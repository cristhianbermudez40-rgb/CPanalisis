"""Diálogo de configuración MySQL — aparece cuando la conexión falla.
Permite al usuario ingresar las credenciales, las prueba en vivo
y las guarda en el .env junto al ejecutable.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

import mysql.connector
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


def _env_path() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / ".env"
    return Path(__file__).resolve().parents[2] / ".env"


def _save_mysql_env(host: str, port: str, user: str, password: str, database: str) -> None:
    """Actualiza las claves MySQL en el .env sin tocar el resto."""
    path = _env_path()
    updates = {
        "MYSQL_HOST": host,
        "MYSQL_PORT": port,
        "MYSQL_USER": user,
        "MYSQL_PASSWORD": password,
        "MYSQL_DATABASE": database,
    }

    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    result = []
    found = set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            result.append(f"{key}={updates[key]}")
            found.add(key)
        else:
            result.append(line)

    for k, v in updates.items():
        if k not in found:
            result.append(f"{k}={v}")

    path.write_text("\n".join(result) + "\n", encoding="utf-8")

    # Actualizar os.environ para que el pool use los nuevos valores
    for k, v in updates.items():
        os.environ[k] = v


def probar_y_crear_db(host: str, port: int, user: str, password: str, database: str) -> str:
    """Prueba la conexión, crea la BD si no existe. Retorna "" si OK, mensaje de error si falla."""
    # 1. Puerto abierto?
    try:
        s = socket.create_connection((host, port), timeout=4)
        s.close()
    except Exception:
        return f"No se puede conectar a {host}:{port} — verifica que MySQL esté corriendo."

    # 2. Credenciales válidas (sin base de datos)?
    try:
        conn = mysql.connector.connect(
            host=host, port=port, user=user, password=password,
            connection_timeout=6,
            auth_plugin="caching_sha2_password",
        )
    except mysql.connector.Error:
        # Reintentar sin forzar plugin (compatibilidad con versiones anteriores)
        try:
            conn = mysql.connector.connect(
                host=host, port=port, user=user, password=password,
                connection_timeout=6,
            )
        except mysql.connector.Error as e:
            code = e.errno
            if code in (1045, 1044):
                return "Contraseña incorrecta para el usuario MySQL."
            return f"Error de autenticación: {e.msg}"

    # 3. Crear BD si no existe
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        cur.close()
    except mysql.connector.Error as e:
        conn.close()
        return f"No se pudo crear la base de datos: {e.msg}"

    conn.close()
    return ""  # éxito


class MySQLSetupDialog(QDialog):
    """Diálogo para configurar credenciales MySQL desde dentro del .exe."""

    def __init__(self, error_msg: str = "", icon: QIcon | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AVISTA CPAnalisis — Configurar MySQL")
        self.setMinimumWidth(480)
        self.setModal(True)
        if icon:
            self.setWindowIcon(icon)

        self._build_ui(error_msg)

    def _build_ui(self, error_msg: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Encabezado ───────────────────────────────────────────────────
        title = QLabel("⚙️  Configuración de MySQL")
        f = QFont(); f.setPointSize(13); f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #1A2B4A;")
        layout.addWidget(title)

        if error_msg:
            err_lbl = QLabel(f"⚠  {error_msg}")
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                "background:#FEF2F2; color:#B91C1C; border:1px solid #FECACA;"
                "border-radius:6px; padding:8px 10px; font-size:12px;"
            )
            layout.addWidget(err_lbl)

        sub = QLabel("Ingresa los datos de conexión de MySQL en este computador:")
        sub.setStyleSheet("color:#64748B; font-size:12px;")
        layout.addWidget(sub)

        # ── Formulario ───────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        style_field = (
            "QLineEdit { border:1px solid #CBD5E1; border-radius:5px;"
            "padding:6px 10px; font-size:13px; }"
            "QLineEdit:focus { border:1px solid #1A2B4A; }"
        )

        self._host = QLineEdit(os.getenv("MYSQL_HOST", "127.0.0.1"))
        self._host.setStyleSheet(style_field)
        form.addRow("Host MySQL:", self._host)

        self._port = QLineEdit(os.getenv("MYSQL_PORT", "3306"))
        self._port.setStyleSheet(style_field)
        form.addRow("Puerto:", self._port)

        self._user = QLineEdit(os.getenv("MYSQL_USER", "root"))
        self._user.setStyleSheet(style_field)
        form.addRow("Usuario:", self._user)

        self._pass = QLineEdit(os.getenv("MYSQL_PASSWORD", ""))
        self._pass.setEchoMode(QLineEdit.Password)
        self._pass.setStyleSheet(style_field)
        self._pass.setPlaceholderText("Contraseña de root MySQL")
        form.addRow("Contraseña:", self._pass)

        self._db = QLineEdit(os.getenv("MYSQL_DATABASE", "local"))
        self._db.setStyleSheet(style_field)
        form.addRow("Base de datos:", self._db)

        layout.addLayout(form)

        # ── Estado ───────────────────────────────────────────────────────
        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("font-size:12px; min-height:20px;")
        layout.addWidget(self._status_lbl)

        # ── Botones ──────────────────────────────────────────────────────
        btn_save = QPushButton("✅  Probar conexión y Guardar")
        btn_save.setMinimumHeight(40)
        btn_save.setStyleSheet("""
            QPushButton {
                background:#1A2B4A; color:white; border-radius:6px;
                font-size:13px; font-weight:bold; padding:6px 20px;
            }
            QPushButton:hover { background:#0055A4; }
        """)
        btn_save.clicked.connect(self._on_save)

        btn_cancel = QPushButton("Cancelar — Cerrar")
        btn_cancel.setMinimumHeight(38)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background:#E83C6C; color:white; border-radius:6px;
                font-size:12px; padding:6px 20px;
            }
            QPushButton:hover { background:#C62A53; }
        """)
        btn_cancel.clicked.connect(self.reject)

        layout.addWidget(btn_save)
        layout.addWidget(btn_cancel)

    def _on_save(self) -> None:
        host = self._host.text().strip()
        port = self._port.text().strip()
        user = self._user.text().strip()
        pwd  = self._pass.text().strip()
        db   = self._db.text().strip()

        self._status_lbl.setText("Probando conexión…")
        self._status_lbl.setStyleSheet("font-size:12px; color:#64748B;")
        self.repaint()

        try:
            port_int = int(port)
        except ValueError:
            self._status_lbl.setText("⚠  El puerto debe ser un número (ejemplo: 3306)")
            self._status_lbl.setStyleSheet("font-size:12px; color:#B91C1C;")
            return

        err = probar_y_crear_db(host, port_int, user, pwd, db)
        if err:
            self._status_lbl.setText(f"❌  {err}")
            self._status_lbl.setStyleSheet("font-size:12px; color:#B91C1C;")
            return

        # Guardar y cerrar con éxito
        _save_mysql_env(host, port, user, pwd, db)
        self._status_lbl.setText("✅  Conexión exitosa — iniciando aplicativo…")
        self._status_lbl.setStyleSheet("font-size:12px; color:#15803D;")
        self.repaint()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(600, self.accept)
