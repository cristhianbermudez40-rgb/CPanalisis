# Procesador Local de Correos ECOSYS - Configuracion

## Estado

✅ **FUNCIONANDO COMPLETAMENTE** - El sistema puede procesar archivos de correo de impresoras ECOSYS sin dependencia de IMAP.

## Carpetas de Procesamiento

```
data/uploads/
├── email_intake/           <- AQUI: Coloque archivos .txt de correos
└── email_processed/        <- AUTOMATICO: Archivos procesados exitosamente se mueven aqui
```

## Flujo de Funcionamiento

1. **Preparacion**: Guarde los correos de las impresoras en formato `.txt` en `data/uploads/email_intake/`
2. **Procesamiento**: El sistema lee cada archivo, extrae datos de contador, toner y eventos
3. **Carga**: Los datos se insertan en la tabla `lecturas_email_impresoras`
4. **Archivado**: Los archivos procesados exitosamente se mueven a `email_processed/`
5. **Deduplicacion**: Si el mismo correo se procesa 2x, el segundo intento es rechazado automaticamente

## Datos Extraidos del Correo

Para cada correo se extraen:
- `serial_number`: Numero de serie de la impresora (ej: R4P0Z68403)
- `contador_efectivo`: Total de paginas impresas
- `toner_black_pct`: Porcentaje de toner negro
- `meter_date`: Fecha/hora de la lectura del contador
- `eventos_json`: Eventos de la impresora (papel bajo, toner bajo, etc)

## Como Usar desde Python

```python
from app.utils.email_file_processor import EmailFileProcessor
from pathlib import Path

# Procesar carpeta completa
result = EmailFileProcessor.process_intake_folder(
    intake_folder=Path('data/uploads/email_intake'),
    archive_folder=Path('data/uploads/email_processed'),
    pattern='*.txt'
)

# Ver resultados
print(f"Procesados: {result['procesados']}")
print(f"Exitosos: {result['exitosos']}")
print(f"Errores: {result['errores']}")
```

## Como Usar desde la App (Puente)

En `app/controllers/bridge.py` hay metodos Qt para controlarlo desde UI:

### Procesar carpeta completa
```python
self.procesarCorreosLocales(
    carpeta_entrada='data/uploads/email_intake',
    carpeta_archivo='data/uploads/email_processed',
    patron='*.txt'
)
```

### Procesar archivo individual
```python
self.procesarCorreoArchivo('ruta/al/archivo.txt')
```

## Formato Esperado del Correo

El archivo `.txt` debe tener este formato (copiado del correo original de la impresora):

```
Equipment ID:
Model Name:             ECOSYS M3655idn
Serial Number:          R4P0Z68403
MeterDate:              Mon 06 Apr 2026 16:03:49

Counters by Function:
 Printed Pages:
  Total:                102418
 Scanned Pages:
  Total:                8450
 Combined Sheets:
  none:                 102418

Consumables:
 Black:                 81%

Equipment Log:
<2026-04-06 16:03:00>
 AddPaper Lower Tray

End of Meter Events
```

## Datos de Prueba Cargados

Se han insertado 4 lecturas de prueba en la base de datos:

| Serial      | Contador | Toner | Fecha          |
|------------|----------|-------|----------------|
| R4P0Z68403 | 102,418  | 81%   | 2026-04-06     |
| R4P0354322 | 95,847   | 67%   | 2026-04-07     |
| R4P0Y67374 | 148,756  | 84%   | 2026-04-08     |
| R4P0Y66708 | 72,495   | 55%   | 2026-04-08     |

## Detalles de Implementacion

### Clases Principales

**EmailFileProcessor** (`app/utils/email_meter_parser.py`)
- `process_email_file(file_path)`: Procesa un archivo individual
- `process_intake_folder(intake_folder, archive_folder, pattern)`: Procesa todos los archivos de una carpeta

**PrintController** (`app/controllers/print_controller.py`)
- `procesar_correos_locales(carpeta_entrada, carpeta_archivo, patron)`: Wrapper con manejo de errores
- `procesar_correo_archivo(archivo_ruta)`: Procesa un archivo via UI

**Bridge** (`app/controllers/bridge.py`)
- `procesarCorreosLocales`: Slot Qt para procesar carpeta
- `procesarCorreoArchivo`: Slot Qt para procesar archivo

### Base de Datos

Tabla: `lecturas_email_impresoras`
- Campos automaticos: id, imported_at
- Campos del correo: serial_number, contador_efectivo, toner_black_pct, meter_date, eventos_json
- Deduplicacion: source_hash (SHA256 de filename + serial + date + contador)

## Proximos Pasos Sugeridos

1. **UI Button**: Agregar boton de "Procesar Correos" al panel admin para usuarios finales
2. **Scheduler**: Crear tarea programada para procesar carpeta diariamente
3. **Reporte**: Agregar vista en dashboard mostrando contador vs proveedor (diferencial)
4. **Alerts**: Notificaciones cuando toner < 30% o papel bajo detectado en eventos

## Errores Comunes

| Problema | Causa | Solucion |
|----------|-------|----------|
| "No se pudo extraer numero de serie" | Archivo con formato incorrecto | Usar formato exacto del correo original |
| "Lectura ya procesada anteriormente" | Archivo duplicado | Es normal - deduplicacion funciona como esperado |
| "Carpeta no existe" | Ruta incorrecta | Verificar que la ruta existe relativa a la carpeta del proyecto |
| UnicodeEncodeError | Caracteres especiales en stdout | No es error de procesamiento, solo de visualizacion en terminal |

## Base de Datos - Verificacion Rapida

```sql
-- Ver ultimas lecturas
SELECT serial_number, contador_efectivo, toner_black_pct, meter_date 
FROM lecturas_email_impresoras 
ORDER BY imported_at DESC LIMIT 10;

-- Ver contador de lecturas por dia
SELECT DATE(meter_date) as fecha, COUNT(*) as total 
FROM lecturas_email_impresoras 
GROUP BY DATE(meter_date) 
ORDER BY fecha DESC;
```

---

Ultima actualizacion: 2026-04-08 | Sistema: Operativo
