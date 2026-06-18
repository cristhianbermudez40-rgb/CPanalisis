"""Diálogo de Políticas y Permisos — se muestra en el primer uso del aplicativo.

Al aceptar, se guarda un archivo 'politicas_aceptadas.txt' junto al ejecutable
(o en la raíz del proyecto en desarrollo). En usos siguientes no vuelve a aparecer.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


def _flag_path() -> Path:
    """Ruta del archivo que marca que el usuario aceptó las políticas."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "politicas_aceptadas.txt"
    return Path(__file__).resolve().parents[2] / "politicas_aceptadas.txt"


def politicas_ya_aceptadas() -> bool:
    """Retorna True si el usuario ya aceptó las políticas anteriormente."""
    return _flag_path().exists()


def guardar_aceptacion() -> None:
    """Guarda el registro de aceptación con fecha y hora."""
    path = _flag_path()
    path.write_text(
        f"Politicas aceptadas: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "Aplicativo: AVISTA CPAnalisis\n"
        "Empresa: AVISTA Colombia S.A.S.\n",
        encoding="utf-8",
    )


TEXTO_POLITICAS = """
AVISTA CPAnalisis — Políticas de Uso y Privacidad
Versión 1.0 | AVISTA Colombia S.A.S.

─────────────────────────────────────────────────

1. PROPÓSITO DEL APLICATIVO
   AVISTA CPAnalisis es una herramienta interna desarrollada por AVISTA Colombia S.A.S.
   para el monitoreo, análisis y gestión de contadores de impresoras en las sedes de
   los clientes. Su uso está autorizado exclusivamente para personal de AVISTA Colombia.

2. DATOS QUE ACCEDE Y ALMACENA
   El aplicativo accede y almacena los siguientes tipos de datos:

   • Contadores de impresión (páginas impresas, tipo, fecha).
   • Números de serie y modelos de impresoras.
   • Información de oficinas y ciudades.
   • Niveles de tóner reportados por las impresoras.
   • Correos electrónicos de lectura automática de contadores (IMAP).
   • Credenciales de conexión a la base de datos MySQL (almacenadas en .env).

3. USO DE LA BASE DE DATOS
   El aplicativo se conecta a una base de datos MySQL configurada en el archivo .env.
   Los datos se almacenan en el servidor MySQL configurado por el administrador.
   No se envían datos a servidores externos de terceros.

4. PERMISOS REQUERIDOS
   Para su correcto funcionamiento, este aplicativo necesita:

   ✓ Acceso a red local / VPN (para conectar con MySQL y leer correos IMAP).
   ✓ Lectura de archivos Excel (.xlsx) cargados manualmente por el usuario.
   ✓ Escritura en la carpeta "reportes/" para generar archivos Excel y PDF.
   ✓ Conexión IMAP para leer correos de lectura de contadores automáticamente.
   ✓ Acceso a la red para consultar impresoras vía SNMP (opcional).

5. CONFIDENCIALIDAD
   La información gestionada por este aplicativo es de carácter CONFIDENCIAL.
   Queda prohibida su distribución, copia o uso fuera del ámbito de AVISTA Colombia
   sin autorización expresa de la gerencia.

6. RESPONSABILIDAD DEL USUARIO
   Al instalar y usar este aplicativo, el usuario:
   • Confirma que está autorizado por AVISTA Colombia S.A.S. para usarlo.
   • Se compromete a no compartir las credenciales de acceso.
   • Acepta que los datos generados son propiedad de AVISTA Colombia S.A.S.
   • Entiende que el aplicativo puede acceder a correos configurados en .env.

7. SOPORTE
   Para soporte técnico o reportar incidencias, contactar a:
   Cristhian Bermúdez — cristhian.bermudez@avista.co
   AVISTA Colombia S.A.S.

─────────────────────────────────────────────────

Al hacer clic en "Acepto y Continuar", confirmo que he leído, entiendo y acepto
las políticas descritas anteriormente, y que estoy autorizado para usar este
aplicativo en nombre de AVISTA Colombia S.A.S.
"""


class PoliticasDialog(QDialog):
    """Diálogo modal con las políticas del aplicativo."""

    def __init__(self, icon: QIcon | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AVISTA CPAnalisis — Políticas de Uso")
        self.setMinimumSize(700, 560)
        self.setModal(True)
        if icon:
            self.setWindowIcon(icon)

        # Evitar que se cierre con la X sin aceptar
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # ── Encabezado ─────────────────────────────────────────────────────────
        title = QLabel("📋  Políticas de Uso y Privacidad")
        font_title = QFont()
        font_title.setPointSize(14)
        font_title.setBold(True)
        title.setFont(font_title)
        title.setStyleSheet("color: #1A2B4A;")
        layout.addWidget(title)

        subtitle = QLabel("Por favor, lea y acepte los términos antes de continuar.")
        subtitle.setStyleSheet("color: #64748B; font-size: 12px;")
        layout.addWidget(subtitle)

        # ── Área de texto con scroll ───────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { border: 1px solid #CBD5E1; border-radius: 6px; background: #F8FAFC; }
            QScrollBar:vertical { width: 10px; background: #F1F5F9; }
            QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 5px; min-height: 30px; }
        """)

        content = QLabel(TEXTO_POLITICAS.strip())
        content.setWordWrap(True)
        content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        content.setContentsMargins(16, 14, 16, 14)
        content.setStyleSheet("font-size: 12px; color: #1E293B; line-height: 1.6; font-family: Consolas, monospace;")
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        # ── Checkbox de aceptación ─────────────────────────────────────────────
        self._chk = QCheckBox(
            "He leído y acepto las Políticas de Uso y Privacidad de AVISTA CPAnalisis."
        )
        self._chk.setStyleSheet("font-size: 12px; font-weight: bold; color: #1A2B4A; margin-top: 4px;")
        self._chk.stateChanged.connect(self._on_check_changed)
        layout.addWidget(self._chk)

        # ── Botones ────────────────────────────────────────────────────────────
        self._btn_accept = QPushButton("✅  Acepto y Continuar")
        self._btn_accept.setEnabled(False)
        self._btn_accept.setMinimumHeight(38)
        self._btn_accept.setStyleSheet("""
            QPushButton {
                background: #1A2B4A; color: white; border-radius: 6px;
                font-size: 13px; font-weight: bold; padding: 6px 24px;
            }
            QPushButton:enabled { background: #1A2B4A; }
            QPushButton:enabled:hover { background: #0055A4; }
            QPushButton:disabled { background: #94A3B8; color: #E2E8F0; }
        """)
        self._btn_accept.clicked.connect(self._accept)

        btn_cancel = QPushButton("✖  No acepto — Cerrar")
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background: #E83C6C; color: white; border-radius: 6px;
                font-size: 13px; padding: 6px 24px;
            }
            QPushButton:hover { background: #C62A53; }
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_row = QWidget()
        btn_layout = QVBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)
        btn_layout.addWidget(self._btn_accept)
        btn_layout.addWidget(btn_cancel)
        layout.addWidget(btn_row)

    def _on_check_changed(self, state: int) -> None:
        self._btn_accept.setEnabled(self._chk.isChecked())

    def _accept(self) -> None:
        guardar_aceptacion()
        self.accept()
