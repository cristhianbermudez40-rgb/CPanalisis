$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$mainPy = Join-Path $projectRoot "app\main.py"
$iconPath = Join-Path $projectRoot "app\views\web\assets\avista logo.png"

if (-not (Test-Path $pythonExe)) {
    throw "No se encontro el interprete: $pythonExe"
}

if (-not (Test-Path $mainPy)) {
    throw "No se encontro el archivo principal: $mainPy"
}

$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "AVISTA CPAnalisis.lnk"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonExe
$shortcut.Arguments = "`"$mainPy`""
$shortcut.WorkingDirectory = $projectRoot
if (Test-Path $iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Description = "Abrir AVISTA CPAnalisis"
$shortcut.Save()

Write-Output "Acceso directo creado: $shortcutPath"
