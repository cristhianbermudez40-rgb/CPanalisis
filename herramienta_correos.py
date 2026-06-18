#!/usr/bin/env python
"""Script simple para diagnosticar y resolver problema de correos - EJECUTA ESTO DIRECTAMENTE."""

import sys
from pathlib import Path

# Agregar el proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def menu_principal():
    """Menú interactivo para el usuario."""
    
    print("\n")
    print("=" * 80)
    print(" HERRAMIENTA DE DIAGNÓSTICO Y IMPORTACIÓN DE CORREOS DE IMPRESORAS")
    print("=" * 80)
    print()
    print("¿Qué deseas hacer?")
    print()
    print("  1. Diagnosticar archivos en una carpeta (ver qué se extrae)")
    print("  2. Importar correos a la base de datos")
    print("  3. Ver seriales guardados en la BD")
    print("  4. Copia rápida: carpeta datecsa (si existe en Escritorio)")
    print("  5. Salir")
    print()
    
    opcion = input("Selecciona opción (1-5): ").strip()
    return opcion


def diagnosticar():
    """Diagnostica archivos."""
    from app.utils.email_meter_parser import parse_meter_email_text
    
    print("\n" + "=" * 80)
    print("DIAGNÓSTICO DE ARCHIVOS")
    print("=" * 80 + "\n")
    
    carpeta = input("Ingresa la ruta de la carpeta (ej: C:\\Users\\usuario\\datecsa): ").strip()
    if not carpeta:
        print("❌ Debe ingresar una ruta válida")
        return
    
    entrada = Path(carpeta).resolve()
    if not entrada.exists():
        print(f"❌ La carpeta no existe: {entrada}")
        return
    
    patron = input("Patrón de búsqueda (Enter para *.txt,*.htm,*.html): ").strip()
    if not patron:
        patron = "*.txt,*.htm,*.html"
    
    patterns = [p.strip() for p in patron.split(",") if p.strip()]
    files_set = []
    for pat in patterns:
        for file_path in entrada.glob(pat):
            files_set.append(file_path)
    
    files = sorted(dict.fromkeys(files_set), key=lambda p: p.name)
    
    if not files:
        print(f"\n⚠️  No hay archivos en {entrada}")
        return
    
    print(f"\n✓ Se encontraron {len(files)} archivos\n")
    print(f"{'ARCHIVO':<40} {'SERIAL':<20} {'MODELO':<15} {'CONTADOR':<10}")
    print("-" * 100)
    
    exitosos = 0
    con_error = 0
    
    for file_path in files:
        try:
            body = file_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_meter_email_text(body)
            
            serial = parsed.get("serial_number") or "-"
            model = parsed.get("model_name") or "-"
            contador = parsed.get("contador_efectivo") or "-"
            
            print(f"{file_path.name:<40} {str(serial):<20} {str(model):<15} {str(contador):<10}")
            
            if parsed.get("serial_number"):
                exitosos += 1
            else:
                con_error += 1
        except Exception as exc:
            print(f"{file_path.name:<40} ERROR: {str(exc)[:55]}")
            con_error += 1
    
    print("-" * 100)
    print(f"\n📊 Resumen: {len(files)} total | {exitosos} válidos | {con_error} con error\n")


def importar():
    """Importa correos a la BD."""
    from app.utils.email_file_processor import EmailFileProcessor
    from app.config import APP_CONFIG
    
    print("\n" + "=" * 80)
    print("IMPORTAR CORREOS")
    print("=" * 80 + "\n")
    
    carpeta = input("Ingresa la ruta de la carpeta (ej: C:\\Users\\usuario\\datecsa): ").strip()
    if not carpeta:
        print("❌ Debe ingresar una ruta válida")
        return
    
    entrada = Path(carpeta).resolve()
    if not entrada.exists():
        print(f"❌ La carpeta no existe: {entrada}")
        return
    
    patron = input("Patrón de búsqueda (Enter para *.txt,*.htm,*.html): ").strip()
    if not patron:
        patron = "*.txt,*.htm,*.html"
    
    print("\n⏳ Importando correos...\n")
    
    try:
        resultado = EmailFileProcessor.process_intake_folder(
            intake_folder=entrada,
            archive_folder=None,
            pattern=patron,
        )
        
        print(f"✓ Procesamiento completado")
        print(f"  Total procesados:  {resultado.get('procesados', 0)}")
        print(f"  Exitosos:          {resultado.get('exitosos', 0)}")
        print(f"  Con errores:       {resultado.get('errores', 0)}\n")
        
    except Exception as exc:
        print(f"❌ Error importando: {exc}\n")


def listar_seriales():
    """Lista seriales en BD."""
    from app.database.conexion_mysql import DB
    
    print("\n" + "=" * 80)
    print("SERIALES EN BASE DE DATOS")
    print("=" * 80 + "\n")
    
    try:
        rows = DB.fetch_all(
            """
            SELECT DISTINCT serial_number, COUNT(*) as cantidad, 
                   MAX(meter_date) as ultima_lectura
            FROM lecturas_email_impresoras
            WHERE serial_number IS NOT NULL AND serial_number != ''
            GROUP BY serial_number
            ORDER BY ultima_lectura DESC
            LIMIT 100
            """,
            tuple(),
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
        
    except Exception as exc:
        print(f"❌ Error listando seriales: {exc}\n")


def copia_rapida():
    """Intenta copiar desde carpeta datecsa en Escritorio."""
    from app.utils.email_file_processor import EmailFileProcessor
    
    print("\n" + "=" * 80)
    print("COPIA RÁPIDA - Buscando carpeta 'datecsa' en Escritorio")
    print("=" * 80 + "\n")
    
    # Posibles rutas
    escritorio = Path.home() / "Escritorio" / "datecsa"
    onedrive = Path.home() / "OneDrive" / "Escritorio" / "datecsa"
    
    carpeta = None
    if escritorio.exists():
        carpeta = escritorio
        print(f"✓ Encontrada en: {escritorio}\n")
    elif onedrive.exists():
        carpeta = onedrive
        print(f"✓ Encontrada en: {onedrive}\n")
    else:
        print(f"❌ No se encontró 'datecsa' en:")
        print(f"   - {escritorio}")
        print(f"   - {onedrive}\n")
        return
    
    print("⏳ Importando correos...")
    try:
        resultado = EmailFileProcessor.process_intake_folder(
            intake_folder=carpeta,
            archive_folder=None,
            pattern="*.txt,*.htm,*.html",
        )
        
        print(f"\n✓ Procesamiento completado")
        print(f"  Total procesados:  {resultado.get('procesados', 0)}")
        print(f"  Exitosos:          {resultado.get('exitosos', 0)}")
        print(f"  Con errores:       {resultado.get('errores', 0)}\n")
        
        # Listar seriales
        print("=" * 80)
        print("SERIALES IMPORTADOS EN BD:")
        print("=" * 80 + "\n")
        
        from app.database.conexion_mysql import DB
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
            print(f"{'SERIAL':<25} {'CANTIDAD':<12} {'ÚLTIMA LECTURA'}")
            print("-" * 70)
            for row in rows:
                print(f"{str(row.get('serial_number', '-')):<25} {str(row.get('cantidad', 0)):<12} {str(row.get('ultima_lectura', '-'))}")
            print("-" * 70)
        
        print()
        
    except Exception as exc:
        print(f"❌ Error: {exc}\n")


def main():
    """Menú principal."""
    
    while True:
        try:
            opcion = menu_principal()
            
            if opcion == "1":
                diagnosticar()
            elif opcion == "2":
                importar()
            elif opcion == "3":
                listar_seriales()
            elif opcion == "4":
                copia_rapida()
            elif opcion == "5":
                print("\n✓ ¡Hasta luego!\n")
                break
            else:
                print("\n❌ Opción inválida\n")
            
            input("\nPresiona Enter para continuar...")
            
        except KeyboardInterrupt:
            print("\n\n✓ Programa cancelado\n")
            break
        except Exception as exc:
            print(f"\n❌ Error: {exc}\n")
            input("Presiona Enter para continuar...")


if __name__ == "__main__":
    main()
