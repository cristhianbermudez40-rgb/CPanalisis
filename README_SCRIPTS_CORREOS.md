# Scripts para Diagnosticar e Importar Correos

## 📋 Descripción

Estos scripts permiten diagnosticar e importar archivos de correo de forma directa sin necesidad de usar la interfaz gráfica.

---

## 🔧 Uso

### 1. Diagnosticar archivos en tu carpeta

```bash
python diagnosticar_correos.py "C:\ruta\a\tu\carpeta\datecsa"
```

**Ejemplo real:**
```bash
python diagnosticar_correos.py "C:\Users\CristhianBermudez\OneDrive - AVISTA COLOMBIA SAS\Escritorio\datecsa"
```

**Salida esperada:**
```
================================================================================
DIAGNOSTICANDO CARPETA: C:\Users\CristhianBermudez\...
================================================================================

✓ Se encontraron 5 archivos

ARCHIVO                              SERIAL               MODELO          CONTADOR    ERROR
----------------------------------------------------------------------------------------------------
email1.txt                           R4P0Y67378           ECOSYS M3655     166659      
email2.htm                           R4P0Y67378           ECOSYS M3655     166659      
email3.txt                           UNKNOWN              -                -           ❌ Error...

----------------------------------------------------------------------------------------------------

📊 RESUMEN:
   Total archivos:      5
   Con serial válido:   4
   Con errores:         1

================================================================================
```

---

### 2. Importar correos a la BD

```bash
python importar_correos.py --carpeta "C:\ruta\a\tu\carpeta\datecsa"
```

**Salida esperada:**
```
================================================================================
IMPORTANDO CORREOS DESDE: C:\Users\CristhianBermudez\...
================================================================================

✓ Procesamiento completado
  Total procesados:  5
  Exitosos:          4
  Con errores:       1
  Mensaje:           Procesamiento completado: 4 exitosos, 1 errores

Detalles de cada archivo:
  ✓ email1.txt: Serial R4P0Y67378
  ✓ email2.htm: Serial R4P0Y67378
  ❌ email3.txt: No se pudo extraer numero de serie del archivo

================================================================================

SERIALES EN BASE DE DATOS
================================================================================

SERIAL                    CANTIDAD     ÚLTIMA LECTURA
----------------------------------------------------------------------
R4P0Y67378                4            2026-04-17 15:23:51
OTROS_SERIALS             2            2026-04-16 10:15:00

Total de seriales diferentes: 2

================================================================================
```

---

### 3. Solo ver seriales guardados (sin importar nuevos)

```bash
python importar_correos.py --solo-listar
```

---

## 💡 Opciones adicionales

### Cambiar patrón de búsqueda

Por defecto busca `*.txt,*.htm,*.html`. Para cambiar:

```bash
python diagnosticar_correos.py "C:\ruta\datecsa" --patron "*.txt"
```

O solo HTML:
```bash
python diagnosticar_correos.py "C:\ruta\datecsa" --patron "*.htm,*.html"
```

---

## ✅ Resolución de problemas

### "La carpeta no existe"
- Verifica que la ruta sea correcta
- Usa comillas si la ruta tiene espacios
- Asegúrate que sea la ruta **absoluta** completa

### "No hay archivos para procesar"
- La carpeta existe pero no tiene archivos .txt/.htm/.html
- Verifica que los archivos están en la carpeta correcta
- Busca archivos ocultos

### "No se pudo extraer número de serie"
- El archivo no tiene formato correcto
- Debe contener "Serial Number: XXXXX"
- Verifica que sea un correo válido de Kyocera

---

## 🚀 Próximos pasos

1. **Ejecuta el diagnóstico** para ver qué archivos tienes y qué se extrae
2. **Importa los correos** si el diagnóstico muestra seriales válidos
3. **Verifica los seriales en BD** para confirmar que se guardaron
4. **Usa el botón "Correo"** en la app desde Contadores para consultar

---

## 📝 Notas

- Los scripts NO eliminan archivos; solo leen y importan
- Puedes ejecutar el diagnóstico múltiples veces sin problemas
- La importación verifica duplicados automáticamente
- Los seriales se normalizan automáticamente (mayúsculas, espacios se limpian)
