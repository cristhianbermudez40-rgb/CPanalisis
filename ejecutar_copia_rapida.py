#!/usr/bin/env python
"""Ejecuta la copia rápida de correos automáticamente."""

import sys
from pathlib import Path

# Agregar el proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.utils.email_file_processor import EmailFileProcessor
from app.database.conexion_mysql import DB


def copia_rapida_automatica():
    """Ejecuta la copia rápida automáticamente."""
    
    print("\n" + "=" * 80)
    print("BUSCANDO Y IMPORTANDO CARPETA 'datecsa' AUTOMÁTICAMENTE")
    print("=" * 80 + "\n")
    
    # Posibles rutas
    rutas_posibles = [
        Path.home() / "Escritorio" / "datecsa",
        Path.home() / "OneDrive" / "Escritorio" / "datecsa",
        Path.home() / "Desktop" / "datecsa",
        Path.home() / "OneDrive" / "Desktop" / "datecsa",
    ]
    
    carpeta = None
    for ruta in rutas_posibles:
        if ruta.exists():
            carpeta = ruta
            print(f"✓ Encontrada carpeta: {ruta}\n")
            break
    
    if not carpeta:
        print("❌ No se encontró la carpeta 'datecsa' en:")
        for ruta in rutas_posibles:
            print(f"   - {ruta}")
        print("\nIntenta crear una carpeta llamada 'datecsa' en tu Escritorio\n")
        return False
    
    # Verificar si hay archivos
    archivos = list(carpeta.glob("*.txt")) + list(carpeta.glob("*.htm")) + list(carpeta.glob("*.html"))
    if not archivos:
        print(f"⚠️  La carpeta está vacía. No hay archivos .txt, .htm o .html\n")
        return False
    
    print(f"✓ Se encontraron {len(archivos)} archivos de correo\n")
    print("⏳ Importando correos a la base de datos...\n")
    
    try:
        resultado = EmailFileProcessor.process_intake_folder(
            intake_folder=carpeta,
            archive_folder=None,
            pattern="*.txt,*.htm,*.html",
        )
        
        print("=" * 80)
        print("RESULTADO DE LA IMPORTACIÓN")
        print("=" * 80 + "\n")
        
        print(f"✓ Procesamiento completado")
        print(f"  • Total de archivos procesados: {resultado.get('procesados', 0)}")
        print(f"  • Importaciones exitosas:       {resultado.get('exitosos', 0)}")
        print(f"  • Archivos con error:           {resultado.get('errores', 0)}\n")
        
        if resultado.get('resultados'):
            print("Detalles por archivo:")
            for res in resultado['resultados'][:10]:
                if res.get('ok'):
                    print(f"  ✓ {res.get('archivo', '?')}")
                else:
                    print(f"  ❌ {res.get('archivo', '?')}: {res.get('mensaje', 'Error')[:60]}")
            print()
        
        # Listar seriales en BD
        print("=" * 80)
        print("SERIALES GUARDADOS EN LA BASE DE DATOS")
        print("=" * 80 + "\n")
        
        rows = DB.fetch_all(
            """
            SELECT DISTINCT serial_number, COUNT(*) as cantidad, 
                   MAX(meter_date) as ultima_lectura
            FROM lecturas_email_impresoras
            WHERE serial_number IS NOT NULL AND serial_number != ''
            GROUP BY serial_number
            ORDER BY ultima_lectura DESC
            LIMIT 50
            """,
            tuple(),
        )
        
        if rows:
            print(f"{'SERIAL':<25} {'CANTIDAD':<12} {'ÚLTIMA LECTURA':<25} {'ESTADO'}")
            print("-" * 80)
            
            for row in rows:
                serial = str(row.get('serial_number', '-'))
                cantidad = str(row.get('cantidad', 0))
                ultima = str(row.get('ultima_lectura', '-'))
                estado = "✓" if row.get('cantidad', 0) > 0 else "?"
                print(f"{serial:<25} {cantidad:<12} {ultima:<25} {estado}")
            
            print("-" * 80)
            print(f"\n✓ Total de seriales únicos en BD: {len(rows)}\n")
            
            return True
        else:
            print("⚠️  No hay seriales guardados todavía\n")
            return False
        
    except Exception as exc:
        print(f"\n❌ Error durante la importación: {exc}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        exito = copia_rapida_automatica()
        
        if exito:
            print("=" * 80)
            print("✓ IMPORTACIÓN COMPLETADA EXITOSAMENTE")
            print("=" * 80)
            print("\n📌 Próximos pasos:")
            print("  1. Abre la aplicación: python app/main.py")
            print("  2. Ve a la pestaña 'Contadores'")
            print("  3. Busca una impresora con uno de los seriales listados arriba")
            print("  4. Haz click en el botón 'Correo' para ver los datos importados\n")
        else:
            print("\n⚠️  No se pudo completar la importación")
            print("   Verifica que tu carpeta 'datecsa' esté en el Escritorio\n")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Proceso cancelado por el usuario\n")
    except Exception as exc:
        print(f"\n❌ Error fatal: {exc}\n")
        import traceback
        traceback.print_exc()
