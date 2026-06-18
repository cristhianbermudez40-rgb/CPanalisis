@echo off
setlocal
cd /d %~dp0\..

echo === AVISTA CPAnalisis - Build portable ===
echo.

REM Crear .env si no existe
if not exist .env (
    if exist .env.example (
        copy .env.example .env > nul
        echo [OK] .env creado desde .env.example - configure sus credenciales MySQL antes de usar el exe.
    )
)

REM Generar logo modo oscuro
echo [1/3] Generando logo modo oscuro...
python scripts\crear_logo_oscuro.py
if errorlevel 1 (
    echo [WARN] No se pudo generar logo oscuro - continuando sin el.
)

echo.
echo [2/3] Compilando con PyInstaller...
pyinstaller --noconfirm avistaimpr.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build fallido. Revise los errores anteriores.
    exit /b 1
)

echo.
echo [3/3] Copiando archivos al directorio de salida...
if exist .env (
    copy .env "dist\AVISTA_CPAnalisis\.env" > nul
    echo [OK] .env copiado a dist\AVISTA_CPAnalisis\
)
if not exist "dist\AVISTA_CPAnalisis\reportes" (
    mkdir "dist\AVISTA_CPAnalisis\reportes"
    echo [OK] Carpeta reportes creada en dist\AVISTA_CPAnalisis\
)

echo.
echo ============================================
echo  Build exitoso: dist\AVISTA_CPAnalisis\
echo  Ejecutable: dist\AVISTA_CPAnalisis\AVISTA_CPAnalisis.exe
echo ============================================
endlocal
