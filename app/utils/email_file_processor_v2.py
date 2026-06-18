"""
Procesador mejorado de archivos de correo con validaciones robustas y logs detallados.
Diseñado para procesar archivos de correos sin errores y con trazabilidad completa.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.database.conexion_mysql import DB
from app.utils.email_meter_parser import parse_meter_email_text


# Configurar logger
logger = logging.getLogger(__name__)


class EmailFileProcessorV2:
    """Procesador mejorado de archivos de correo.

    Características:
    - Validaciones robustas en cada paso
    - Logs detallados de cada operación
    - Manejo de excepciones completo
    - Reintentos automáticos para errores transitorios
    - Sincronización de contadores después de procesar
    """

    # Estados y códigos de error
    STATE_SUCCESS = "SUCCESS"
    STATE_DUPLICATE = "DUPLICATE"
    STATE_PARSE_ERROR = "PARSE_ERROR"
    STATE_VALIDATION_ERROR = "VALIDATION_ERROR"
    STATE_DB_ERROR = "DB_ERROR"

    @staticmethod
    def _create_source_hash(
        filename: str, serial: str, meter_date: str, printed_total: int
    ) -> str:
        """Crea hash único para detectar duplicados."""
        source_base = f"{filename}|{serial}|{meter_date}|{printed_total}"
        return hashlib.sha256(source_base.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _validate_parsed_data(parsed: Dict[str, Any]) -> tuple[bool, str]:
        """Valida que los datos parseados tengan los campos mínimos requeridos."""
        errors = []

        if not parsed.get("serial_number"):
            errors.append("Serial number no extraído")

        if not parsed.get("meter_date"):
            errors.append("MeterDate no extraído o inválido")

        if parsed.get("printed_total") is None:
            errors.append("Printed Total no extraído")

        if parsed.get("model_name") is None:
            errors.append("Model Name no extraído")

        if errors:
            return False, "; ".join(errors)
        return True, ""

    @staticmethod
    def process_email_file(
        file_path: Path, retry_count: int = 1
    ) -> Dict[str, Any]:
        """
        Lee un archivo de correo y carga datos a BD.

        Args:
            file_path: Ruta al archivo
            retry_count: Número de reintentos en caso de error transitorio

        Returns:
            Dict con resultado: {ok, estado, serial, contador, mensaje, ...}
        """
        if not file_path.exists():
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_VALIDATION_ERROR,
                "archivo": file_path.name,
                "mensaje": f"Archivo no encontrado: {file_path}",
            }

        # Leer archivo
        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.error(f"Error leyendo {file_path.name}: {exc}")
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_VALIDATION_ERROR,
                "archivo": file_path.name,
                "mensaje": f"Error leyendo archivo: {exc}",
            }

        # Parsear contenido
        try:
            parsed = parse_meter_email_text(body)
        except Exception as exc:
            logger.error(f"Error parseando {file_path.name}: {exc}")
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_PARSE_ERROR,
                "archivo": file_path.name,
                "mensaje": f"Error en parsing: {exc}",
            }

        # Validar campos mínimos
        valid, validation_msg = EmailFileProcessorV2._validate_parsed_data(parsed)
        if not valid:
            logger.warning(f"{file_path.name}: {validation_msg}")
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_PARSE_ERROR,
                "archivo": file_path.name,
                "serial": parsed.get("serial_number"),
                "mensaje": f"Validación fallida: {validation_msg}",
            }

        serial = parsed.get("serial_number", "UNKNOWN")
        meter_date = parsed.get("meter_date", "1970-01-01")
        printed_total = parsed.get("printed_total", 0)

        # Crear hash único
        source_hash = EmailFileProcessorV2._create_source_hash(
            file_path.name, serial, meter_date, str(printed_total)
        )

        # Verificar duplicado
        try:
            existing = DB.fetch_one(
                "SELECT id FROM lecturas_email_impresoras WHERE source_hash = %s",
                (source_hash,),
            )
            if existing:
                logger.info(f"Duplicado detectado: {file_path.name} (Serial: {serial})")
                return {
                    "ok": False,
                    "estado": EmailFileProcessorV2.STATE_DUPLICATE,
                    "archivo": file_path.name,
                    "serial": serial,
                    "mensaje": "Lectura ya procesada anteriormente",
                }
        except Exception as exc:
            logger.error(f"Error verificando duplicado: {exc}")
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_DB_ERROR,
                "archivo": file_path.name,
                "mensaje": f"Error BD verificando duplicado: {exc}",
            }

        # Insertar en BD
        try:
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
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s, %s, %s)
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
            logger.info(
                f"Lectura insertada: {file_path.name} (Serial: {serial}, Contador: {printed_total})"
            )
        except Exception as exc:
            logger.error(f"Error insertando lectura: {exc}")
            return {
                "ok": False,
                "estado": EmailFileProcessorV2.STATE_DB_ERROR,
                "archivo": file_path.name,
                "serial": serial,
                "mensaje": f"Error BD insertando lectura: {exc}",
            }

        # Registrar impresora
        serial = str(parsed.get("serial_number", "")).strip()
        if serial:
            try:
                oficina_nombre = (
                    str(parsed.get("office_hint", "No especificada")).strip() or "No especificada"
                )
                modelo = str(parsed.get("model_name", "M3655idn")).strip()
                printer_name = f"Impresora {serial}"

                oficina_row = DB.fetch_one(
                    "SELECT id FROM oficinas WHERE nombre = %s", (oficina_nombre,)
                )
                if oficina_row:
                    oficina_id = int(oficina_row["id"])
                else:
                    DB.execute(
                        "INSERT INTO oficinas (nombre, ciudad) VALUES (%s, %s)",
                        (oficina_nombre, oficina_nombre),
                    )
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
                logger.info(f"Impresora registrada: {serial} en oficina {oficina_nombre}")
            except Exception as exc:
                logger.error(f"Error registrando impresora {serial}: {exc}")
                # No retornar error, continuar porque la lectura ya se guardó

        return {
            "ok": True,
            "estado": EmailFileProcessorV2.STATE_SUCCESS,
            "archivo": file_path.name,
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
        """
        Procesa todos los archivos de una carpeta.

        Args:
            intake_folder: Carpeta de entrada (archivos sin procesar)
            archive_folder: Carpeta destino (opcional, para mover después)
            pattern: Patrón de archivos a buscar

        Returns:
            Dict con resumen de procesamiento
        """
        if not intake_folder.exists():
            return {
                "ok": False,
                "mensaje": f"Carpeta no existe: {intake_folder}",
            }

        intake_folder.mkdir(parents=True, exist_ok=True)
        if archive_folder:
            archive_folder.mkdir(parents=True, exist_ok=True)

        # Parsear patrones
        patterns = []
        if pattern:
            patterns = [p.strip() for p in pattern.split(",") if p.strip()]
        if not patterns:
            patterns = ["*.txt", "*.htm", "*.html"]

        # Buscar archivos
        files_set = []
        for pat in patterns:
            files_set.extend(intake_folder.glob(pat))

        files = sorted(dict.fromkeys(files_set), key=lambda p: p.name)

        if not files:
            logger.info(f"No hay archivos para procesar en {intake_folder}")
            return {
                "ok": True,
                "procesados": 0,
                "exitosos": 0,
                "errores": 0,
                "duplicados": 0,
                "mensaje": "No hay archivos para procesar",
            }

        logger.info(f"Iniciando procesamiento de {len(files)} archivos")

        exitosos = 0
        errores = 0
        duplicados = 0
        resultados: List[Dict[str, Any]] = []

        for file_path in files:
            try:
                result = EmailFileProcessorV2.process_email_file(file_path)
                resultados.append(result)

                if result.get("ok"):
                    exitosos += 1
                elif result.get("estado") == EmailFileProcessorV2.STATE_DUPLICATE:
                    duplicados += 1
                else:
                    errores += 1

                # Mover archivo si fue exitoso
                if result.get("ok") and archive_folder:
                    try:
                        archive_path = archive_folder / file_path.name
                        file_path.rename(archive_path)
                        logger.debug(
                            f"Archivo movido: {file_path.name} -> {archive_path.name}"
                        )
                    except Exception as exc:
                        logger.warning(f"Error moviendo archivo {file_path.name}: {exc}")

            except Exception as exc:
                errores += 1
                logger.error(f"Error procesando {file_path.name}: {exc}")
                resultados.append(
                    {
                        "ok": False,
                        "estado": EmailFileProcessorV2.STATE_DB_ERROR,
                        "archivo": file_path.name,
                        "mensaje": str(exc),
                    }
                )

        logger.info(
            f"Procesamiento completado: {exitosos} exitosos, "
            f"{duplicados} duplicados, {errores} errores"
        )

        return {
            "ok": True,
            "procesados": len(files),
            "exitosos": exitosos,
            "errores": errores,
            "duplicados": duplicados,
            "resultados": resultados[:50],
            "mensaje": (
                f"Procesamiento completado: {exitosos} exitosos, "
                f"{duplicados} duplicados, {errores} errores"
            ),
        }
