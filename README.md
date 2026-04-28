# AVISTA Print Analytics

Sistema empresarial de analisis de impresion construido con Python, PySide6, MySQL y dashboard HTML/CSS/JavaScript embebido en `QWebEngineView`.

## Caracteristicas

- Carga de registros desde Excel con control de duplicados por hash.
- Dashboard con ranking de usuarios/oficinas y consumo mensual.
- Comparador de contadores (proveedor vs maquina) con porcentaje de error.
- Analisis de toner para impresoras `M3655idn`.
- Programa de mantenimiento preventivo por umbral de paginas.
- Analisis por tipo de documento impreso.
- Reportes comparativos por numero de serie (mes vs mes / trimestre vs trimestre).
- Exportacion de reportes a Excel y PDF.
- Arquitectura modular preparada para crecimiento multi-ciudad.

## Estructura

```text
app/
 |- main.py
 |- config.py
 |- database/
 |    |- conexion_mysql.py
 |    `- schema.py
 |- models/
 |- controllers/
 |    |- print_controller.py
 |    `- bridge.py
 |- views/
 |    |- main_window.py
 |    `- web/
 |         |- index.html
 |         `- assets/
 |- dashboard/
 |- reports/
 `- utils/
```

## Instalacion

1. Crear entorno virtual.
2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

3. Configurar variables de entorno:

```bash
copy .env.example .env
```

4. Crear base MySQL y usuario con permisos:

```sql
CREATE DATABASE print_analytics CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

5. Ejecutar aplicacion:

```bash
python -m app.main
```

## Conexion con Power BI

Power BI puede conectarse directamente a la base MySQL (`print_analytics`) usando el conector oficial MySQL.
Tablas recomendadas para modelos BI:

- `impresiones`
- `impresoras`
- `oficinas`
- `usuarios`
- `contadores`
- `mantenimientos`

## Funciones clave implementadas

- `cargar_excel()`
- `limpiar_registros()`
- `evitar_duplicados()`
- `generar_estadisticas()`
- `comparar_contadores()`
- `generar_reporte_mensual()`

## Generar ejecutable .exe con PyInstaller

### Opcion 1: Script automatico

```bat
scripts\build_exe.bat
```

### Opcion 2: Comando manual

```bash
pyinstaller --noconfirm --windowed --name avista_print_analytics \
  --add-data "app/views/web;app/views/web" \
  --hidden-import PySide6.QtWebChannel \
  --hidden-import PySide6.QtWebEngineWidgets \
  app/main.py
```

El ejecutable quedara en:

- `dist/avista_print_analytics/avista_print_analytics.exe`

## Notas de escalabilidad

- La base de datos usa entidades normalizadas por oficina, usuario e impresora.
- El dashboard se alimenta por consultas agregadas, lo que permite manejar multiples ciudades.
- Puede migrarse a una capa API/servicios sin cambiar la vista web embebida.
