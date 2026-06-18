#!/usr/bin/env python
"""Importar correos rápidamente desde email_intake."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

from app.utils.email_file_processor import EmailFileProcessor
from app.database.conexion_mysql import DB
from app.config import APP_CONFIG

print('\n' + '='*80)
print('IMPORTANDO CORREOS DESDE CARPETA POR DEFECTO')
print('='*80 + '\n')

carpeta = APP_CONFIG.upload_dir / 'email_intake'
print(f'Carpeta: {carpeta}\n')

resultado = EmailFileProcessor.process_intake_folder(
    intake_folder=carpeta,
    archive_folder=None,
    pattern='*.txt,*.htm,*.html',
)

print(f'✓ Procesamiento completado')
print(f'  Total procesados:  {resultado.get("procesados", 0)}')
print(f'  Exitosos:          {resultado.get("exitosos", 0)}')
print(f'  Con errores:       {resultado.get("errores", 0)}\n')

if resultado.get('resultados'):
    print('Detalles de importación:')
    for res in resultado['resultados'][:10]:
        if res.get('ok'):
            print(f'  ✓ {res.get("archivo", "?")}: Serial {res.get("serial", "?")}')
        else:
            print(f'  ❌ {res.get("archivo", "?")}: {res.get("mensaje", "Error")}')
    print()

# Listar seriales
print('='*80)
print('SERIALES EN BASE DE DATOS')
print('='*80 + '\n')

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
    print(f'{"SERIAL":<25} {"CANTIDAD":<12} {"ÚLTIMA LECTURA":<25} {"ESTADO"}')
    print("-" * 80)
    
    for row in rows:
        serial = str(row.get('serial_number', '-'))
        cantidad = str(row.get('cantidad', 0))
        ultima = str(row.get('ultima_lectura', '-'))
        estado = "✓" if row.get('cantidad', 0) > 0 else "?"
        print(f"{serial:<25} {cantidad:<12} {ultima:<25} {estado}")
    
    print("-" * 80)
    print(f'\n✓ Total de seriales únicos en BD: {len(rows)}\n')
else:
    print('⚠️  No hay seriales guardados\n')

print('='*80)
print('IMPORTACIÓN COMPLETADA')
print('='*80)
print('\n📌 Próximos pasos:')
print('  1. Abre la aplicación: python app/main.py')
print('  2. Ve a "Contadores"')
print('  3. Busca una impresora con uno de los seriales arriba')
print('  4. Click en "Correo" para ver los datos\n')
