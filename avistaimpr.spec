# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para AVISTA CPAnalisis
# Ejecutar: pyinstaller avistaimpr.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # UI web completa (HTML, CSS, JS, imagenes, iconos)
        ('app/views/web', 'app/views/web'),
        # Configuracion base
        ('.env.example', '.'),
    ],
    hiddenimports=[
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebChannel',
        'PySide6.QtPrintSupport',
        'PySide6.QtGui',
        'mysql.connector',
        'mysql.connector.locales',
        'mysql.connector.locales.eng',
        'mysql.connector.plugins',
        'mysql.connector.plugins.mysql_native_password',
        'pandas',
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        'reportlab',
        'reportlab.pdfgen',
        'reportlab.lib',
        'reportlab.platypus',
        'dotenv',
        'email',
        'email.mime',
        'email.mime.text',
        'imaplib',
        'hashlib',
        'socket',
        'struct',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AVISTA_CPAnalisis',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='cp_icon.ico',        # <-- icono CP para el exe
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AVISTA_CPAnalisis',
)
