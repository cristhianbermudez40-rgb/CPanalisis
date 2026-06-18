from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database.conexion_mysql import DB
from app.utils.email_meter_parser import parse_meter_email_text


class EmailFileProcessor:
    """Procesa archivos de correo desde carpeta local sin dependencia de IMAP."""

    @staticmethod
    def process_email_file(file_path: Path) -> Dict[str, Any]:
        """Lee un archivo de correo plain text y carga datos a BD."""
        if not file_path.exists():
            return {"ok": False, "mensaje": f"Archivo no encontrado: {file_path}"}

        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"ok": False, "mensaje": f"Error leyendo archivo: {exc}"}

        parsed = parse_meter_email_text(body)
        if not parsed.get("serial_number"):
            return {
                "ok": False,
                "mensaje": "No se pudo extraer numero de serie del archivo",
                "parsed_keys": list(parsed.keys()),
            }

        source_base = f"{file_path.name}|{parsed.get('serial_number')}|{parsed.get('meter_date')}|{parsed.get('printed_total')}"
        source_hash = hashlib.sha256(source_base.encode("utf-8", errors="ignore")).hexdigest()

        existing = DB.fetch_one(
            "SELECT id FROM lecturas_email_impresoras WHERE source_hash = %s",
            (source_hash,),
        )
        if existing:
            return {
                "ok": False,
                "mensaje": "Lectura ya procesada anteriormente",
                "serial": parsed.get("serial_number"),
            }

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
                file_path.stem,
                None,
                source_hash,
                "archivo_local",
                file_path.name,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

        serial = str(parsed.get("serial_number", "")).strip()
        if serial:
            oficina_nombre = str(parsed.get("office_hint", "Archivo")).strip()
            modelo = str(parsed.get("model_name", "M3655idn")).strip()
            printer_name = str(parsed.get("model_name", "Impresora")).strip()

            oficina_row = DB.fetch_one("SELECT id FROM oficinas WHERE nombre = %s", (oficina_nombre,))
            if oficina_row:
                oficina_id = int(oficina_row["id"])
            else:
                DB.execute("INSERT INTO oficinas (nombre, ciudad) VALUES (%s, %s)", (oficina_nombre, oficina_nombre))
                oficina_id = int(DB.fetch_one("SELECT LAST_INSERT_ID() AS id")["id"])

            DB.execute(
                """
                INSERT INTO impresoras (nombre, numero_serie, modelo, oficina_id, ciudad)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    nombre = VALUES(nombre),
                    modelo = VALUES(modelo),
                    oficina_id = VALUES(oficina_id)
                """,
                (printer_name, serial, modelo, oficina_id, oficina_nombre),
            )

        return {
            "ok": True,
            "serial": parsed.get("serial_number"),
            "modelo": parsed.get("model_name"),
            "oficina": parsed.get("office_hint"),
            "contador": parsed.get("contador_efectivo"),
            "meter_date": parsed.get("meter_date"),
            "toner": parsed.get("toner_black_pct"),
            "mensaje": "Lectura cargada exitosamente",
        }

    @staticmethod
    def process_intake_folder(
        intake_folder: Path,
        archive_folder: Optional[Path] = None,
        pattern: str = "*.txt",
    ) -> Dict[str, Any]:
        """Procesa todos los archivos de texto en una carpeta."""
        if not intake_folder.exists():
            return {"ok": False, "mensaje": f"Carpeta no existe: {intake_folder}"}

        intake_folder.mkdir(parents=True, exist_ok=True)
        if archive_folder:
            archive_folder.mkdir(parents=True, exist_ok=True)

        patterns = [p.strip() for p in pattern.split(",") if p.strip()] if pattern else []
        if not patterns:
            patterns = ["*.txt", "*.htm", "*.html"]

        files_set = []
        for pat in patterns:
            for file_path in intake_folder.glob(pat):
                files_set.append(file_path)

        files = sorted(dict.fromkeys(files_set), key=lambda p: p.name)
        if not files:
            return {
                "ok": True,
                "procesados": 0,
                "exitosos": 0,
                "errores": 0,
                "mensaje": "No hay archivos para procesar",
            }

        exitosos = 0
        errores = 0
        resultados: List[Dict[str, Any]] = []

        for file_path in files:
            try:
                result = EmailFileProcessor.process_email_file(file_path)
                resultados.append(result)

                if result.get("ok"):
                    exitosos += 1
                    if archive_folder:
                        archive_path = archive_folder / file_path.name
                        file_path.rename(archive_path)
                else:
                    errores += 1
            except Exception as exc:
                errores += 1
                resultados.append({"ok": False, "archivo": file_path.name, "error": str(exc)})

        return {
            "ok": True,
            "procesados": len(files),
            "exitosos": exitosos,
            "errores": errores,
            "resultados": resultados[:20],
            "mensaje": f"Procesamiento completado: {exitosos} exitosos, {errores} errores",
        }
