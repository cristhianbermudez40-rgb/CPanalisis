from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import email
import html
import hashlib
import imaplib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Set, Tuple
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import pandas as pd

try:
    from app.config import APP_CONFIG, BASE_DIR
    from app.database.conexion_mysql import DB
    from app.reports.report_service import ReportService
    from app.utils.email_meter_parser import parse_meter_email_text
    from app.utils.excel_loader import read_excel_records
    from app.utils.hash_utils import sha256_file, sha256_row
except ModuleNotFoundError:
    # Allow direct execution of this file by adding the project root to sys.path.
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from app.config import APP_CONFIG, BASE_DIR
    from app.database.conexion_mysql import DB
    from app.reports.report_service import ReportService
    from app.utils.email_meter_parser import parse_meter_email_text
    from app.utils.excel_loader import read_excel_records
    from app.utils.hash_utils import sha256_file, sha256_row


class PrintController:
    def __init__(self) -> None:
        self.report_service = ReportService()

    @staticmethod
    def _clip_text(value: str | None, max_len: int = 255, default: str = "") -> str:
        text = (value or "").strip()
        if not text:
            text = default
        if len(text) > max_len:
            text = text[:max_len]
        return text

    def autenticar_acceso(self, username: str, password: str) -> Dict:
        user_ok = (username or "").strip() == APP_CONFIG.login_user
        pass_ok = (password or "") == APP_CONFIG.login_password
        if user_ok and pass_ok:
            return {"ok": True, "usuario": APP_CONFIG.login_user}
        return {"ok": False, "mensaje": "Usuario o contrasena incorrecta"}

    def validar_admin(self, admin_password: str) -> Dict:
        if (admin_password or "") == APP_CONFIG.admin_password:
            return {"ok": True}
        return {"ok": False, "mensaje": "Clave admin invalida"}

    def actualizar_credenciales(self, user: str, user_password: str, admin_password: str) -> Dict:
        user = self._clip_text(user, 120, "").strip()
        if not user or not user_password or not admin_password:
            return {"ok": False, "mensaje": "Todos los campos son obligatorios"}

        env_path = BASE_DIR / ".env"
        if not env_path.exists():
            return {"ok": False, "mensaje": "No existe el archivo .env"}

        lines = env_path.read_text(encoding="utf-8").splitlines()
        replaced = {"APP_LOGIN_USER": False, "APP_LOGIN_PASSWORD": False, "APP_ADMIN_PASSWORD": False}
        out: list[str] = []

        for line in lines:
            if line.startswith("APP_LOGIN_USER="):
                out.append(f"APP_LOGIN_USER={user}")
                replaced["APP_LOGIN_USER"] = True
            elif line.startswith("APP_LOGIN_PASSWORD="):
                out.append(f"APP_LOGIN_PASSWORD={user_password}")
                replaced["APP_LOGIN_PASSWORD"] = True
            elif line.startswith("APP_ADMIN_PASSWORD="):
                out.append(f"APP_ADMIN_PASSWORD={admin_password}")
                replaced["APP_ADMIN_PASSWORD"] = True
            else:
                out.append(line)

        if not replaced["APP_LOGIN_USER"]:
            out.append(f"APP_LOGIN_USER={user}")
        if not replaced["APP_LOGIN_PASSWORD"]:
            out.append(f"APP_LOGIN_PASSWORD={user_password}")
        if not replaced["APP_ADMIN_PASSWORD"]:
            out.append(f"APP_ADMIN_PASSWORD={admin_password}")

        env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return {"ok": True, "mensaje": "Credenciales actualizadas. Reinicia la app para aplicar cambios."}

    def _get_or_create_oficina(self, nombre: str, ciudad: str | None) -> int:
        nombre = self._clip_text(nombre, max_len=255, default="Sin oficina")
        ciudad = self._clip_text(ciudad, max_len=255) or None
        row = DB.fetch_one("SELECT id FROM oficinas WHERE nombre = %s", (nombre,))
        if row:
            if ciudad:
                DB.execute("UPDATE oficinas SET ciudad = COALESCE(ciudad, %s) WHERE id = %s", (ciudad, row["id"]))
            return row["id"]

        DB.execute("INSERT INTO oficinas (nombre, ciudad) VALUES (%s, %s)", (nombre, ciudad))
        row = DB.fetch_one("SELECT id FROM oficinas WHERE nombre = %s", (nombre,))
        return int(row["id"])

    def _get_or_create_usuario(self, nombre: str, oficina_id: int) -> int:
        nombre = self._clip_text(nombre, max_len=255, default="Sistema")
        row = DB.fetch_one(
            "SELECT id FROM usuarios WHERE nombre = %s AND oficina_id <=> %s",
            (nombre, oficina_id),
        )
        if row:
            return row["id"]

        DB.execute("INSERT INTO usuarios (nombre, oficina_id) VALUES (%s, %s)", (nombre, oficina_id))
        row = DB.fetch_one(
            "SELECT id FROM usuarios WHERE nombre = %s AND oficina_id <=> %s",
            (nombre, oficina_id),
        )
        return int(row["id"])

    def _get_or_create_impresora(
        self,
        nombre: str,
        numero_serie: str,
        oficina_id: int,
        ciudad: str | None,
        modelo: str,
    ) -> int:
        nombre = self._clip_text(nombre, max_len=255, default="Impresora")
        numero_serie = self._clip_text(numero_serie, max_len=180, default="SIN-SERIE")
        ciudad = self._clip_text(ciudad, max_len=255) or None
        modelo = self._clip_text(modelo, max_len=255, default="M3655idn")
        row = DB.fetch_one("SELECT id FROM impresoras WHERE numero_serie = %s", (numero_serie,))
        if row:
            DB.execute(
                """
                UPDATE impresoras
                SET nombre = %s,
                    oficina_id = %s,
                    ciudad = COALESCE(ciudad, %s),
                    modelo = COALESCE(modelo, %s)
                WHERE id = %s
                """,
                (nombre, oficina_id, ciudad, modelo, row["id"]),
            )
            return row["id"]

        DB.execute(
            "INSERT INTO impresoras (nombre, numero_serie, modelo, oficina_id, ciudad) VALUES (%s, %s, %s, %s, %s)",
            (nombre, numero_serie, modelo, oficina_id, ciudad),
        )
        row = DB.fetch_one("SELECT id FROM impresoras WHERE numero_serie = %s", (numero_serie,))
        return int(row["id"])

    def evitar_duplicados(self, row_payload: Tuple) -> str:
        return sha256_row(row_payload)

    def cargar_excel(self, file_path: str) -> Dict:
        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(f"No existe el archivo: {source}")

        APP_CONFIG.upload_dir.mkdir(parents=True, exist_ok=True)
        file_hash = sha256_file(source)

        existing = DB.fetch_one("SELECT COUNT(*) AS total FROM impresiones WHERE file_hash = %s", (file_hash,))
        if existing and existing["total"] > 0:
            return {"insertados": 0, "duplicados": existing["total"], "mensaje": "Archivo ya cargado previamente"}

        records = read_excel_records(source)
        if not records:
            return {
                "ok": False,
                "insertados": 0,
                "duplicados": 0,
                "mensaje": "No se encontraron registros validos en el Excel",
            }

        rows_to_insert = []
        duplicate_count = 0
        seen_hashes: set[str] = set()

        for record in records:
            oficina_id = self._get_or_create_oficina(record["oficina"], record["ciudad"])
            usuario_id = self._get_or_create_usuario(record["usuario"], oficina_id)
            impresora_id = self._get_or_create_impresora(
                record["impresora"],
                record["numero_serie"],
                oficina_id,
                record["ciudad"],
                record["modelo"],
            )

            row_payload = (
                record["fecha"],
                record["usuario"],
                record["oficina"],
                record["numero_serie"],
                record["tipo_documento"],
                record["paginas"],
                record["contador_actual"],
                record["tipo_impresion"],
            )
            row_hash = self.evitar_duplicados(row_payload)
            if row_hash in seen_hashes:
                duplicate_count += 1
                continue

            seen_hashes.add(row_hash)
            exists = DB.fetch_one("SELECT id FROM impresiones WHERE row_hash = %s", (row_hash,))
            if exists:
                duplicate_count += 1
                continue

            rows_to_insert.append(
                (
                    record["fecha"],
                    usuario_id,
                    oficina_id,
                    impresora_id,
                    record["tipo_documento"],
                    record["paginas"],
                    record["contador_actual"],
                    record["tipo_impresion"],
                    file_hash,
                    row_hash,
                )
            )

        inserted_count = DB.executemany(
            """
            INSERT IGNORE INTO impresiones (
                fecha, usuario_id, oficina_id, impresora_id, tipo_documento,
                paginas, contador_actual, tipo_impresion, file_hash, row_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows_to_insert,
        )

        duplicate_count += max(len(rows_to_insert) - inserted_count, 0)

        if inserted_count == 0 and duplicate_count > 0:
            return {
                "ok": True,
                "insertados": 0,
                "duplicados": duplicate_count,
                "mensaje": "Archivo procesado: todos los registros ya existian (duplicados)",
            }

        return {
            "ok": True,
            "insertados": inserted_count,
            "duplicados": duplicate_count,
            "mensaje": "Carga completada",
        }

    def cargar_excel_masivo(self, folder_path: str) -> Dict:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"No existe la carpeta: {folder}")

        excel_files = [
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls"} and not path.name.startswith("~$")
        ]

        if not excel_files:
            return {
                "ok": False,
                "mensaje": "No se encontraron archivos Excel en la carpeta seleccionada",
                "archivos_procesados": 0,
                "insertados": 0,
                "duplicados": 0,
                "errores": [],
            }

        total_insertados = 0
        total_duplicados = 0
        processed = 0
        errors: List[Dict[str, str]] = []

        for file_path in sorted(excel_files):
            try:
                result = self.cargar_excel(str(file_path))
                total_insertados += int(result.get("insertados", 0))
                total_duplicados += int(result.get("duplicados", 0))
                processed += 1
            except Exception as exc:
                errors.append({"archivo": str(file_path), "error": str(exc)})

        ok = processed > 0
        message = (
            "Carga masiva completada"
            if ok
            else "No se pudo procesar ningun archivo Excel"
        )

        return {
            "ok": ok,
            "mensaje": message,
            "archivos_encontrados": len(excel_files),
            "archivos_procesados": processed,
            "insertados": total_insertados,
            "duplicados": total_duplicados,
            "errores": errors,
        }

    def limpiar_registros(self) -> Dict:
        DB.execute("DELETE FROM mantenimientos")
        DB.execute("DELETE FROM contadores")
        DB.execute("DELETE FROM impresiones")
        DB.execute("DELETE FROM usuarios")
        DB.execute("DELETE FROM impresoras")
        DB.execute("DELETE FROM oficinas")
        return {"ok": True, "mensaje": "Base de datos limpia y contador de analisis reiniciado"}

    def reiniciar_contador_analisis(self) -> Dict:
        DB.execute("DELETE FROM contadores")
        DB.execute("DELETE FROM mantenimientos")
        return {"ok": True, "mensaje": "Contadores y alertas de mantenimiento reiniciados"}

    def comparar_contadores(self, numero_serie: str, contador_proveedor: int, contador_maquina: int) -> Dict:
        diferencia = contador_maquina - contador_proveedor
        base = contador_proveedor if contador_proveedor > 0 else 1
        porcentaje_error = abs(diferencia) * 100 / base

        printer = DB.fetch_one("SELECT id FROM impresoras WHERE numero_serie = %s", (numero_serie,))
        if printer:
            DB.execute(
                """
                INSERT INTO contadores (
                    impresora_id, fecha, contador_proveedor, contador_maquina, diferencia, porcentaje_error
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (printer["id"], date.today(), contador_proveedor, contador_maquina, diferencia, porcentaje_error),
            )

        return {
            "ok": True,
            "numero_serie": numero_serie,
            "contador_proveedor": contador_proveedor,
            "contador_maquina": contador_maquina,
            "diferencia": diferencia,
            "porcentaje_error": round(porcentaje_error, 2),
        }

    def comparar_contadores_mensual(self, numero_serie: str, periodo: str, contador_proveedor: int) -> Dict:
        periodo = (periodo or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", periodo):
            return {"ok": False, "mensaje": "Periodo invalido. Usa formato YYYY-MM"}

        row = DB.fetch_one(
            """
            SELECT
                MAX(i.contador_actual) AS contador_maquina,
                SUM(i.paginas) AS volumen_mes,
                COUNT(*) AS registros_mes
            FROM impresiones i
            JOIN impresoras p ON p.id = i.impresora_id
            WHERE p.numero_serie = %s
              AND DATE_FORMAT(i.fecha, '%Y-%m') = %s
              AND i.contador_actual IS NOT NULL
            """,
            (numero_serie, periodo),
        )

        if not row or row.get("contador_maquina") is None:
            return {
                "ok": False,
                "mensaje": (
                    f"No se encontro contador de maquina para la serie {numero_serie} "
                    f"en el periodo {periodo}. Verifica que ese mes exista en el Excel."
                ),
            }

        contador_maquina = int(row["contador_maquina"])
        payload = self.comparar_contadores(numero_serie, contador_proveedor, contador_maquina)
        payload.update(
            {
                "periodo": periodo,
                "volumen_mes": int(row.get("volumen_mes") or 0),
                "registros_mes": int(row.get("registros_mes") or 0),
                "fuente_maquina": "MAX(contador_actual) del mes en impresiones",
            }
        )
        return payload

    def _periodo_anterior(self, fecha: date) -> str:
        """Dado un date, devuelve el mes anterior en formato YYYY-MM.

        Lógica de negocio: el proveedor emite el Excel con fecha de lectura
        en el mes X (ej. 27/04/2026), pero ese contador cubre el mes X-1
        (ej. marzo 2026, corte 30/03/2026). Esta función hace esa conversión.
        """
        if fecha.month == 1:
            return f"{fecha.year - 1}-12"
        return f"{fecha.year}-{fecha.month - 1:02d}"

    def auto_comparar_mes_actual(self) -> Dict:
        """Compara proveedor (Excel) vs maquina (correo).

        LÓGICA CORRECTA:
        - El Excel tiene fecha de facturación (ej. 27/04/2026).
        - Esa fecha representa los contadores del MES ANTERIOR (ej. marzo 2026).
        - Buscamos el batch de Excel MÁS RECIENTE importado.
        - Derivamos periodo_real = mes_anterior(fecha_excel).
        - Comparamos contra el contador de correo MÁS CERCANO a la fecha_excel de cada impresora.
        """
        # ── 1. Encontrar la fecha más reciente de Excel importado ──────────────
        latest_row = DB.fetch_one(
            "SELECT MAX(fecha) AS ultima_fecha FROM impresiones WHERE contador_actual IS NOT NULL"
        )
        if not latest_row or not latest_row.get("ultima_fecha"):
            return {"ok": False, "mensaje": "No hay datos de Excel cargados aún"}

        ultima_fecha = latest_row["ultima_fecha"]
        if isinstance(ultima_fecha, str):
            ultima_fecha = date.fromisoformat(ultima_fecha)

        # El Excel de la fecha X cubre el mes X-1
        periodo_excel = ultima_fecha.strftime("%Y-%m")       # ej. "2026-04"
        periodo_real  = self._periodo_anterior(ultima_fecha) # ej. "2026-03"

        # ── 2. Excel: contador del proveedor con la fecha exacta por impresora ─
        # MAX(i.fecha) = fecha de facturación de esa impresora en el período
        rows = DB.fetch_all(
            """
            SELECT p.numero_serie,
                   MAX(i.contador_actual) AS contador_proveedor,
                   MAX(i.fecha)           AS fecha_excel,
                   COALESCE(o.nombre, '') AS oficina
            FROM impresiones i
            JOIN impresoras p ON p.id = i.impresora_id
            LEFT JOIN oficinas o ON o.id = i.oficina_id
            WHERE DATE_FORMAT(i.fecha, '%Y-%m') = %s AND i.contador_actual IS NOT NULL
            GROUP BY p.numero_serie, o.nombre
            """,
            (periodo_excel,),
        )

        comparados = []
        sin_correo = []

        for row in rows:
            serial     = row["numero_serie"]
            oficina    = row.get("oficina") or ""
            # Fecha exacta del Excel para esta impresora (ej. 2026-04-27)
            fecha_excel_str = str(row.get("fecha_excel") or ultima_fecha)

            # ── 3. Correo: contador más cercano a la fecha exacta del Excel ────
            email_row = DB.fetch_one(
                """
                SELECT h.contador_efectivo,
                       COALESCE(ir.oficina, h.oficina, '') AS oficina,
                       h.meter_date
                FROM historial_lecturas_email h
                LEFT JOIN impresoras_red ir
                    ON UPPER(TRIM(ir.numero_serie)) = UPPER(TRIM(h.serial_number))
                WHERE UPPER(TRIM(h.serial_number)) = UPPER(TRIM(%s))
                  AND h.contador_efectivo IS NOT NULL
                ORDER BY ABS(DATEDIFF(h.meter_date, %s)) ASC, h.meter_date DESC
                LIMIT 1
                """,
                (serial, fecha_excel_str),
            )

            # Fallback: tabla lecturas_email_impresoras si no hay en historial
            if not email_row or not email_row.get("contador_efectivo"):
                email_row = DB.fetch_one(
                    """
                    SELECT le.contador_efectivo,
                           COALESCE(ir.oficina, '') AS oficina
                    FROM lecturas_email_impresoras le
                    LEFT JOIN impresoras_red ir
                        ON UPPER(TRIM(ir.numero_serie)) = UPPER(TRIM(le.serial_number))
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(%s))
                      AND le.contador_efectivo IS NOT NULL
                    ORDER BY ABS(DATEDIFF(COALESCE(le.meter_date, le.imported_at), %s)) ASC
                    LIMIT 1
                    """,
                    (serial, fecha_excel_str),
                )

            cprov = int(row["contador_proveedor"])

            if email_row and email_row.get("contador_efectivo"):
                cmaq    = int(email_row["contador_efectivo"])
                dif     = cmaq - cprov
                pct     = round(abs(dif) * 100 / max(cprov, 1), 2)
                oficina = email_row.get("oficina") or oficina
                fuente_registro = "auto_excel"
            else:
                # Sin lectura de correo: guardar igual con maquina=0 para que aparezca en la tabla
                cmaq    = 0
                dif     = 0
                pct     = 0.0
                fuente_registro = "auto_excel_sin_correo"
                sin_correo.append(serial)

            comparados.append({
                "numero_serie": serial,
                "oficina": oficina,
                "contador_proveedor": cprov,
                "contador_maquina": cmaq,
                "diferencia": dif,
                "porcentaje_error": pct,
                "periodo_excel": periodo_excel,
                "periodo_real": periodo_real,
                "fuente": fuente_registro,
            })
            try:
                DB.execute(
                    """
                    INSERT INTO reportes_comparativos
                        (periodo, numero_serie, oficina, contador_proveedor, contador_maquina,
                         diferencia, porcentaje_error, fuente)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        contador_proveedor = VALUES(contador_proveedor),
                        contador_maquina   = VALUES(contador_maquina),
                        diferencia         = VALUES(diferencia),
                        porcentaje_error   = VALUES(porcentaje_error),
                        fuente             = VALUES(fuente),
                        guardado_en        = CURRENT_TIMESTAMP
                    """,
                    (periodo_real, serial, oficina, cprov, cmaq, dif, pct, fuente_registro),
                )
            except Exception:
                pass

        return {
            "ok": True,
            "periodo_excel": periodo_excel,
            "periodo_real": periodo_real,
            "comparados": len(comparados),
            "sin_correo": len(sin_correo),
            "resultados": comparados,
        }

    def listar_comparativos_periodo(self, periodo: str) -> List[Dict]:
        """Retorna los comparativos guardados para un periodo YYYY-MM."""
        return DB.fetch_all(
            """
            SELECT periodo, numero_serie, oficina, contador_proveedor, contador_maquina,
                   diferencia, porcentaje_error, fuente, guardado_en
            FROM reportes_comparativos
            WHERE periodo = %s
            ORDER BY ABS(diferencia) DESC
            """,
            (periodo,),
        ) or []

    def listar_periodos_comparativos(self) -> List[str]:
        rows = DB.fetch_all(
            "SELECT DISTINCT periodo FROM reportes_comparativos ORDER BY periodo DESC LIMIT 24"
        ) or []
        return [r["periodo"] for r in rows]

    def generar_estadisticas(self) -> Dict:
        top_usuario = DB.fetch_one(
            """
            SELECT u.nombre AS usuario, SUM(i.paginas) AS paginas
            FROM impresiones i
            JOIN usuarios u ON u.id = i.usuario_id
            GROUP BY u.nombre
            ORDER BY paginas DESC
            LIMIT 1
            """
        )
        top_oficina = DB.fetch_one(
            """
            SELECT o.nombre AS oficina, SUM(i.paginas) AS paginas
            FROM impresiones i
            JOIN oficinas o ON o.id = i.oficina_id
            GROUP BY o.nombre
            ORDER BY paginas DESC
            LIMIT 1
            """
        )
        ranking_oficinas = DB.fetch_all(
            """
            SELECT o.nombre AS oficina, COALESCE(o.ciudad, 'Sin ciudad') AS ciudad, SUM(i.paginas) AS paginas
            FROM impresiones i
            JOIN oficinas o ON o.id = i.oficina_id
            GROUP BY o.nombre, o.ciudad
            ORDER BY paginas DESC
            LIMIT 10
            """
        )
        mes_vs_mes = DB.fetch_all(
            """
            SELECT DATE_FORMAT(i.fecha, '%Y-%m') AS periodo, SUM(i.paginas) AS paginas
            FROM impresiones i
            GROUP BY DATE_FORMAT(i.fecha, '%Y-%m')
            ORDER BY periodo
            """
        )
        documentos = DB.fetch_all(
            """
            SELECT tipo_documento, SUM(paginas) AS paginas
            FROM impresiones
            GROUP BY tipo_documento
            ORDER BY paginas DESC
            """
        )
        tendencia_mensual = self._build_monthly_trend(mes_vs_mes)
        estado_impresoras = DB.fetch_all(
            """
            SELECT p.numero_serie, p.nombre AS impresora, COALESCE(o.nombre, 'N/A') AS oficina,
                   SUM(i.paginas) AS paginas
            FROM impresoras p
            LEFT JOIN impresiones i ON i.impresora_id = p.id
            LEFT JOIN oficinas o ON o.id = p.oficina_id
            GROUP BY p.id, p.numero_serie, p.nombre, o.nombre
            ORDER BY paginas DESC
            """
        )

        reduced_office = self._office_reduction_by_month()

        # Periodo más reciente en Excel
        ultimo_per = DB.fetch_one(
            "SELECT DATE_FORMAT(MAX(fecha), '%Y-%m') AS periodo FROM impresiones"
        )
        periodo_excel = (ultimo_per or {}).get("periodo")

        # Correo = Maquina: suma del último contador efectivo por impresora (lo que registra la maquina)
        row_maq = DB.fetch_one(
            """
            SELECT SUM(sub.cnt) AS total FROM (
                SELECT MAX(le.contador_efectivo) AS cnt
                FROM lecturas_email_impresoras le
                WHERE le.contador_efectivo IS NOT NULL
                GROUP BY le.serial_number
            ) sub
            """
        )
        cnt_maquina_total = int(row_maq["total"]) if row_maq and row_maq.get("total") else None

        # Excel = Proveedor: suma de MAX(contador_actual) del ultimo periodo cargado
        cnt_proveedor_total = None
        if periodo_excel:
            row_prov = DB.fetch_one(
                """
                SELECT SUM(sub.cnt) AS total FROM (
                    SELECT MAX(i.contador_actual) AS cnt
                    FROM impresiones i
                    JOIN impresoras p ON p.id = i.impresora_id
                    WHERE DATE_FORMAT(i.fecha, '%%Y-%%m') = %s
                      AND i.contador_actual IS NOT NULL
                    GROUP BY p.numero_serie
                ) sub
                """,
                (periodo_excel,),
            )
            cnt_proveedor_total = int(row_prov["total"]) if row_prov and row_prov.get("total") else None

        return {
            "total_impresiones": sum(r["paginas"] for r in tendencia_mensual["serie"]) if tendencia_mensual["serie"] else 0,
            "top_usuario": top_usuario,
            "top_oficina": top_oficina,
            "ranking_oficinas": ranking_oficinas,
            "mes_vs_mes": tendencia_mensual["serie"],
            "mensual_resumen": tendencia_mensual["resumen"],
            "documentos": documentos,
            "estado_impresoras": estado_impresoras,
            "oficina_reduccion": reduced_office,
            "mantenimiento": self.programa_mantenimiento(),
            "toner": self.analisis_toner_m3655idn(),
            "contadores_comparados": self.resumen_comparador_contadores(),
            "contadores_excel": self.ultimo_contador_reportado_excel(),
            "periodo_excel": periodo_excel,
            "contador_maquina_total": cnt_maquina_total,
            "contador_proveedor_total": cnt_proveedor_total,
        }

    def _build_monthly_trend(self, mes_vs_mes: List[Dict]) -> Dict[str, Any]:
        if not mes_vs_mes:
            return {"serie": [], "resumen": {}}

        df = pd.DataFrame(mes_vs_mes)
        if df.empty:
            return {"serie": [], "resumen": {}}

        df["periodo"] = pd.to_datetime(df["periodo"].astype(str) + "-01", errors="coerce")
        df["paginas"] = pd.to_numeric(df["paginas"], errors="coerce").fillna(0)
        df = df.dropna(subset=["periodo"]).sort_values("periodo")
        if df.empty:
            return {"serie": [], "resumen": {}}

        df = df.set_index("periodo").asfreq("MS", fill_value=0).reset_index()
        df["paginas"] = df["paginas"].astype(int)
        df["media_movil_3m"] = df["paginas"].rolling(window=3, min_periods=1).mean().round(2)
        df["delta_paginas"] = df["paginas"].diff().fillna(0).astype(int)

        base = df["paginas"].shift(1).replace(0, pd.NA)
        df["delta_pct"] = (((df["paginas"] - base) / base) * 100).fillna(0).round(2)
        df["periodo"] = df["periodo"].dt.strftime("%Y-%m")

        serie = [
            {
                "periodo": row["periodo"],
                "paginas": int(row["paginas"]),
                "media_movil_3m": float(row["media_movil_3m"]),
                "delta_paginas": int(row["delta_paginas"]),
                "delta_pct": float(row["delta_pct"]),
            }
            for _, row in df.iterrows()
        ]

        idx_max = int(df["paginas"].idxmax())
        idx_min = int(df["paginas"].idxmin())
        resumen = {
            "promedio_mensual": float(round(df["paginas"].mean(), 2)),
            "ultimo_delta_pct": float(df.iloc[-1]["delta_pct"]),
            "mejor_mes": {
                "periodo": str(df.iloc[idx_max]["periodo"]),
                "paginas": int(df.iloc[idx_max]["paginas"]),
            },
            "mes_mas_bajo": {
                "periodo": str(df.iloc[idx_min]["periodo"]),
                "paginas": int(df.iloc[idx_min]["paginas"]),
            },
        }
        return {"serie": serie, "resumen": resumen}

    def resumen_comparador_contadores(self) -> List[Dict]:
        rows = DB.fetch_all(
            """
            SELECT
                DATE_FORMAT(c.fecha, '%Y-%m-%d') AS fecha,
                p.numero_serie,
                p.nombre AS impresora,
                COALESCE(o.nombre, 'N/A') AS oficina,
                c.contador_proveedor,
                c.contador_maquina,
                c.diferencia,
                c.porcentaje_error
            FROM contadores c
            JOIN impresoras p ON p.id = c.impresora_id
            LEFT JOIN oficinas o ON o.id = p.oficina_id
            ORDER BY c.fecha DESC, c.id DESC
            LIMIT 20
            """
        )

        # Si no hay comparaciones manuales, habilita el comparador
        # tomando proveedor (Excel) vs maquina (correo de contadores).
        if not rows:
            rows = DB.fetch_all(
                """
                SELECT
                    DATE_FORMAT(COALESCE(mc.meter_date, mc.imported_at), '%Y-%m-%d') AS fecha,
                    ex.numero_serie,
                    ex.impresora,
                    ex.oficina,
                    ex.contador_proveedor,
                    mc.contador_maquina,
                    (mc.contador_maquina - ex.contador_proveedor) AS diferencia,
                    ROUND(
                        ABS(mc.contador_maquina - ex.contador_proveedor) * 100 / GREATEST(ex.contador_proveedor, 1),
                        2
                    ) AS porcentaje_error
                FROM (
                    SELECT
                        p.id AS impresora_id,
                        p.numero_serie,
                        p.nombre AS impresora,
                        COALESCE(o.nombre, 'N/A') AS oficina,
                        MAX(i.contador_actual) AS contador_proveedor,
                        MAX(i.fecha) AS fecha_proveedor
                    FROM impresiones i
                    JOIN impresoras p ON p.id = i.impresora_id
                    LEFT JOIN oficinas o ON o.id = p.oficina_id
                    WHERE i.contador_actual IS NOT NULL
                    GROUP BY p.id, p.numero_serie, p.nombre, o.nombre
                ) ex
                JOIN (
                    SELECT le1.serial_number, le1.contador_efectivo AS contador_maquina, le1.meter_date, le1.imported_at
                    FROM lecturas_email_impresoras le1
                    JOIN (
                        SELECT serial_number, MAX(COALESCE(meter_date, imported_at)) AS max_dt
                        FROM lecturas_email_impresoras
                        WHERE serial_number IS NOT NULL
                          AND serial_number <> ''
                          AND contador_efectivo IS NOT NULL
                        GROUP BY serial_number
                    ) le2
                      ON le2.serial_number = le1.serial_number
                     AND COALESCE(le1.meter_date, le1.imported_at) = le2.max_dt
                    WHERE le1.contador_efectivo IS NOT NULL
                ) mc ON mc.serial_number = ex.numero_serie
                ORDER BY COALESCE(mc.meter_date, mc.imported_at) DESC
                LIMIT 20
                """
            )

        for row in rows:
            error = float(row.get("porcentaje_error", 0) or 0)
            if error <= 2:
                estado = "OK"
            elif error <= 5:
                estado = "Revision"
            else:
                estado = "Alerta"
            row["estado"] = estado

        return rows

    def ultimo_contador_reportado_excel(self) -> List[Dict]:
        return DB.fetch_all(
            """
            SELECT
                DATE_FORMAT(i.fecha, '%Y-%m-%d') AS fecha,
                p.numero_serie,
                p.nombre AS impresora,
                COALESCE(o.nombre, 'N/A') AS oficina,
                i.contador_actual
            FROM impresiones i
            JOIN impresoras p ON p.id = i.impresora_id
            LEFT JOIN oficinas o ON o.id = p.oficina_id
            JOIN (
                SELECT impresora_id, MAX(fecha) AS max_fecha
                FROM impresiones
                WHERE contador_actual IS NOT NULL
                GROUP BY impresora_id
            ) mx ON mx.impresora_id = i.impresora_id AND mx.max_fecha = i.fecha
            WHERE i.contador_actual IS NOT NULL
            ORDER BY i.fecha DESC
            LIMIT 20
            """
        )

    def _office_reduction_by_month(self) -> Dict:
        rows = DB.fetch_all(
            """
            SELECT o.nombre AS oficina,
                   DATE_FORMAT(i.fecha, '%Y-%m') AS periodo,
                   SUM(i.paginas) AS paginas
            FROM impresiones i
            JOIN oficinas o ON o.id = i.oficina_id
            GROUP BY o.nombre, DATE_FORMAT(i.fecha, '%Y-%m')
            ORDER BY o.nombre, periodo
            """
        )
        by_office: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for row in rows:
            by_office[row["oficina"]].append((row["periodo"], int(row["paginas"])))

        best_office = {"oficina": None, "reduccion": 0, "periodo": None}
        for office, periods in by_office.items():
            if len(periods) < 2:
                continue
            prev = periods[-2][1]
            curr = periods[-1][1]
            reduction = prev - curr
            if reduction > best_office["reduccion"]:
                best_office = {
                    "oficina": office,
                    "reduccion": reduction,
                    "periodo": f"{periods[-2][0]} vs {periods[-1][0]}",
                }
        return best_office

    def analisis_toner_m3655idn(self) -> Dict:
        monthly = DB.fetch_all(
            """
            SELECT DATE_FORMAT(i.fecha, '%Y-%m') AS periodo, SUM(i.paginas) AS paginas
            FROM impresiones i
            JOIN impresoras p ON p.id = i.impresora_id
            WHERE p.modelo = 'M3655idn'
            GROUP BY DATE_FORMAT(i.fecha, '%Y-%m')
            ORDER BY periodo
            """
        )
        toner_yield = APP_CONFIG.toner_yield_m3655idn
        estimado = []
        acumulado = 0

        for row in monthly:
            paginas = int(row["paginas"])
            acumulado += paginas
            toner = paginas / toner_yield
            restante = max(toner_yield - (acumulado % toner_yield), 0)
            estimado.append(
                {
                    "periodo": row["periodo"],
                    "paginas": paginas,
                    "toner_estimado": round(toner, 2),
                    "paginas_restantes_cambio": restante,
                }
            )

        proximo_cambio = None
        if estimado:
            last = estimado[-1]
            proximo_cambio = {
                "periodo_referencia": last["periodo"],
                "paginas_restantes": last["paginas_restantes_cambio"],
            }

        return {
            "rendimiento_toner": toner_yield,
            "mensual": estimado,
            "prediccion_cambio": proximo_cambio,
        }

    @staticmethod
    def _maintenance_plan_m3655idn(contador_vida: int) -> Dict:
        # Politica escalonada para ECOSYS M3655idn basada en contador de vida.
        # Los hitos pueden ajustarse por ambiente de uso sin tocar la vista.
        hitos = [
            {
                "hito": 100000,
                "tipo": "Preventivo Inicial",
                "tareas": "Limpieza interna, revision de rodillos de alimentacion y calibracion de calidad.",
            },
            {
                "hito": 200000,
                "tipo": "Mantenimiento Mayor",
                "tareas": "Revision/cambio de kit de mantenimiento (rodillos/unidades de arrastre) y ajuste general.",
            },
            {
                "hito": 300000,
                "tipo": "Mantenimiento Critico",
                "tareas": "Revision de unidad fusora y componentes de desgaste critico; evaluar recambio de kit completo.",
            },
            {
                "hito": 400000,
                "tipo": "Overhaul",
                "tareas": "Mantenimiento integral de ciclo alto y validacion tecnica completa del equipo.",
            },
        ]

        siguiente = None
        for h in hitos:
            if contador_vida < h["hito"]:
                siguiente = h
                break

        if not siguiente:
            ultimo_hito = hitos[-1]["hito"]
            ciclos = max((contador_vida - ultimo_hito) // 100000 + 1, 1)
            proximo_hito = ultimo_hito + ciclos * 100000
            siguiente = {
                "hito": proximo_hito,
                "tipo": "Ciclo Alto",
                "tareas": "Equipo en ciclo avanzado: ejecutar mantenimiento integral y plan de renovacion.",
            }

        restante = int(siguiente["hito"]) - int(contador_vida)
        if restante <= 0:
            prioridad = "ALTA"
            estado = "VENCIDO"
        elif restante <= 5000:
            prioridad = "ALTA"
            estado = "PROXIMO"
        elif restante <= 15000:
            prioridad = "MEDIA"
            estado = "PROGRAMAR"
        else:
            prioridad = "BAJA"
            estado = "CONTROL"

        return {
            "hito": int(siguiente["hito"]),
            "tipo": str(siguiente["tipo"]),
            "tareas": str(siguiente["tareas"]),
            "restante": restante,
            "prioridad": prioridad,
            "estado": estado,
        }

    def programa_mantenimiento(self) -> List[Dict]:
        toner_yield = APP_CONFIG.toner_yield_m3655idn
        rows = DB.fetch_all(
            """
            SELECT
                p.id AS impresora_id,
                p.numero_serie,
                p.nombre AS impresora,
                COALESCE(o.nombre, 'N/A') AS oficina,
                COALESCE(p.modelo, 'M3655idn') AS modelo,
                COALESCE(SUM(i.paginas), 0) AS paginas,
                MAX(i.contador_actual) AS contador_excel,
                                (
                                        SELECT le.contador_efectivo
                                        FROM lecturas_email_impresoras le
                                        WHERE le.serial_number = p.numero_serie
                                            AND le.contador_efectivo IS NOT NULL
                                        ORDER BY COALESCE(le.meter_date, le.imported_at) DESC
                                        LIMIT 1
                                ) AS contador_email,
                                (
                                        SELECT DATE_FORMAT(COALESCE(le.meter_date, le.imported_at), '%Y-%m-%d %H:%i:%s')
                                        FROM lecturas_email_impresoras le
                                        WHERE le.serial_number = p.numero_serie
                                            AND le.contador_efectivo IS NOT NULL
                                        ORDER BY COALESCE(le.meter_date, le.imported_at) DESC
                                        LIMIT 1
                                ) AS ultima_lectura_email,
                (
                    SELECT MAX(ls.total_paginas)
                    FROM impresoras_red ir
                    JOIN lecturas_snmp ls ON ls.ip_address = ir.ip_address
                    WHERE (ir.numero_serie IS NOT NULL AND ir.numero_serie = p.numero_serie)
                       OR (ir.numero_serie IS NULL AND ir.nombre = p.nombre AND ir.oficina <=> o.nombre)
                ) AS contador_snmp,
                (
                    SELECT MAX(ls.leido_en)
                    FROM impresoras_red ir
                    JOIN lecturas_snmp ls ON ls.ip_address = ir.ip_address
                    WHERE (ir.numero_serie IS NOT NULL AND ir.numero_serie = p.numero_serie)
                       OR (ir.numero_serie IS NULL AND ir.nombre = p.nombre AND ir.oficina <=> o.nombre)
                ) AS ultima_lectura_snmp
            FROM impresoras p
            LEFT JOIN impresiones i ON i.impresora_id = p.id
            LEFT JOIN oficinas o ON o.id = p.oficina_id
            GROUP BY p.id, p.numero_serie, p.nombre, o.nombre, p.modelo
            """
        )
        recommendations: List[Dict] = []

        for row in rows:
            paginas = int(row.get("paginas") or 0)
            contador_email = row.get("contador_email")
            contador_snmp = row.get("contador_snmp")
            contador_excel = row.get("contador_excel")

            if contador_email is not None:
                contador_vida = int(contador_email)
                fuente = "Correo"
            elif contador_snmp is not None:
                contador_vida = int(contador_snmp)
                fuente = "SNMP"
            elif contador_excel is not None:
                contador_vida = int(contador_excel)
                fuente = "Excel"
            else:
                contador_vida = paginas
                fuente = "Paginas acumuladas"

            plan = self._maintenance_plan_m3655idn(contador_vida)

            restante_toner = toner_yield - (contador_vida % toner_yield)
            alerta_toner = restante_toner <= 2000

            recommendations.append(
                {
                    "impresora": row.get("impresora"),
                    "numero_serie": row.get("numero_serie"),
                    "oficina": row.get("oficina"),
                    "modelo": row.get("modelo") or "M3655idn",
                    "contador_vida": contador_vida,
                    "fuente_contador": fuente,
                    "ultima_lectura_email": row.get("ultima_lectura_email"),
                    "ultima_lectura_snmp": row.get("ultima_lectura_snmp"),
                    "hito_mantenimiento": plan["hito"],
                    "estado": plan["estado"],
                    "prioridad": plan["prioridad"],
                    "restante_hito": plan["restante"],
                    "tipo_mantenimiento": plan["tipo"],
                    "recomendacion": plan["tareas"],
                    "toner_restante_estimado": int(restante_toner),
                    "alerta_toner": bool(alerta_toner),
                }
            )

        order = {"ALTA": 0, "MEDIA": 1, "BAJA": 2}
        recommendations.sort(
            key=lambda r: (
                order.get(str(r.get("prioridad")), 9),
                int(r.get("restante_hito") or 0),
                -(int(r.get("contador_vida") or 0)),
            )
        )

        return recommendations

    def sincronizar_mantenimientos(self, regenerar: bool = False) -> Dict:
        """Sincroniza mantenimientos calculados a la BD.

        Calcula mantenimientos para todas las impresoras y los guarda en la tabla.

        Args:
            regenerar: Si True, elimina mantenimientos antiguos y recalcula. Si False, solo agrega nuevos.

        Returns:
            Dict con: {ok, mensaje, generados, existentes, total}
        """
        try:
            if regenerar:
                DB.execute("DELETE FROM mantenimientos")

            # Obtener recomendaciones
            recommendations = self.programa_mantenimiento()

            generados = 0
            existentes = 0

            for rec in recommendations:
                impresora_id = DB.fetch_one(
                    "SELECT id FROM impresoras WHERE numero_serie = %s",
                    (rec.get("numero_serie"),),
                )

                if not impresora_id:
                    continue

                imp_id = int(impresora_id["id"])

                # Verificar si ya existe mantenimiento para esta impresora
                existing = DB.fetch_one(
                    "SELECT id FROM mantenimientos WHERE impresora_id = %s order by fecha_recomendacion desc limit 1",
                    (imp_id,),
                )

                if existing and not regenerar:
                    existentes += 1
                    continue

                # Insertar mantenimiento
                DB.execute(
                    """
                    INSERT INTO mantenimientos (
                        impresora_id, fecha_recomendacion, paginas_acumuladas,
                        tipo, estado, descripcion
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        imp_id,
                        date.today(),
                        rec.get("contador_vida"),
                        rec.get("tipo_mantenimiento"),
                        rec.get("estado"),
                        f"Hito: {rec.get('hito_mantenimiento')} | "
                        f"Restante: {rec.get('restante_hito')} | "
                        f"Prioridad: {rec.get('prioridad')} | "
                        f"Fuente: {rec.get('fuente_contador')} | "
                        f"{rec.get('recomendacion')}",
                    ),
                )
                generados += 1

            return {
                "ok": True,
                "mensaje": f"Sint sync completada: {generados} nuevos, {existentes} existentes",
                "generados": generados,
                "existentes": existentes,
                "total": generados + existentes,
            }
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error sincronizando mantenimientos: {exc}"}

    def obtener_mantenimientos_vigentes(self) -> List[Dict]:
        """Obtiene mantenimientos vigentes de la BD.

        Returns:
            Lista de mantenimientos con detalles de impresoras.
        """
        try:
            rows = DB.fetch_all(
                """
                SELECT
                    m.id,
                    m.impresora_id,
                    m.fecha_recomendacion,
                    m.paginas_acumuladas,
                    m.tipo,
                    m.estado,
                    m.descripcion,
                    m.created_at,
                    p.numero_serie,
                    p.nombre AS impresora,
                    COALESCE(o.nombre, 'N/A') AS oficina,
                    COALESCE(p.modelo, 'M3655idn') AS modelo
                FROM mantenimientos m
                JOIN impresoras p ON p.id = m.impresora_id
                LEFT JOIN oficinas o ON o.id = p.oficina_id
                WHERE m.estado IN ('VENCIDO', 'PROXIMO', 'PROGRAMAR', 'CONTROL', 'PENDIENTE')
                ORDER BY
                    CASE m.estado
                        WHEN 'VENCIDO' THEN 0
                        WHEN 'PROXIMO' THEN 1
                        WHEN 'PROGRAMAR' THEN 2
                        WHEN 'CONTROL' THEN 3
                        ELSE 4
                    END,
                    m.fecha_recomendacion ASC
                """
            )
            return rows or []
        except Exception:
            return []

    def listar_periodos_disponibles(self) -> List[str]:
        rows = DB.fetch_all(
            """
            SELECT DISTINCT DATE_FORMAT(fecha, '%Y-%m') AS periodo
            FROM impresiones
            ORDER BY periodo DESC
            """
        )
        return [row["periodo"] for row in rows if row.get("periodo")]

    @staticmethod
    def _periodo_anterior(periodo: str) -> str:
        dt = datetime.strptime(periodo, "%Y-%m")
        year = dt.year
        month = dt.month - 1
        if month == 0:
            month = 12
            year -= 1
        return f"{year:04d}-{month:02d}"

    def generar_reporte_general_oficinas(self, periodo: str | None = None) -> Dict:
        """Reporte general basado en las 32 impresoras de impresoras_red + contadores de correo.

        El periodo es opcional — si se da, filtra datos Excel de ese mes para complementar.
        Siempre muestra las 32 impresoras aunque no tengan Excel cargado.
        """
        periodo = (periodo or "").strip()
        if periodo and not re.fullmatch(r"\d{4}-\d{2}", periodo):
            return {"ok": False, "mensaje": "Periodo invalido. Usa formato YYYY-MM"}

        # Base: todas las impresoras registradas
        impresoras_raw = DB.fetch_all(
            """
            SELECT ir.nombre, ir.numero_serie, ir.oficina, ir.canal, ir.modelo, ir.area,
                   (SELECT le.contador_efectivo
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.contador_efectivo IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC LIMIT 1
                   ) AS contador_maquina,
                   (SELECT DATE_FORMAT(COALESCE(le.meter_date, le.imported_at), '%Y-%m-%d')
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.contador_efectivo IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC LIMIT 1
                   ) AS ultima_lectura,
                   (SELECT le.toner_black_pct
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.toner_black_pct IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC LIMIT 1
                   ) AS toner_pct
            FROM impresoras_red ir
            ORDER BY ir.oficina ASC, ir.nombre ASC
            """
        ) or []

        # Datos Excel por serial para el periodo dado (opcional)
        excel_map: Dict[str, Dict] = {}
        if periodo:
            excel_rows = DB.fetch_all(
                """
                SELECT p.numero_serie,
                       SUM(i.paginas) AS paginas,
                       COUNT(*) AS trabajos,
                       MAX(i.contador_actual) AS contador_proveedor
                FROM impresiones i
                JOIN impresoras p ON p.id = i.impresora_id
                WHERE DATE_FORMAT(i.fecha, '%Y-%m') = %s
                  AND i.contador_actual IS NOT NULL
                GROUP BY p.numero_serie
                """,
                (periodo,),
            ) or []
            for r in excel_rows:
                excel_map[str(r["numero_serie"] or "").upper().strip()] = r

        # Agrupar por oficina
        from collections import defaultdict
        oficinas_dict: Dict[str, list] = defaultdict(list)
        for p in impresoras_raw:
            oficinas_dict[p["oficina"] or "Sin oficina"].append(p)

        resumen_oficinas = []
        detalle_impresoras = []

        for oficina in sorted(oficinas_dict.keys()):
            printers = oficinas_dict[oficina]
            con_datos = sum(1 for p in printers if p.get("contador_maquina"))
            contadores = [int(p["contador_maquina"]) for p in printers if p.get("contador_maquina")]
            paginas_list = []
            for p in printers:
                key = str(p.get("numero_serie") or "").upper().strip()
                ex = excel_map.get(key, {})
                pags = int(ex.get("paginas") or 0)
                paginas_list.append(pags)

            resumen_oficinas.append({
                "oficina": oficina,
                "impresoras_total": len(printers),
                "impresoras_con_datos": con_datos,
                "suma_contadores": sum(contadores),
                "max_contador": max(contadores) if contadores else 0,
                "paginas_excel": sum(paginas_list),
            })

            for p in printers:
                key = str(p.get("numero_serie") or "").upper().strip()
                ex = excel_map.get(key, {})
                cnt_maq = int(p["contador_maquina"]) if p.get("contador_maquina") else None
                cnt_prov = int(ex["contador_proveedor"]) if ex.get("contador_proveedor") else None
                diferencia = (cnt_maq - cnt_prov) if (cnt_maq and cnt_prov) else None
                detalle_impresoras.append({
                    "oficina": oficina,
                    "impresora": p["nombre"],
                    "numero_serie": p["numero_serie"],
                    "canal": p.get("canal") or "-",
                    "area": p.get("area") or "",
                    "modelo": p.get("modelo") or "",
                    "contador_maquina": cnt_maq,
                    "ultima_lectura": p.get("ultima_lectura") or "-",
                    "toner_pct": p.get("toner_pct"),
                    "contador_proveedor": cnt_prov,
                    "paginas_excel": int(ex.get("paginas") or 0),
                    "trabajos_excel": int(ex.get("trabajos") or 0),
                    "diferencia": diferencia,
                })

        if not impresoras_raw:
            return {
                "ok": False,
                "mensaje": "No hay impresoras registradas. Ve a Admin → Cargar impresoras base.",
            }

        total_con_datos = sum(1 for p in impresoras_raw if p.get("contador_maquina"))
        return {
            "ok": True,
            "periodo": periodo or "TODOS",
            "resumen_oficinas": resumen_oficinas,
            "detalle_impresoras": detalle_impresoras,
            "totales": {
                "oficinas": len(resumen_oficinas),
                "impresoras_total": len(impresoras_raw),
                "impresoras_con_datos": total_con_datos,
                "paginas_excel_total": sum(r["paginas_excel"] for r in resumen_oficinas),
            },
        }

    def _resumen_general_por_periodo(self, periodo: str | None = None) -> Dict[str, List[Dict]]:
        """Mantiene compatibilidad interna para exportaciones heredadas."""
        where_clause = ""
        params: tuple = ()
        if periodo:
            where_clause = "WHERE DATE_FORMAT(i.fecha, '%Y-%m') = %s"
            params = (periodo,)
        resumen = DB.fetch_all(
            f"""
            SELECT COALESCE(o.id,0) AS oficina_id,
                   COALESCE(o.nombre,'Sin oficina') AS oficina,
                   COALESCE(o.ciudad,'Sin ciudad') AS ciudad,
                   COUNT(DISTINCT i.impresora_id) AS impresoras_activas,
                   COUNT(DISTINCT i.usuario_id) AS usuarios_activos,
                   COUNT(*) AS total_trabajos,
                   SUM(i.paginas) AS total_paginas,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('MONO','B/N','BW','BLACK','BN') THEN i.paginas ELSE 0 END) AS paginas_mono,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('COLOR','COLOUR') THEN i.paginas ELSE 0 END) AS paginas_color,
                   COUNT(DISTINCT DATE_FORMAT(i.fecha,'%Y-%m-%d')) AS dias_activos
            FROM impresiones i LEFT JOIN oficinas o ON o.id=i.oficina_id
            {where_clause}
            GROUP BY o.id,o.nombre,o.ciudad ORDER BY total_paginas DESC
            """, params,
        ) or []
        detalle = DB.fetch_all(
            f"""
            SELECT COALESCE(o.nombre,'Sin oficina') AS oficina,
                   COALESCE(o.ciudad,p.ciudad,'Sin ciudad') AS ciudad,
                   p.nombre AS impresora, p.numero_serie,
                   COUNT(*) AS trabajos,
                   SUM(i.paginas) AS total_paginas,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('MONO','B/N','BW','BLACK','BN') THEN i.paginas ELSE 0 END) AS paginas_mono,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('COLOR','COLOUR') THEN i.paginas ELSE 0 END) AS paginas_color,
                   MAX(i.contador_actual) AS ultimo_contador
            FROM impresiones i JOIN impresoras p ON p.id=i.impresora_id
            LEFT JOIN oficinas o ON o.id=i.oficina_id
            {where_clause}
            GROUP BY o.nombre,o.ciudad,p.nombre,p.numero_serie,p.id
            ORDER BY oficina ASC,total_paginas DESC
            """, params,
        ) or []
        return {"resumen": resumen, "detalle": detalle}


    def generar_reporte_mensual(self, numero_serie: str, periodo_a: str, periodo_b: str) -> Dict:
        """Genera un reporte comparativo mensual para una impresora entre dos periodos.

        Busca la impresora primero en impresoras_red (por numero_serie), luego en
        impresoras + oficinas. Devuelve un dict con ok, comparativo y delta.
        """
        numero_serie = (numero_serie or "").strip()
        periodo_a = (periodo_a or "").strip()
        periodo_b = (periodo_b or "").strip()

        if not numero_serie:
            return {"ok": False, "mensaje": "Debes indicar el numero de serie"}
        if not re.fullmatch(r"\d{4}-\d{2}", periodo_a) or not re.fullmatch(r"\d{4}-\d{2}", periodo_b):
            return {"ok": False, "mensaje": "Los periodos deben tener formato YYYY-MM"}

        # Resolve printer metadata: try impresoras_red first, then impresoras + oficinas
        imp_red = DB.fetch_one(
            "SELECT nombre, oficina FROM impresoras_red WHERE UPPER(TRIM(numero_serie)) = UPPER(TRIM(%s))",
            (numero_serie,),
        )
        if imp_red:
            printer_nombre = imp_red.get("nombre") or numero_serie
            printer_oficina = imp_red.get("oficina") or "N/A"
            printer_ciudad = "N/A"
        else:
            imp_reg = DB.fetch_one(
                """
                SELECT p.nombre, COALESCE(o.nombre, 'N/A') AS oficina,
                       COALESCE(o.ciudad, p.ciudad, 'N/A') AS ciudad
                FROM impresoras p
                LEFT JOIN oficinas o ON o.id = p.oficina_id
                WHERE UPPER(TRIM(p.numero_serie)) = UPPER(TRIM(%s))
                """,
                (numero_serie,),
            )
            if not imp_reg:
                return {
                    "ok": False,
                    "mensaje": f"No se encontro ninguna impresora con serie '{numero_serie}'",
                }
            printer_nombre = imp_reg.get("nombre") or numero_serie
            printer_oficina = imp_reg.get("oficina") or "N/A"
            printer_ciudad = imp_reg.get("ciudad") or "N/A"

        # ── 1. Query print records from Excel data (impresiones table) ──────────
        rows = DB.fetch_all(
            """
            SELECT DATE_FORMAT(i.fecha, '%Y-%m') AS periodo,
                   COALESCE(o.nombre, %s) AS oficina,
                   COALESCE(o.ciudad, p.ciudad, %s) AS ciudad,
                   p.nombre AS impresora,
                   p.numero_serie,
                   SUM(i.paginas) AS volumen,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('MONO','B/N','BW','BLACK','BN') THEN i.paginas ELSE 0 END) AS paginas_mono,
                   SUM(CASE WHEN UPPER(TRIM(i.tipo_impresion)) IN ('COLOR','COLOUR') THEN i.paginas ELSE 0 END) AS paginas_color,
                   MAX(i.contador_actual) AS ultimo_contador,
                   COUNT(DISTINCT DATE_FORMAT(i.fecha, '%Y-%m-%d')) AS dias_activos,
                   COUNT(*) AS total_trabajos
            FROM impresiones i
            JOIN impresoras p ON p.id = i.impresora_id
            LEFT JOIN oficinas o ON o.id = i.oficina_id
            WHERE UPPER(TRIM(p.numero_serie)) = UPPER(TRIM(%s))
              AND DATE_FORMAT(i.fecha, '%Y-%m') IN (%s, %s)
            GROUP BY DATE_FORMAT(i.fecha, '%Y-%m'), o.nombre, o.ciudad, p.nombre, p.numero_serie
            ORDER BY periodo
            """,
            (printer_oficina, printer_ciudad, numero_serie, periodo_a, periodo_b),
        )

        fuente = "excel"

        # ── 2. Fallback: correo (historial_lecturas_email) si Excel no tiene datos ──
        if not rows:
            email_rows = DB.fetch_all(
                """
                SELECT
                    DATE_FORMAT(meter_date, '%Y-%m') AS periodo,
                    MAX(contador_efectivo)            AS ultimo_contador,
                    MAX(contador_efectivo) - MIN(contador_efectivo) AS volumen,
                    COUNT(DISTINCT DATE_FORMAT(meter_date, '%Y-%m-%d')) AS dias_activos,
                    COUNT(*)                          AS total_trabajos,
                    COALESCE(MAX(oficina), %s)        AS oficina
                FROM historial_lecturas_email
                WHERE UPPER(TRIM(serial_number)) = UPPER(TRIM(%s))
                  AND DATE_FORMAT(meter_date, '%Y-%m') IN (%s, %s)
                  AND meter_date IS NOT NULL
                GROUP BY DATE_FORMAT(meter_date, '%Y-%m')
                ORDER BY periodo
                """,
                (printer_oficina, numero_serie, periodo_a, periodo_b),
            )
            if email_rows:
                rows = email_rows
                fuente = "correo"

        # ── 3. Build comparativo list ──────────────────────────────────────────
        comparativo = []
        for r in rows:
            comparativo.append({
                "periodo": r.get("periodo"),
                "oficina": r.get("oficina") or printer_oficina,
                "ciudad": printer_ciudad,
                "impresora": printer_nombre,
                "volumen": int(r.get("volumen") or 0),
                "paginas_mono": int(r.get("paginas_mono") or 0) if fuente == "excel" else None,
                "paginas_color": int(r.get("paginas_color") or 0) if fuente == "excel" else None,
                "ultimo_contador": int(r.get("ultimo_contador") or 0),
                "dias_activos": int(r.get("dias_activos") or 0),
                "total_trabajos": int(r.get("total_trabajos") or 0),
                "fuente": fuente,
            })

        # Build delta comparing periodo_a vs periodo_b
        delta: Dict = {}
        row_map = {r["periodo"]: r for r in comparativo}
        ra = row_map.get(periodo_a)
        rb = row_map.get(periodo_b)
        if ra and rb:
            vol_a = ra["volumen"]
            vol_b = rb["volumen"]
            # variacion positiva = aumentó de periodo_a → periodo_b
            variacion = vol_b - vol_a
            pct = round(variacion * 100 / vol_a, 2) if vol_a else 0.0
            if variacion > 0:
                tendencia = "AUMENTO"
            elif variacion < 0:
                tendencia = "REDUCCION"
            else:
                tendencia = "SIN_VARIACION"
            cnt_a = ra["ultimo_contador"]
            cnt_b = rb["ultimo_contador"]
            delta = {
                "volumen_a": vol_a,
                "volumen_b": vol_b,
                "variacion": variacion,
                "porcentaje_cambio": pct,
                "tendencia": tendencia,
                "contador_a": cnt_a,
                "contador_b": cnt_b,
                "variacion_contador": (cnt_b - cnt_a) if (cnt_a is not None and cnt_b is not None) else None,
            }

        return {
            "ok": True,
            "periodo_a": periodo_a,
            "periodo_b": periodo_b,
            "comparativo": comparativo,
            "delta": delta,
            "fuente": fuente if comparativo else "sin_datos",
        }

    def exportar_reporte_excel(self, serial: str, periodo_a: str, periodo_b: str) -> str:
        report = self.generar_reporte_mensual(serial, periodo_a, periodo_b)
        if not report.get("ok", True):
            raise ValueError(report.get("mensaje", "No fue posible generar el reporte"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.report_service.export_to_excel(report, f"reporte_{serial}_{periodo_a}_{periodo_b}_{ts}.xlsx")

    def exportar_reporte_pdf(self, serial: str, periodo_a: str, periodo_b: str) -> str:
        report = self.generar_reporte_mensual(serial, periodo_a, periodo_b)
        if not report.get("ok", True):
            raise ValueError(report.get("mensaje", "No fue posible generar el reporte"))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.report_service.export_to_pdf(report, f"reporte_{serial}_{periodo_a}_{periodo_b}_{ts}.pdf")

    def exportar_reporte_general_excel(self, periodo: str | None = None) -> str:
        report = self.generar_reporte_general_oficinas(periodo)
        if not report.get("ok", True):
            raise ValueError(report.get("mensaje", "No fue posible generar el reporte general"))
        suffix = (periodo or "general").replace("/", "-")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.report_service.export_general_to_excel(report, f"reporte_general_oficinas_{suffix}_{ts}.xlsx")

    def exportar_reporte_general_pdf(self, periodo: str | None = None) -> str:
        report = self.generar_reporte_general_oficinas(periodo)
        if not report.get("ok", True):
            raise ValueError(report.get("mensaje", "No fue posible generar el reporte general"))
        suffix = (periodo or "general").replace("/", "-")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.report_service.export_general_to_pdf(report, f"reporte_general_oficinas_{suffix}_{ts}.pdf")

    def backup_reporte_general_mensual(self) -> Dict:
        """Exporta el reporte general del periodo actual a una carpeta de backups.

        Si ya existe el archivo para el periodo actual, no lo sobreescribe.
        Devuelve {"ok": True, "archivo": path, "ya_existia": bool}.
        """
        import shutil

        periodo = datetime.now().strftime("%Y-%m")
        backup_dir = Path(APP_CONFIG.upload_dir) / "reportes_backup"
        backup_dir.mkdir(parents=True, exist_ok=True)

        dest_filename = f"reporte_general_{periodo}.xlsx"
        dest_path = backup_dir / dest_filename

        if dest_path.exists():
            return {"ok": True, "archivo": str(dest_path), "ya_existia": True}

        # Generate the report and export to Excel
        output_path = self.exportar_reporte_general_excel(periodo)
        shutil.copy2(output_path, dest_path)
        return {"ok": True, "archivo": str(dest_path), "ya_existia": False}

    def consultar_contadores_ip(self, ip: str) -> Dict:
        from app.utils.snmp_reader import consultar_contadores, validate_ipv4
        try:
            safe_ip = validate_ipv4(ip)
        except ValueError as exc:
            return {"ok": False, "mensaje": str(exc)}
        try:
            contadores = consultar_contadores(safe_ip, community=APP_CONFIG.snmp_community)
            # Ensure queried devices are persisted so they appear in IP inventory/history.
            row = DB.fetch_one("SELECT nombre, oficina FROM impresoras_red WHERE ip_address = %s", (safe_ip,))
            if row:
                nombre = row["nombre"]
                oficina = row["oficina"]
            else:
                nombre = f"Impresora {safe_ip}"
                oficina = ""
                DB.execute(
                    """
                    INSERT INTO impresoras_red (nombre, numero_serie, oficina, ip_address, modelo)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        nombre = VALUES(nombre),
                        oficina = VALUES(oficina),
                        modelo = VALUES(modelo)
                    """,
                    (nombre, None, oficina, safe_ip, "M3655idn"),
                )
            DB.execute(
                """
                INSERT INTO lecturas_snmp (ip_address, nombre, oficina, total_paginas, kyocera_total, mono, color)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    safe_ip, nombre, oficina,
                    contadores.get("contador_efectivo", contadores.get("total_paginas")),
                    contadores.get("kyocera_total"),
                    contadores.get("mono"),
                    contadores.get("color"),
                ),
            )
            return {"ok": True, "ip": safe_ip, "nombre": nombre, "oficina": oficina, "contadores": contadores}
        except Exception as exc:
            return {"ok": False, "mensaje": str(exc)}

    def consultar_contadores_correo(self, serial: str, email_user: str = "", email_password: str = "") -> Dict:
        from app.utils.email_meter_parser import _clean_serial_number
        
        serial_value = (serial or "").strip()
        if not serial_value:
            return {"ok": False, "mensaje": "Número de serie no proporcionado"}

        # Limpiar y normalizar el serial
        serial_clean = _clean_serial_number(serial_value)
        if not serial_clean:
            return {"ok": False, "mensaje": f"Número de serie inválido: {serial_value}"}

        # Si se proporcionan credenciales, buscar en IMAP en tiempo real
        email_user = (email_user or "").strip()
        email_password = (email_password or "").strip()
        
        if email_user and email_password:
            try:
                resultado_imap = self._buscar_correo_imap_por_serial(serial_clean, email_user, email_password)
                if resultado_imap.get("ok"):
                    return resultado_imap
            except Exception as exc:
                pass  # Si falla IMAP, continúa a BD

        # Fallback: buscar en BD usando UPPER para case-insensitive matching
        row = DB.fetch_one(
            """
            SELECT serial_number, model_name, office_hint, contador_efectivo,
                   printed_total, scanned_total, duplex_total, combine_total,
                   toner_black_pct, meter_date, eventos_json, remitente, asunto
            FROM lecturas_email_impresoras
            WHERE UPPER(TRIM(serial_number)) = UPPER(%s)
            ORDER BY meter_date DESC, imported_at DESC
            LIMIT 1
            """,
            (serial_clean,),
        )
        if not row:
            return {"ok": False, "mensaje": f"No hay lecturas de correo para la serie {serial_value}"}

        return {
            "ok": True,
            "serial": row["serial_number"],
            "model_name": row["model_name"],
            "oficina": row["office_hint"],
            "contador_efectivo": row["contador_efectivo"],
            "printed_total": row["printed_total"],
            "scanned_total": row["scanned_total"],
            "duplex_total": row["duplex_total"],
            "combine_total": row["combine_total"],
            "toner_black_pct": row["toner_black_pct"],
            "meter_date": row["meter_date"],
            "eventos_json": row["eventos_json"],
            "remitente": row["remitente"],
            "asunto": row["asunto"],
            "fuente": "Correo (BD)",
        }

    def _buscar_correo_imap_por_serial(self, serial_clean: str, email_user: str, email_password: str) -> Dict:
        """Busca el correo más reciente del serial en IMAP sin guardarlo."""
        try:
            host = APP_CONFIG.email_imap_host.strip()
            mailbox = APP_CONFIG.email_inbox_folder.strip() or "INBOX"
            subject = (APP_CONFIG.email_subject_filter or "").strip()
            
            mail = imaplib.IMAP4_SSL(host, APP_CONFIG.email_imap_port)
            mail.login(email_user, email_password)
            status, _ = mail.select(mailbox)
            if status != "OK":
                return {"ok": False, "mensaje": "No se pudo abrir la carpeta IMAP"}
            
            # Buscar todos los correos (no solo no leídos)
            criteria: List[str] = ["ALL"]
            if subject:
                criteria += ["SUBJECT", f'"{subject}"']
            
            status, data = mail.search(None, *criteria)
            if status != "OK":
                return {"ok": False, "mensaje": "No se pudo buscar en IMAP"}
            
            uids = (data[0] or b"").split()
            if not uids:
                return {"ok": False, "mensaje": "No hay correos en IMAP"}
            
            # Buscar desde el más reciente
            for uid in reversed(uids[-100:]):
                try:
                    status, msg_data = mail.fetch(uid, "(RFC822)")
                    if status != "OK" or not msg_data:
                        continue
                    
                    raw_email = None
                    for part in msg_data:
                        if isinstance(part, tuple) and len(part) > 1:
                            raw_email = part[1]
                            break
                    if not raw_email:
                        continue
                    
                    msg = email.message_from_bytes(raw_email)
                    body = self._extract_plain_text_from_email(msg)
                    parsed = parse_meter_email_text(body)
                    
                    # Verificar si este correo es del serial que buscamos
                    parsed_serial_clean = _clean_serial_number(parsed.get("serial_number"))
                    if parsed_serial_clean and parsed_serial_clean.upper() == serial_clean.upper():
                        # Encontramos el correo más reciente del serial
                        asunto = self._decode_header_value(msg.get("Subject"))
                        remitente = self._decode_header_value(msg.get("From"))
                        
                        try:
                            mail.close()
                            mail.logout()
                        except:
                            pass
                        
                        return {
                            "ok": True,
                            "serial": parsed.get("serial_number"),
                            "model_name": parsed.get("model_name"),
                            "oficina": parsed.get("office_hint"),
                            "contador_efectivo": parsed.get("contador_efectivo"),
                            "printed_total": parsed.get("printed_total"),
                            "scanned_total": parsed.get("scanned_total"),
                            "duplex_total": parsed.get("duplex_total"),
                            "combine_total": parsed.get("combine_total"),
                            "toner_black_pct": parsed.get("toner_black_pct"),
                            "meter_date": parsed.get("meter_date"),
                            "eventos_json": json.dumps(parsed.get("events", []), ensure_ascii=False),
                            "remitente": remitente,
                            "asunto": asunto,
                            "fuente": "Correo (IMAP en vivo)",
                        }
                except Exception:
                    continue
            
            try:
                mail.close()
                mail.logout()
            except:
                pass
            
            return {"ok": False, "mensaje": f"No se encontró correo para el serial {serial_clean} en IMAP"}
            
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error conectando a IMAP: {str(exc)}"}

    # ------------------------------------------------------------------
    # Catálogo base de 32 impresoras (identificadas por serial)
    # ------------------------------------------------------------------
    _IMPRESORAS_BASE = [
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P1171228",  "ip_address": "192.168.40.20",  "oficina": "Armenia",        "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y67378",  "ip_address": "192.168.1.53",   "oficina": "Barranquilla",   "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P1682502",  "ip_address": "192.168.20.30",  "oficina": "Barranquilla",   "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P2805895",  "ip_address": "10.100.10.12",   "oficina": "Bogota",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "TechOps"},
        {"nombre": "ECOSYS M3655idn/A", "numero_serie": "1352800775",  "ip_address": "10.100.10.30",   "oficina": "Bogota",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn/A", "area": None},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y67374",  "ip_address": "10.100.10.15",   "oficina": "Bogota",         "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": None},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P8607199",  "ip_address": "10.100.10.4",    "oficina": "Bogota | Jhulios","canal": "EXTERNO",       "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z68403",  "ip_address": "10.100.10.5",    "oficina": "Bogota",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "CPL"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P1172375",  "ip_address": "10.100.10.25",   "oficina": "Bogota",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Soporte TI / Recepcion"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P1683592",  "ip_address": "10.100.10.9",    "oficina": "Bogota",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "TMK"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y67044",  "ip_address": "192.168.0.14",   "oficina": "Bucaramanga",    "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66966",  "ip_address": "192.168.60.51",  "oficina": "Bucaramanga",    "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y65436",  "ip_address": "192.168.1.51",   "oficina": "Cali",           "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66787",  "ip_address": "192.168.1.50",   "oficina": "Cali",           "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y67381",  "ip_address": "192.168.1.20",   "oficina": "Cartagena",      "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z67817",  "ip_address": "192.168.127.51", "oficina": "Cartagena",      "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y65427",  "ip_address": "192.168.87.15",  "oficina": "Cucuta",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z69074",  "ip_address": "192.168.0.50",   "oficina": "Fusagasuga",     "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66708",  "ip_address": "192.168.123.51", "oficina": "Girardot",       "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z67812",  "ip_address": "192.168.1.100",  "oficina": "Ibague",         "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z67822",  "ip_address": "192.168.100.250","oficina": "Ibague",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y65438",  "ip_address": "192.168.72.51",  "oficina": "Medellin",       "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66908",  "ip_address": "192.168.0.20",   "oficina": "Medellin",       "canal": "EXTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Comercial"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66781",  "ip_address": "192.168.129.51", "oficina": "Monteria",       "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y65507",  "ip_address": "192.168.73.51",  "oficina": "Neiva",          "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z67819",  "ip_address": "192.168.85.51",  "oficina": "Pereira",        "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0354322",  "ip_address": "192.168.134.52", "oficina": "Santa Marta",    "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66956",  "ip_address": "192.168.86.16",  "oficina": "Sincelejo",      "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Z68453",  "ip_address": "192.168.54.51",  "oficina": "Soacha",         "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66711",  "ip_address": "192.168.89.51",  "oficina": "Soledad - Atl",  "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
        {"nombre": "ECOSYS M3655idn",   "numero_serie": "R4P0Y66797",  "ip_address": "192.168.65.51",  "oficina": "Valledupar",     "canal": "INTERNO",        "modelo": "ECOSYS M3655idn",   "area": "Oficina Interna"},
    ]

    def cargar_impresoras_base(self) -> Dict:
        """Reemplaza impresoras_red con las 32 impresoras base del inventario."""
        try:
            DB.execute("DELETE FROM impresoras_red")
        except Exception as exc:
            return {"ok": False, "mensaje": f"No se pudo limpiar la tabla: {exc}"}
        insertadas = 0
        errores = []
        for p in self._IMPRESORAS_BASE:
            try:
                DB.execute(
                    """INSERT INTO impresoras_red (nombre, numero_serie, oficina, ip_address, modelo, canal, area)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (p["nombre"], p["numero_serie"].strip(), p["oficina"],
                     p["ip_address"], p["modelo"], p["canal"], p["area"]),
                )
                insertadas += 1
            except Exception as exc:
                errores.append(f"{p.get('numero_serie')}: {exc}")
        return {
            "ok": True,
            "mensaje": f"Base cargada: {insertadas} impresoras. Errores: {len(errores)}",
            "insertadas": insertadas,
            "errores": errores,
        }

    def registrar_impresora_ip(self, nombre: str, oficina: str, ip: str, numero_serie: str, modelo: str, canal: str = "") -> Dict:
        nombre = self._clip_text(nombre, 255, "Impresora")
        oficina = self._clip_text(oficina, 255)
        serie = self._clip_text(numero_serie, 180)
        if not serie:
            return {"ok": False, "mensaje": "El número de serie es obligatorio"}
        modelo = self._clip_text(modelo, 100) or "ECOSYS M3655idn"
        canal_val = self._clip_text(canal, 60) or None
        ip_val = self._clip_text(ip, 45) or None
        existing = DB.fetch_one(
            "SELECT id FROM impresoras_red WHERE UPPER(TRIM(numero_serie)) = UPPER(%s)", (serie,)
        )
        if existing:
            DB.execute(
                """UPDATE impresoras_red
                   SET nombre=%s, oficina=%s, ip_address=%s, modelo=%s, canal=%s
                   WHERE UPPER(TRIM(numero_serie)) = UPPER(%s)""",
                (nombre, oficina, ip_val, modelo, canal_val, serie),
            )
            return {"ok": True, "mensaje": f"Impresora '{nombre}' ({serie}) actualizada"}
        DB.execute(
            """INSERT INTO impresoras_red (nombre, numero_serie, oficina, ip_address, modelo, canal)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (nombre, serie, oficina, ip_val, modelo, canal_val),
        )
        return {"ok": True, "mensaje": f"Impresora '{nombre}' ({serie}) registrada"}

    def cargar_impresoras_lote(self, impresoras_lista: List[Dict]) -> Dict:
        """Carga múltiples impresoras de golpe (para carga masiva)."""
        from app.utils.snmp_reader import validate_ipv4
        
        insertas = 0
        errores = []
        
        for item in impresoras_lista:
            try:
                nombre = self._clip_text(item.get("nombre") or item.get("modelo", "Impresora"), 255)
                oficina = self._clip_text(item.get("oficina", ""), 255)
                numero_serie = self._clip_text(item.get("numero_serie", ""), 180) or None
                modelo = self._clip_text(item.get("modelo", "M3655idn"), 100) or "M3655idn"
                ip_str = (item.get("ip_address") or "").strip() if item.get("ip_address") else ""
                
                # Validar IP si existe
                if ip_str:
                    try:
                        safe_ip = validate_ipv4(ip_str)
                    except ValueError:
                        errores.append(f"{numero_serie or nombre}: IP inválida {ip_str}")
                        continue
                else:
                    safe_ip = None
                
                # Insertar/actualizar
                DB.execute(
                    """
                    INSERT INTO impresoras_red (nombre, numero_serie, oficina, ip_address, modelo)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        nombre = VALUES(nombre),
                        numero_serie = VALUES(numero_serie),
                        oficina = VALUES(oficina),
                        modelo = VALUES(modelo)
                    """,
                    (nombre, numero_serie, oficina, safe_ip, modelo),
                )
                insertas += 1
            except Exception as exc:
                errores.append(f"{item.get('numero_serie', 'desconocido')}: {str(exc)}")
        
        return {
            "ok": True,
            "mensaje": f"Cargadas {insertas} impresoras. Errores: {len(errores)}",
            "insertadas": insertas,
            "errores": errores,
        }


    def listar_impresoras_ip(self) -> List[Dict]:
        """Retorna todas las impresoras de impresoras_red con su último contador de correo."""
        return DB.fetch_all(
            """
            SELECT
                ir.id,
                ir.nombre,
                ir.numero_serie,
                ir.oficina,
                ir.ip_address,
                ir.modelo,
                ir.canal,
                ir.area,
                COALESCE(o.ciudad, '') AS ciudad,
                (
                    SELECT le.contador_efectivo
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.contador_efectivo IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC
                    LIMIT 1
                ) AS ultima_lectura,
                (
                    SELECT DATE_FORMAT(COALESCE(le.meter_date, le.imported_at), '%Y-%m-%d %H:%i')
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.contador_efectivo IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC
                    LIMIT 1
                ) AS ultima_fecha,
                (
                    SELECT le.toner_black_pct
                    FROM lecturas_email_impresoras le
                    WHERE UPPER(TRIM(le.serial_number)) = UPPER(TRIM(ir.numero_serie))
                      AND le.toner_black_pct IS NOT NULL
                    ORDER BY COALESCE(le.meter_date, le.imported_at) DESC
                    LIMIT 1
                ) AS toner_black_pct
            FROM impresoras_red ir
            LEFT JOIN oficinas o ON o.nombre = ir.oficina
            ORDER BY ir.oficina, ir.nombre
            """
        )

    def eliminar_impresora_ip(self, numero_serie: str) -> Dict:
        serie = (numero_serie or "").strip()
        if not serie:
            return {"ok": False, "mensaje": "Número de serie requerido"}
        DB.execute(
            "DELETE FROM impresoras_red WHERE UPPER(TRIM(numero_serie)) = UPPER(%s)", (serie,)
        )
        return {"ok": True, "mensaje": f"Impresora {serie} eliminada del listado"}

    def consultar_todos_contadores_ip(self) -> Dict:
        # Primero, traer todas las impresoras de impresoras_red
        printers_red = DB.fetch_all("SELECT ip_address, nombre, oficina, numero_serie FROM impresoras_red")
        resultados = []
        errores = []
        
        for p in printers_red:
            r = self.consultar_contadores_ip(p["ip_address"])
            if r.get("ok"):
                resultados.append({
                    "ip": p["ip_address"],
                    "nombre": p["nombre"],
                    "oficina": p["oficina"],
                    **r["contadores"],
                })
            else:
                errores.append({"ip": p["ip_address"], "nombre": p["nombre"], "error": r.get("mensaje")})
        
        # Luego, agregar impresoras del inventario sin IP registrada (Soacha, Barranquilla, etc)
        printers_excel = DB.fetch_all(
            """
            SELECT p.numero_serie, p.nombre, COALESCE(o.nombre, p.ciudad) AS oficina
            FROM impresoras p
            LEFT JOIN oficinas o ON o.id = p.oficina_id
            WHERE p.numero_serie IS NOT NULL 
              AND p.numero_serie NOT IN (SELECT numero_serie FROM impresoras_red WHERE numero_serie IS NOT NULL)
            """
        )
        
        for p in printers_excel:
            if p.get("numero_serie"):
                # Intentar obtener datos de correo
                r = self.consultar_contadores_correo(p["numero_serie"])
                if r.get("ok"):
                    resultados.append({
                        "nombre": p["nombre"],
                        "oficina": p["oficina"],
                        "fuente": "Correo",
                        "contador_efectivo": r.get("contador_efectivo"),
                        "meter_date": r.get("meter_date"),
                    })
                else:
                    # Si no hay datos en correo, no agregar a errores, solo registrar con "-"
                    resultados.append({
                        "nombre": p["nombre"],
                        "oficina": p["oficina"],
                        "contador_efectivo": None,
                    })
        
        return {"ok": True, "resultados": resultados, "errores": errores}

    def historial_lecturas_ip(self, numero_serie: str) -> List[Dict]:
        """Historial de lecturas de correo para una impresora por serial."""
        serie = (numero_serie or "").strip()
        if not serie:
            return []
        return DB.fetch_all(
            """
            SELECT
                DATE_FORMAT(COALESCE(meter_date, imported_at), '%Y-%m-%d %H:%i') AS fecha,
                contador_efectivo,
                printed_total,
                scanned_total,
                toner_black_pct,
                asunto
            FROM lecturas_email_impresoras
            WHERE UPPER(TRIM(serial_number)) = UPPER(%s)
              AND contador_efectivo IS NOT NULL
            ORDER BY COALESCE(meter_date, imported_at) DESC
            LIMIT 30
            """,
            (serie,),
        )

    # ------------------------------------------------------------------
    # Ingestion de correos de contadores (Kyocera)
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_header_value(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value))).strip()
        except Exception:
            return value.strip()

    @staticmethod
    def _extract_plain_text_from_email(msg: email.message.Message) -> str:
        def decode_payload(part: email.message.Message) -> str:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except Exception:
                return payload.decode("utf-8", errors="replace")

        def html_to_text(raw_html: str) -> str:
            text = re.sub(r"<\s*br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
            text = re.sub(r"</\s*(p|div|li|tr|h\d)\s*>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
            text = text.replace("\r\n", "\n")
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        body_text_parts: List[str] = []
        attachment_parts: List[str] = []

        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue

                content_type = (part.get_content_type() or "").lower()
                disposition = str(part.get("Content-Disposition") or "").lower()
                filename = (part.get_filename() or "").lower()
                decoded = decode_payload(part)

                if "attachment" in disposition:
                    is_counter_attachment = (
                        content_type in {"text/plain", "text/html"}
                        or filename.endswith((".txt", ".htm", ".html"))
                        or "counter" in filename
                    )
                    if is_counter_attachment:
                        attachment_parts.append(html_to_text(decoded) if content_type == "text/html" else decoded)
                    continue

                if content_type == "text/plain":
                    body_text_parts.append(decoded)
                elif content_type == "text/html":
                    body_text_parts.append(html_to_text(decoded))

            merged = "\n\n".join([p for p in (body_text_parts + attachment_parts) if p and p.strip()])
            return merged.strip()

        content_type = (msg.get_content_type() or "").lower()
        decoded = decode_payload(msg)
        if content_type == "text/html":
            return html_to_text(decoded)
        return decoded

    def importar_lecturas_desde_correo(
        self,
        email_user: str = "",
        email_password: str = "",
        imap_host: str = "",
        folder: str = "",
        sender_filter: str = "",
        subject_filter: str = "",
        only_unseen: bool = False,
        max_messages: int = 100,
    ) -> Dict:
        # Resolver credenciales y parámetros
        user = (email_user or "").strip()
        password = (email_password or "").strip()
        host = (imap_host or APP_CONFIG.email_imap_host or "").strip()
        mailbox = (folder or APP_CONFIG.email_inbox_folder or "datecsa").strip()
        s_filter = (sender_filter or APP_CONFIG.email_sender_filter or "").strip()
        subj_filter = (subject_filter or APP_CONFIG.email_subject_filter or "").strip()
        max_msg = max(1, min(int(max_messages or 100), 500))

        if not user or not password:
            return {"ok": False, "mensaje": "Credenciales de correo requeridas (usuario y contraseña)"}
        if not host:
            return {"ok": False, "mensaje": "Host IMAP no configurado"}

        mail = None
        try:
            mail = imaplib.IMAP4_SSL(host, APP_CONFIG.email_imap_port)
        except Exception as exc:
            return {"ok": False, "mensaje": f"No se pudo conectar al servidor IMAP ({host}): {exc}"}

        try:
            mail.login(user, password)
        except Exception as exc:
            try:
                mail.logout()
            except Exception:
                pass
            return {"ok": False, "mensaje": f"Credenciales incorrectas o acceso denegado: {exc}"}

        # Seleccionar carpeta — intentar con el nombre dado y variantes comunes
        # Para Gmail los nombres van entre comillas: "[Gmail]/Enviados"
        status = "NO"
        folder_variants = [
            mailbox,
            f'"{mailbox}"',
            mailbox.upper(),
            mailbox.lower(),
            f"[Gmail]/{mailbox}",
            f'"[Gmail]/{mailbox}"',
            f"[Gmail]/Sent Mail",
            f'"[Gmail]/Sent Mail"',
        ]
        for folder_try in folder_variants:
            try:
                status, _ = mail.select(folder_try)
                if status == "OK":
                    mailbox = folder_try
                    break
            except Exception:
                continue

        if status != "OK":
            # Listar carpetas disponibles para dar un mensaje útil
            try:
                import re as _re
                _, folders_raw = mail.list()
                available = []
                for f in (folders_raw or []):
                    if isinstance(f, bytes):
                        decoded = f.decode("utf-8", errors="replace")
                        # El nombre de la carpeta es el último token: quoted o unquoted
                        m = _re.search(r'"([^"]+)"\s*$', decoded)
                        if m:
                            available.append(m.group(1).strip())
                        else:
                            m2 = _re.search(r'\s(\S+)\s*$', decoded)
                            if m2:
                                available.append(m2.group(1).strip())
                available_str = ", ".join(available[:20]) if available else "no se pudieron listar"
            except Exception:
                available_str = "no se pudieron listar"
            try:
                mail.logout()
            except Exception:
                pass
            return {
                "ok": False,
                "mensaje": (
                    f"Carpeta '{folder}' no encontrada. "
                    f"Carpetas disponibles: {available_str}"
                ),
            }

        # Construir criterio de búsqueda
        criteria: List[str] = ["UNSEEN"] if only_unseen else ["ALL"]
        if subj_filter:
            criteria += ["SUBJECT", f'"{subj_filter}"']
        if s_filter:
            criteria += ["FROM", f'"{s_filter}"']

        try:
            status, data = mail.search(None, *criteria)
        except Exception as exc:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass
            return {"ok": False, "mensaje": f"Error buscando correos: {exc}"}

        uids = (data[0] or b"").split() if status == "OK" else []
        if not uids:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass
            criterio_desc = "no leídos" if only_unseen else "todos"
            return {
                "ok": True,
                "insertados": 0,
                "omitidos": 0,
                "errores": [],
                "muestras": [],
                "mensaje": f"No hay correos ({criterio_desc}) en la carpeta '{folder or mailbox}'",
            }

        # Procesar desde el más reciente, limitado a max_msg
        uids_to_process = list(reversed(uids))[:max_msg]

        inserted = 0
        skipped = 0
        errors: List[str] = []
        muestras: List[Dict[str, Any]] = []
        seriales_procesados: Set[str] = set()

        for uid in uids_to_process:
            try:
                status, msg_data = mail.fetch(uid, "(RFC822)")
                if status != "OK" or not msg_data:
                    errors.append(f"UID {uid}: no se pudo obtener el mensaje")
                    continue

                raw_email = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) > 1:
                        raw_email = part[1]
                        break
                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                body = self._extract_plain_text_from_email(msg)
                if not body or not body.strip():
                    continue

                parsed = parse_meter_email_text(body)

                serial_raw = parsed.get("serial_number") or ""
                meter_date_raw = str(parsed.get("meter_date") or "")
                printed_raw = str(parsed.get("printed_total") or "")
                message_id_val = self._decode_header_value(msg.get("Message-ID")) or str(uid)
                asunto = self._decode_header_value(msg.get("Subject")) or ""
                remitente = self._decode_header_value(msg.get("From")) or ""
                fecha_correo_hdr = self._decode_header_value(msg.get("Date")) or ""

                # Fecha de correo como datetime string
                try:
                    import email.utils as email_utils
                    parsed_date = email_utils.parsedate_to_datetime(fecha_correo_hdr)
                    fecha_correo = parsed_date.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    fecha_correo = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Hash de deduplicación
                source_base = f"{message_id_val}|{serial_raw}|{meter_date_raw}|{printed_raw}"
                source_hash = hashlib.sha256(source_base.encode("utf-8", errors="ignore")).hexdigest()

                existing = DB.fetch_one(
                    "SELECT id FROM lecturas_email_impresoras WHERE source_hash = %s",
                    (source_hash,),
                )
                if existing:
                    skipped += 1
                    continue

                DB.execute(
                    """
                    INSERT INTO lecturas_email_impresoras (
                        message_uid, message_id, source_hash,
                        remitente, asunto, fecha_correo,
                        serial_number, model_name, office_hint,
                        meter_date, printed_total, scanned_total,
                        duplex_1sided, duplex_2sided, duplex_total,
                        combine_total, toner_black_pct, contador_efectivo,
                        eventos_json, raw_body
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uid),
                        message_id_val,
                        source_hash,
                        remitente,
                        asunto,
                        fecha_correo,
                        parsed.get("serial_number"),
                        parsed.get("model_name"),
                        parsed.get("office_hint"),
                        parsed.get("meter_date"),
                        parsed.get("printed_total"),
                        parsed.get("scanned_total"),
                        parsed.get("duplex_1sided"),
                        parsed.get("duplex_2sided"),
                        parsed.get("duplex_total"),
                        parsed.get("combine_total"),
                        parsed.get("toner_black_pct"),
                        parsed.get("contador_efectivo"),
                        json.dumps(parsed.get("events", []), ensure_ascii=False),
                        body,
                    ),
                )
                inserted += 1

                serial = parsed.get("serial_number")
                if serial:
                    DB.execute(
                        """
                        INSERT INTO historial_lecturas_email (
                            serial_number, model_name, oficina,
                            contador_efectivo, printed_total, scanned_total,
                            toner_black_pct, meter_date, asunto, remitente
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            serial,
                            parsed.get("model_name"),
                            parsed.get("office_hint"),
                            parsed.get("contador_efectivo"),
                            parsed.get("printed_total"),
                            parsed.get("scanned_total"),
                            parsed.get("toner_black_pct"),
                            parsed.get("meter_date"),
                            asunto,
                            remitente,
                        ),
                    )
                    if serial not in seriales_procesados:
                        seriales_procesados.add(serial)

                    # Sincronizar catálogo de impresoras
                    serial_clip = self._clip_text(serial, 180, "")
                    if serial_clip:
                        oficina_nombre = self._clip_text(parsed.get("office_hint"), 255, "Correo")
                        modelo = self._clip_text(parsed.get("model_name"), 255, "M3655idn")
                        printer_name = self._clip_text(parsed.get("model_name"), 255, "Impresora correo")
                        office_id = self._get_or_create_oficina(oficina_nombre, None)
                        self._get_or_create_impresora(printer_name, serial_clip, office_id, None, modelo)

                if len(muestras) < 8:
                    muestras.append(
                        {
                            "serial": parsed.get("serial_number"),
                            "modelo": parsed.get("model_name"),
                            "oficina": parsed.get("office_hint"),
                            "contador": parsed.get("contador_efectivo"),
                            "meter_date": parsed.get("meter_date"),
                            "toner_black_pct": parsed.get("toner_black_pct"),
                        }
                    )

            except Exception as exc:
                errors.append(f"UID {uid}: {str(exc)}")

        try:
            mail.close()
            mail.logout()
        except Exception:
            pass

        # Limpiar historial: mantener solo los últimos 40 por serial
        for serial in seriales_procesados:
            DB.execute(
                """
                DELETE FROM historial_lecturas_email
                WHERE serial_number = %s
                AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM historial_lecturas_email
                        WHERE serial_number = %s
                        ORDER BY leido_en DESC
                        LIMIT 40
                    ) AS keep
                )
                """,
                (serial, serial),
            )

        # Auto-sincronizar mantenimientos con los nuevos datos
        if inserted > 0:
            try:
                self.sincronizar_mantenimientos(regenerar=True)
            except Exception:
                pass

        total = len(uids_to_process)
        return {
            "ok": True,
            "insertados": inserted,
            "omitidos": skipped,
            "errores": errors,
            "muestras": muestras,
            "mensaje": (
                f"Importación desde '{folder or mailbox}' completada. "
                f"Revisados: {total}, nuevos: {inserted}, duplicados: {skipped}"
                + (f", errores: {len(errors)}" if errors else "")
            ),
        }

    def setup_nueva_bd(self, host: str, port: int, user: str, password: str, db_name: str) -> Dict:
        """Crea una nueva base de datos con la misma estructura del proyecto."""
        import mysql.connector as mc
        from app.database.schema import SCHEMA_SQL, EXTRA_SCHEMA_SQL

        host = (host or "127.0.0.1").strip()
        port = int(port or 3306)
        user = (user or "root").strip()
        password = (password or "").strip()
        db_name = (db_name or "print_analytics_nueva").strip()

        # Validar nombre de BD (solo alfanuméricos y guiones bajos)
        import re as _re
        if not _re.fullmatch(r"[a-zA-Z0-9_]+", db_name):
            return {"ok": False, "mensaje": "Nombre de BD inválido. Use solo letras, números y guiones bajos."}

        # Paso 1: verificar conexión
        try:
            conn = mc.connect(host=host, port=port, user=user, password=password, connection_timeout=5)
        except mc.Error as exc:
            err = str(exc)
            if "1045" in err or "Access denied" in err:
                return {"ok": False, "mensaje": f"Credenciales incorrectas: {exc}"}
            if "2003" in err or "Can't connect" in err:
                return {
                    "ok": False,
                    "mensaje": (
                        f"No se puede conectar a MySQL en {host}:{port}.\n"
                        "Verifique que MySQL esté instalado y el servicio esté activo.\n"
                        "Versión requerida: MySQL 8.0 o superior."
                    ),
                }
            return {"ok": False, "mensaje": f"Error de conexión: {exc}"}

        cursor = conn.cursor()
        tablas_creadas = []
        errores = []

        try:
            # Crear la base de datos si no existe
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.execute(f"USE `{db_name}`")
            conn.commit()

            # Ejecutar todas las tablas del schema
            for stmt in SCHEMA_SQL + EXTRA_SCHEMA_SQL:
                stmt_clean = stmt.strip()
                if not stmt_clean:
                    continue
                try:
                    cursor.execute(stmt_clean)
                    conn.commit()
                    # Extraer nombre de tabla del CREATE TABLE
                    m = _re.search(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", stmt_clean, _re.IGNORECASE)
                    if m:
                        tablas_creadas.append(m.group(1))
                except mc.Error as exc:
                    errores.append(str(exc))

        except mc.Error as exc:
            cursor.close()
            conn.close()
            return {"ok": False, "mensaje": f"Error creando base de datos: {exc}"}
        finally:
            cursor.close()
            conn.close()

        if errores:
            return {
                "ok": False,
                "mensaje": f"BD '{db_name}' creada pero con {len(errores)} error(es): {'; '.join(errores[:3])}",
                "tablas": tablas_creadas,
            }

        return {
            "ok": True,
            "mensaje": f"¡Creación de tablas exitosa! Base de datos '{db_name}' lista con {len(tablas_creadas)} tablas.",
            "tablas": tablas_creadas,
            "db_name": db_name,
        }

    def listar_lecturas_email(self, limit: int = 100) -> List[Dict]:
        safe_limit = max(1, min(int(limit or 100), 500))
        return DB.fetch_all(
            f"""
            SELECT
                DATE_FORMAT(imported_at, '%Y-%m-%d %H:%i:%s') AS importado_en,
                DATE_FORMAT(meter_date, '%Y-%m-%d %H:%i:%s') AS meter_date,
                serial_number,
                model_name,
                office_hint,
                contador_efectivo,
                printed_total,
                scanned_total,
                duplex_total,
                toner_black_pct,
                asunto,
                remitente
            FROM lecturas_email_impresoras
            ORDER BY imported_at DESC
            LIMIT {safe_limit}
            """
        )

    def obtener_historico_impresora(self, serial: str) -> Dict:
        """Retorna historial de contadores y toner para una impresora desde historial_lecturas_email."""
        if not serial:
            return {"ok": False, "mensaje": "Serial requerido"}
        rows = DB.fetch_all(
            """
            SELECT
                DATE_FORMAT(meter_date, '%Y-%m-%d') AS fecha,
                DATE_FORMAT(meter_date, '%Y-%m')    AS periodo,
                contador_efectivo,
                printed_total,
                toner_black_pct,
                model_name,
                oficina
            FROM historial_lecturas_email
            WHERE serial_number = %s
              AND meter_date IS NOT NULL
            ORDER BY meter_date ASC
            LIMIT 60
            """,
            (serial,),
        )
        # Basic printer info from impresoras_red
        info = DB.fetch_one(
            "SELECT nombre, oficina, canal, area FROM impresoras_red WHERE numero_serie = %s LIMIT 1",
            (serial,),
        )
        return {
            "ok": True,
            "serial": serial,
            "info": info or {},
            "historial": rows,
        }

    def procesar_correos_locales(
        self,
        carpeta_entrada: str = "",
        carpeta_archivo: str = "",
        patron: str = "*.txt",
    ) -> Dict:
        """Procesa archivos de correo desde una carpeta local sin IMAP.

        Usa EmailFileProcessorV2 para mejor manejo de errores y validaciones.
        """
        from app.utils.email_file_processor_v2 import EmailFileProcessorV2

        entrada = Path(carpeta_entrada or (APP_CONFIG.upload_dir / "email_intake")).resolve()
        archivo = Path(carpeta_archivo or (APP_CONFIG.upload_dir / "email_processed")).resolve() if carpeta_archivo else None

        try:
            result = EmailFileProcessorV2.process_intake_folder(
                intake_folder=entrada,
                archive_folder=archivo,
                pattern=patron,
            )
            return result
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error procesando carpeta: {exc}"}

    def procesar_correo_archivo(self, archivo_ruta: str) -> Dict:
        """Procesa un archivo de correo individual."""
        from app.utils.email_file_processor_v2 import EmailFileProcessorV2

        ruta = Path(archivo_ruta or "").resolve()
        if not ruta.exists():
            return {"ok": False, "mensaje": f"Archivo no encontrado: {ruta}"}

        try:
            return EmailFileProcessorV2.process_email_file(ruta)
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error procesando archivo: {exc}"}

    def diagnosticar_archivos_correos(
        self,
        carpeta: str = "",
        patron: str = "*.txt,*.htm,*.html",
    ) -> Dict:
        """Diagnostica archivos de correo mostrando qué se extrae de cada uno sin guardar."""
        entrada = Path(carpeta or (APP_CONFIG.upload_dir / "email_intake")).resolve()
        if not entrada.exists():
            return {"ok": False, "mensaje": f"Carpeta no existe: {entrada}"}

        patterns = [p.strip() for p in (patron or "*.txt,*.htm,*.html").split(",") if p.strip()]
        
        files_set = []
        for pat in patterns:
            for file_path in entrada.glob(pat):
                files_set.append(file_path)

        files = sorted(dict.fromkeys(files_set), key=lambda p: p.name)
        if not files:
            return {
                "ok": True,
                "total": 0,
                "archivos": [],
                "mensaje": "No hay archivos para diagnosticar",
            }

        resultados = []
        for file_path in files:
            try:
                body = file_path.read_text(encoding="utf-8", errors="replace")
                parsed = parse_meter_email_text(body)
                
                resultados.append({
                    "archivo": file_path.name,
                    "serial_number": parsed.get("serial_number"),
                    "model_name": parsed.get("model_name"),
                    "office_hint": parsed.get("office_hint"),
                    "meter_date": parsed.get("meter_date"),
                    "contador_efectivo": parsed.get("contador_efectivo"),
                    "printed_total": parsed.get("printed_total"),
                    "toner_black_pct": parsed.get("toner_black_pct"),
                })
            except Exception as exc:
                resultados.append({
                    "archivo": file_path.name,
                    "error": str(exc),
                })

        return {
            "ok": True,
            "total": len(files),
            "archivos": resultados,
            "mensaje": f"Se encontraron {len(files)} archivos",
        }

    def listar_seriales_en_bd(self, limit: int = 100) -> Dict:
        """Lista los seriales que existen en la base de datos de lecturas de correo."""
        try:
            rows = DB.fetch_all(
                """
                SELECT DISTINCT serial_number, COUNT(*) as cantidad, 
                       MAX(meter_date) as ultima_lectura
                FROM lecturas_email_impresoras
                WHERE serial_number IS NOT NULL AND serial_number != ''
                GROUP BY serial_number
                ORDER BY ultima_lectura DESC
                LIMIT %s
                """,
                (limit,),
            )
            return {
                "ok": True,
                "seriales": rows or [],
                "total": len(rows or []),
                "mensaje": f"Se encontraron {len(rows or [])} seriales en BD",
            }
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error listando seriales: {exc}"}

    # ══════════════════════════════════════════════════════════════════════════
    # BACKUPS MENSUALES
    # ══════════════════════════════════════════════════════════════════════════

    def _backup_dir(self) -> Path:
        d = BASE_DIR / "backups"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def backup_datos_mes(self, periodo: str = None) -> Dict:
        """Guarda en backups/{periodo}/datos.json los datos clave del mes.

        Si el período solicitado no tiene comparativos, usa el último período
        disponible con datos para no crear backups vacíos.
        """
        if not periodo:
            periodo = datetime.now().strftime("%Y-%m")

        # Si no hay comparativos para el período pedido, buscar el último disponible
        check = DB.fetch_one(
            "SELECT COUNT(*) AS cnt FROM reportes_comparativos WHERE periodo = %s",
            (periodo,),
        )
        if not check or (check.get("cnt") or 0) == 0:
            ultimo = DB.fetch_one(
                "SELECT MAX(periodo) AS p FROM reportes_comparativos"
            )
            if ultimo and ultimo.get("p"):
                periodo = ultimo["p"]

        backup_dir = self._backup_dir() / periodo
        backup_dir.mkdir(parents=True, exist_ok=True)
        datos_file = backup_dir / "datos.json"

        # 1. Comparativos del período
        comparativos = DB.fetch_all(
            "SELECT * FROM reportes_comparativos WHERE periodo = %s ORDER BY numero_serie",
            (periodo,),
        )

        # 2. Historial de lecturas del período
        historial = DB.fetch_all(
            """SELECT serial_number, model_name, oficina, contador_efectivo,
                      printed_total, toner_black_pct, meter_date, leido_en
               FROM historial_lecturas_email
               WHERE DATE_FORMAT(leido_en, '%%Y-%%m') = %s
                  OR DATE_FORMAT(meter_date, '%%Y-%%m') = %s
               ORDER BY serial_number, meter_date""",
            (periodo, periodo),
        )

        # 3. Totales de impresiones del mes
        impresiones = DB.fetch_all(
            """SELECT DATE_FORMAT(fecha, '%%Y-%%m') as mes,
                      SUM(paginas) as total_paginas,
                      COUNT(DISTINCT impresora_id) as impresoras
               FROM impresiones
               WHERE DATE_FORMAT(fecha, '%%Y-%%m') = %s
               GROUP BY mes""",
            (periodo,),
        )

        datos = {
            "periodo": periodo,
            "generado_en": datetime.now().isoformat(),
            "version_app": "1.1.0",
            "comparativos": [dict(r) for r in comparativos],
            "historial_lecturas": [dict(r) for r in historial],
            "impresiones": [dict(r) for r in impresiones],
        }

        datos_file.write_text(
            json.dumps(datos, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "periodo": periodo,
            "archivo": str(datos_file),
            "comparativos": len(comparativos),
            "historial": len(historial),
        }

    def listar_backups(self) -> Dict:
        """Lista todos los backups disponibles con resumen de cada uno."""
        backup_base = self._backup_dir()
        backups = []
        for folder in sorted(backup_base.iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            datos_file = folder / "datos.json"
            if not datos_file.exists():
                continue
            try:
                info = json.loads(datos_file.read_text(encoding="utf-8"))
                backups.append({
                    "periodo": info.get("periodo", folder.name),
                    "generado_en": info.get("generado_en", ""),
                    "comparativos": len(info.get("comparativos", [])),
                    "historial": len(info.get("historial_lecturas", [])),
                    "archivo": str(datos_file),
                })
            except Exception:
                backups.append({"periodo": folder.name, "error": True})
        return {"ok": True, "backups": backups}

    def _red_backup_dir(self) -> Path | None:
        """Carpeta de backups en la red compartida (si está configurada y accesible)."""
        import os as _os
        folder = (_os.environ.get("UPDATE_FOLDER") or APP_CONFIG.update_folder or "").strip()
        if not folder:
            return None
        red = Path(folder) / "backups"
        try:
            red.mkdir(parents=True, exist_ok=True)
            return red
        except Exception:
            return None

    def sincronizar_backup_a_red(self, periodo: str = None) -> Dict:
        """Copia el backup local del período a la carpeta compartida de red."""
        import shutil
        if not periodo:
            # Buscar el período con datos más reciente
            ultimo = DB.fetch_one("SELECT MAX(periodo) AS p FROM reportes_comparativos")
            periodo = (ultimo or {}).get("p") or datetime.now().strftime("%Y-%m")

        local_file = self._backup_dir() / periodo / "datos.json"
        if not local_file.exists():
            # Crear backup primero
            self.backup_datos_mes(periodo)
        if not local_file.exists():
            return {"ok": False, "mensaje": f"No se pudo generar el backup local para {periodo}"}

        red_dir = self._red_backup_dir()
        if not red_dir:
            return {"ok": False, "mensaje": "Carpeta de red no configurada o inaccesible"}

        dest_dir = red_dir / periodo
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "datos.json"
        shutil.copy2(local_file, dest_file)
        return {"ok": True, "mensaje": f"Backup {periodo} sincronizado a la red", "ruta": str(dest_file)}

    def listar_backups_red(self) -> Dict:
        """Lista backups disponibles en la carpeta de red."""
        red_dir = self._red_backup_dir()
        if not red_dir or not red_dir.exists():
            return {"ok": False, "mensaje": "Carpeta de red no configurada o inaccesible", "backups": []}
        backups = []
        for folder in sorted(red_dir.iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            datos_file = folder / "datos.json"
            if not datos_file.exists():
                continue
            try:
                info = json.loads(datos_file.read_text(encoding="utf-8"))
                backups.append({
                    "periodo": info.get("periodo", folder.name),
                    "generado_en": info.get("generado_en", ""),
                    "comparativos": len(info.get("comparativos", [])),
                    "historial": len(info.get("historial_lecturas", [])),
                    "fuente": "red",
                })
            except Exception:
                pass
        return {"ok": True, "backups": backups}

    def cargar_datos_backup(self, periodo: str) -> Dict:
        """Carga los datos de un backup para mostrar en el historial."""
        datos_file = self._backup_dir() / periodo / "datos.json"
        if not datos_file.exists():
            return {"ok": False, "mensaje": f"No hay backup para {periodo}"}
        try:
            datos = json.loads(datos_file.read_text(encoding="utf-8"))
            return {"ok": True, **datos}
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error leyendo backup: {exc}"}

    def obtener_estadisticas_mensuales(self) -> Dict:
        """Retorna datos agrupados por mes para gráficas históricas."""
        # Páginas totales por mes desde historial de correos
        # Nota: sin params → usar % simple (mysql-connector no escapa %% sin params)
        por_mes = DB.fetch_all(
            """SELECT DATE_FORMAT(meter_date, '%Y-%m') as mes,
                      SUM(printed_total) as total_paginas,
                      COUNT(DISTINCT serial_number) as impresoras,
                      AVG(toner_black_pct) as toner_promedio
               FROM historial_lecturas_email
               WHERE meter_date IS NOT NULL
                 AND printed_total IS NOT NULL
               GROUP BY mes
               ORDER BY mes DESC
               LIMIT 24""",
        )

        # Comparativos por mes (% error promedio)
        por_mes_cmp = DB.fetch_all(
            """SELECT periodo as mes,
                      COUNT(*) as total,
                      AVG(ABS(porcentaje_error)) as error_promedio,
                      SUM(CASE WHEN diferencia < 0 THEN 1 ELSE 0 END) as a_favor,
                      SUM(CASE WHEN diferencia > 0 THEN 1 ELSE 0 END) as en_contra
               FROM reportes_comparativos
               GROUP BY periodo
               ORDER BY periodo DESC
               LIMIT 24""",
        )

        # Páginas por mes desde Excel (impresiones)
        por_mes_excel = DB.fetch_all(
            """SELECT DATE_FORMAT(fecha, '%Y-%m') as mes,
                      SUM(paginas) as total_paginas,
                      COUNT(DISTINCT impresora_id) as impresoras
               FROM impresiones
               WHERE fecha IS NOT NULL
               GROUP BY mes
               ORDER BY mes DESC
               LIMIT 24""",
        )

        return {
            "ok": True,
            "por_mes_correo": [dict(r) for r in reversed(por_mes)],
            "por_mes_comparativo": [dict(r) for r in reversed(por_mes_cmp)],
            "por_mes_excel": [dict(r) for r in reversed(por_mes_excel)],
        }

    # ══════════════════════════════════════════════════════════════════════════
    # AUTO-ACTUALIZACIÓN
    # ══════════════════════════════════════════════════════════════════════════

    def check_actualizacion(self) -> Dict:
        """Verifica si hay una nueva versión en la carpeta compartida."""
        import os as _os
        from app.config import APP_VERSION
        # Lee siempre del entorno (APP_CONFIG es frozen y no se actualiza al guardar)
        update_folder = (_os.environ.get("UPDATE_FOLDER") or APP_CONFIG.update_folder or "").strip()
        if not update_folder:
            return {"ok": False, "hay_actualizacion": False,
                    "mensaje": "Carpeta de actualizaciones no configurada"}

        version_file = Path(update_folder) / "version.json"
        if not version_file.exists():
            return {"ok": False, "hay_actualizacion": False,
                    "mensaje": f"No se encontró version.json en {update_folder}"}

        try:
            info = json.loads(version_file.read_text(encoding="utf-8"))
            remote_ver = tuple(int(x) for x in info.get("version", "0.0.0").split("."))
            current_ver = tuple(int(x) for x in APP_VERSION.split("."))
            hay_update = remote_ver > current_ver
            return {
                "ok": True,
                "hay_actualizacion": hay_update,
                "version_actual": APP_VERSION,
                "version_nueva": info.get("version", ""),
                "fecha": info.get("fecha", ""),
                "notas": info.get("notas", []),
                "carpeta": update_folder,
            }
        except Exception as exc:
            return {"ok": False, "hay_actualizacion": False,
                    "mensaje": f"Error leyendo version.json: {exc}"}

    def configurar_update_folder(self, carpeta: str) -> Dict:
        """Guarda la ruta de la carpeta de actualizaciones en el .env."""
        import sys as _sys, os as _os
        if getattr(_sys, "frozen", False):
            env_path = Path(_sys.executable).parent / ".env"
        else:
            env_path = BASE_DIR / ".env"

        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        found = False
        new_lines = []
        for line in lines:
            if line.startswith("UPDATE_FOLDER="):
                new_lines.append(f"UPDATE_FOLDER={carpeta}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"UPDATE_FOLDER={carpeta}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        _os.environ["UPDATE_FOLDER"] = carpeta

        # Si la carpeta existe y no tiene version.json, crear uno con la versión actual
        from app.config import APP_VERSION
        p = Path(carpeta)
        extras = []
        if p.exists():
            vf = p / "version.json"
            if not vf.exists():
                vf.write_text(
                    json.dumps({
                        "version": APP_VERSION,
                        "fecha": datetime.now().strftime("%Y-%m-%d"),
                        "notas": ["Versión inicial configurada desde el aplicativo"]
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                extras.append("version.json creado")
            # Crear subcarpeta backups si no existe
            (p / "backups").mkdir(exist_ok=True)

        msg = f"Carpeta configurada: {carpeta}"
        if extras:
            msg += f" ({', '.join(extras)})"
        return {"ok": True, "mensaje": msg}

    def instalar_actualizacion(self) -> Dict:
        """Copia el exe nuevo desde la carpeta compartida a C:\\AVISTA_Updates\\ y lanza el instalador."""
        import os, shutil, subprocess, sys as _sys
        from app.config import APP_VERSION

        # Lee siempre del entorno (APP_CONFIG es frozen y no se actualiza al guardar)
        update_folder = (os.environ.get("UPDATE_FOLDER") or APP_CONFIG.update_folder or "").strip()
        if not update_folder:
            return {"ok": False, "mensaje": "Carpeta de actualizaciones no configurada"}

        src = Path(update_folder)
        exe_src = src / "AVISTA_CPAnalisis.exe"
        if not exe_src.exists():
            return {"ok": False, "mensaje": f"No se encontró AVISTA_CPAnalisis.exe en {update_folder}"}

        staging = Path(r"C:\AVISTA_Updates")
        staging.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(exe_src, staging / "AVISTA_CPAnalisis.exe")
            internal_src = src / "_internal"
            if internal_src.exists():
                internal_dst = staging / "_internal"
                if internal_dst.exists():
                    shutil.rmtree(internal_dst)
                shutil.copytree(internal_src, internal_dst)
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error copiando archivos: {exc}"}

        # Script que espera a que este proceso termine y luego copia encima + relanza
        current_exe = Path(_sys.executable) if getattr(_sys, "frozen", False) else None
        bat_lines = ["@echo off", "echo Esperando cierre de la aplicacion..."]
        if current_exe:
            bat_lines += [
                f":wait",
                f'tasklist /FI "PID eq %1" 2>NUL | find "%1" >NUL',
                f"if not ERRORLEVEL 1 ( timeout /t 2 >NUL & goto wait )",
                f'echo Copiando nueva version...',
                f'xcopy /Y /E /I "{staging}\\*" "{current_exe.parent}\\"',
                f'echo Lanzando nueva version...',
                f'start "" "{current_exe}"',
            ]
        else:
            bat_lines += [
                f':wait',
                f'timeout /t 3 >NUL',
                f'start "" "{staging / "AVISTA_CPAnalisis.exe"}"',
            ]
        bat_lines.append("del \"%~f0\"")
        bat_path = staging / "updater.bat"
        bat_path.write_text("\r\n".join(bat_lines) + "\r\n", encoding="utf-8")

        pid = os.getpid()
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path), str(pid)],
            creationflags=0x00000008,  # DETACHED_PROCESS
            close_fds=True,
        )

        return {
            "ok": True,
            "mensaje": "Actualización descargada. La aplicación se reiniciará automáticamente.",
            "staging": str(staging),
        }

