#!/usr/bin/env python
"""Script para diagnosticar archivos de correo locales sin necesidad de la UI."""

from pathlib import Path
import sys

# Agregar el proyecto al path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.utils.email_meter_parser import parse_meter_email_text
from app.config import APP_CONFIG

def diagnosticar_carpeta(carpeta: str = "", patron: str = "*.txt,*.htm,*.html"):
    """Diagnostica archivos en una carpeta y muestra lo que extrae."""
    
    # Determinar carpeta
    if carpeta:
        entrada = Path(carpeta).resolve()
    else:
        entrada = Path(APP_CONFIG.upload_dir) / "email_intake"
        entrada = entrada.resolve()
    
    print(f"\n{'='*80}")
    print(f"DIAGNOSTICANDO CARPETA: {entrada}")
    print(f"{'='*80}\n")
    
    if not entrada.exists():
        print(f"❌ ERROR: La carpeta no existe: {entrada}")
        print(f"\nIntenta con una ruta absoluta, por ejemplo:")
        print(f"  python diagnosticar_correos.py 'C:\\ruta\\a\\datecsa'")
        return
    
    # Buscar archivos
    patterns = [p.strip() for p in (patron or "*.txt,*.htm,*.html").split(",") if p.strip()]
    files_set = []
    for pat in patterns:
        for file_path in entrada.glob(pat):
            files_set.append(file_path)
    
    files = sorted(dict.fromkeys(files_set), key=lambda p: p.name)
    
    if not files:
        print(f"⚠️  No hay archivos para procesar")
        print(f"   Patrones buscados: {', '.join(patterns)}")
        return
    
    print(f"✓ Se encontraron {len(files)} archivos\n")
    print(f"{'ARCHIVO':<40} {'SERIAL':<20} {'MODELO':<15} {'CONTADOR':<10} {'ERROR'}")
    print("-" * 120)
    
    exitosos = 0
    con_errores = 0
    
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
                con_errores += 1
        except Exception as exc:
            print(f"{file_path.name:<40} {'':<20} {'':<15} {'':<10} ❌ {exc}")
            con_errores += 1
    
    print("-" * 120)
    print(f"\n📊 RESUMEN:")
    print(f"   Total archivos:      {len(files)}")
    print(f"   Con serial válido:   {exitosos}")
    print(f"   Con errores:         {con_errores}")
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Diagnostica archivos de correo locales")
    parser.add_argument("carpeta", nargs="?", default="", help="Ruta absoluta a la carpeta de correos (ej: C:\\ruta\\datecsa)")
    parser.add_argument("--patron", default="*.txt,*.htm,*.html", help="Patrón de búsqueda (ej: *.txt,*.htm,*.html)")
    
    args = parser.parse_args()
    
    diagnosticar_carpeta(args.carpeta, args.patron)
