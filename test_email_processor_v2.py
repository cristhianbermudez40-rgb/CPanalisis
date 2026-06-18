#!/usr/bin/env python
"""Script de prueba para validar el procesador de correos mejorado V2."""

from pathlib import Path
import sys

# Agregar proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.database.conexion_mysql import DB
from app.utils.email_file_processor_v2 import EmailFileProcessorV2
from app.config import APP_CONFIG


def test_procesar_carpeta():
    """Prueba el procesamiento de la carpeta de email_intake."""
    print("\n" + "=" * 80)
    print("PRUEBA: Procesador de Correos V2")
    print("=" * 80 + "\n")

    entrada = Path(APP_CONFIG.upload_dir) / "email_intake"
    print(f"[ENTRADA] Carpeta de entrada: {entrada}")
    print(f"[ENTRADA] Existe: {entrada.exists()}")

    if entrada.exists():
        archivos = list(entrada.glob("*.txt")) + list(entrada.glob("*.htm")) + list(entrada.glob("*.html"))
        print(f"[ENTRADA] Archivos encontrados: {len(archivos)}")
        for arch in archivos[:5]:
            print(f"   - {arch.name}")

    print("\n" + "-" * 80)
    print("Iniciando procesamiento...")
    print("-" * 80 + "\n")

    try:
        resultado = EmailFileProcessorV2.process_intake_folder(
            intake_folder=entrada,
            archive_folder=None,  # No mover archivos en prueba
            pattern="*.txt,*.htm,*.html",
        )

        print(f"\n[RESULTADO] Procesamiento completado\n")
        print(f"   Procesados:  {resultado.get('procesados', 0)}")
        print(f"   Exitosos:    {resultado.get('exitosos', 0)}")
        print(f"   Duplicados:  {resultado.get('duplicados', 0)}")
        print(f"   Errores:     {resultado.get('errores', 0)}")
        print(f"   Mensaje:     {resultado.get('mensaje', '-')}\n")

        if resultado.get("resultados"):
            print("Detalles de archivos:")
            print("-" * 80)
            for res in resultado["resultados"][:20]:
                estado = "[OK]" if res.get("ok") else "[ERROR]"
                serial = res.get("serial", res.get("archivo", "?"))
                mensaje = res.get("mensaje", "-")[:50]
                print(f"{estado} {serial:<20} {mensaje}")
            print("-" * 80)

        # Listar seriales en BD
        print("\n" + "-" * 80)
        print("Seriales en base de datos:")
        print("-" * 80 + "\n")
        rows = DB.fetch_all(
            """
            SELECT DISTINCT serial_number, COUNT(*) as cantidad,
                   MAX(meter_date) as ultima_lectura, MAX(contador_efectivo) as contador
            FROM lecturas_email_impresoras
            WHERE serial_number IS NOT NULL AND serial_number != ''
            GROUP BY serial_number
            ORDER BY ultima_lectura DESC
            LIMIT 10
            """
        )

        if rows:
            for row in rows:
                serial = row.get("serial_number", "-")
                cant = row.get("cantidad", 0)
                fecha = row.get("ultima_lectura", "-")
                contador = row.get("contador", "-")
                print(f"  Serial: {serial:<20} Contador: {contador:-<10} Cantidad: {cant} Fecha: {fecha}")
        else:
            print("  No hay seriales cargados")

        print("\n" + "=" * 80)
        print("[EXITO] PRUEBA COMPLETADA EXITOSAMENTE")
        print("=" * 80 + "\n")
        return True

    except Exception as exc:
        print(f"\n[ERROR] {exc}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_procesar_carpeta()
    sys.exit(0 if success else 1)
