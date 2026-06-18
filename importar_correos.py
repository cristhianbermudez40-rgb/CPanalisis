#!/usr/bin/env python
"""Script para importar correos y listar seriales guardados en BD."""

from pathlib import Path
import sys

# Agregar el proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.database.conexion_mysql import DB
from app.utils.email_file_processor import EmailFileProcessor
from app.config import APP_CONFIG


def importar_correos_locales(carpeta: str = "", patron: str = "*.txt,*.htm,*.html"):
    """Importa correos desde una carpeta local."""
    
    entrada = Path(carpeta).resolve() if carpeta else (Path(APP_CONFIG.upload_dir) / "email_intake").resolve()
    
    print(f"\n{'='*80}")
    print(f"IMPORTANDO CORREOS DESDE: {entrada}")
    print(f"{'='*80}\n")
    
    if not entrada.exists():
        print(f"❌ ERROR: La carpeta no existe: {entrada}")
        return
    
    try:
        resultado = EmailFileProcessor.process_intake_folder(
            intake_folder=entrada,
            archive_folder=None,  # No mover archivos
            pattern=patron,
        )
        
        print(f"✓ Procesamiento completado")
        print(f"  Total procesados:  {resultado.get('procesados', 0)}")
        print(f"  Exitosos:          {resultado.get('exitosos', 0)}")
        print(f"  Con errores:       {resultado.get('errores', 0)}")
        print(f"  Mensaje:           {resultado.get('mensaje', '-')}\n")
        
        # Mostrar si hay resultados individuales
        if resultado.get('resultados'):
            print("Detalles de cada archivo:")
            for res in resultado['resultados'][:10]:
                if res.get('ok'):
                    print(f"  ✓ {res.get('archivo', '-')}: Serial {res.get('serial', '-')}")
                else:
                    print(f"  ❌ {res.get('archivo', '-')}: {res.get('mensaje', 'Error desconocido')}")
        
        print(f"\n{'='*80}\n")
        
    except Exception as exc:
        print(f"❌ Error importando: {exc}\n")


def listar_seriales_en_bd(limit: int = 100):
    """Lista los seriales guardados en la base de datos."""
    
    print(f"\n{'='*80}")
    print(f"SERIALES EN BASE DE DATOS")
    print(f"{'='*80}\n")
    
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
        
        if not rows:
            print("⚠️  No hay seriales guardados en la BD\n")
            return
        
        print(f"{'SERIAL':<25} {'CANTIDAD':<12} {'ÚLTIMA LECTURA'}")
        print("-" * 70)
        
        for row in rows:
            serial = row.get('serial_number', '-')
            cantidad = row.get('cantidad', 0)
            ultima = row.get('ultima_lectura', '-')
            print(f"{str(serial):<25} {str(cantidad):<12} {str(ultima)}")
        
        print("-" * 70)
        print(f"\nTotal de seriales diferentes: {len(rows)}\n")
        print(f"{'='*80}\n")
        
    except Exception as exc:
        print(f"❌ Error listando seriales: {exc}\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Importa correos y lista seriales en BD")
    parser.add_argument("--carpeta", default="", help="Ruta absoluta a la carpeta de correos")
    parser.add_argument("--patron", default="*.txt,*.htm,*.html", help="Patrón de búsqueda")
    parser.add_argument("--solo-listar", action="store_true", help="Solo lista seriales sin importar")
    
    args = parser.parse_args()
    
    if not args.solo_listar:
        importar_correos_locales(args.carpeta, args.patron)
    
    listar_seriales_en_bd(100)
