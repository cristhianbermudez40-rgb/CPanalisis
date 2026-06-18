@echo off
:: =========================================================
:: AVISTA CPAnalisis — Proxy SNMP  (inicio facil oficina)
:: =========================================================
:: Copia este archivo junto a microservicio_snmp_proxy.py
:: y ejecuta con doble clic (o agrega a Tarea Programada).
::
:: Variables configurables:
::   PUERTO   — puerto en el que escucha (default 8765)
::   SITIO    — nombre de esta oficina (aparece en /ping)
::   TOKEN    — token de seguridad (dejar en blanco = sin auth)
::
:: Port-forwarding recomendado en el router de la oficina:
::   TCP exterior %PUERTO%  ->  IP-de-este-pc:%PUERTO%

setlocal

set PUERTO=8765
set SITIO=Oficina Remota
set TOKEN=

:: Detecta python disponible
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python no encontrado. Instala Python 3.9+ desde https://python.org
    pause
    exit /b 1
)

:: Directorio de este .bat (donde esta tambien el .py)
cd /d "%~dp0"

echo Iniciando proxy SNMP en puerto %PUERTO%  [sitio: %SITIO%]
echo Presiona Ctrl+C para detener.

python microservicio_snmp_proxy.py ^
    --port %PUERTO% ^
    --sitio "%SITIO%" ^
    --token "%TOKEN%"

pause
