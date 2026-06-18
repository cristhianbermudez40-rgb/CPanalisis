import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """Devuelve la carpeta raíz tanto en desarrollo como en exe PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()

if __package__ is None or __package__ == "":
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

import os
os.environ.setdefault("_AVISTA_BASE_DIR", str(BASE_DIR))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QSplashScreen

from app.views.politicas_dialog import PoliticasDialog, politicas_ya_aceptadas
from app.views.mysql_setup_dialog import MySQLSetupDialog, probar_y_crear_db


def _set_taskbar_icon() -> None:
    """Fuerza a Windows a mostrar el ícono CP en la barra de tareas."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "avista.cpanalisis.1.0"
        )
    except Exception:
        pass


def _find_icon() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "cp_icon.ico"
    ico = BASE_DIR / "cp_icon.ico"
    if ico.exists():
        return ico
    return BASE_DIR / "app" / "views" / "web" / "assets" / "cp_icon.png"


def _ensure_mysql(app_icon: QIcon) -> bool:
    """
    Verifica conexión MySQL. Si falla, muestra el diálogo de configuración.
    Retorna True si la conexión quedó lista, False si el usuario canceló.
    """
    import os
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port_str = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    pwd  = os.getenv("MYSQL_PASSWORD", "")
    db   = os.getenv("MYSQL_DATABASE", "local")

    err = probar_y_crear_db(host, int(port_str), user, pwd, db)
    if not err:
        return True  # ya funciona, seguir sin dialogo

    # Mostrar diálogo de configuración
    while True:
        dlg = MySQLSetupDialog(error_msg=err, icon=app_icon)
        result = dlg.exec()
        if result != QDialog.Accepted:
            return False  # usuario canceló

        # Reintentar con los nuevos valores guardados
        host = os.getenv("MYSQL_HOST", "127.0.0.1")
        port_str = os.getenv("MYSQL_PORT", "3306")
        user = os.getenv("MYSQL_USER", "root")
        pwd  = os.getenv("MYSQL_PASSWORD", "")
        db   = os.getenv("MYSQL_DATABASE", "local")
        err = probar_y_crear_db(host, int(port_str), user, pwd, db)
        if not err:
            return True


def _make_splash(app) -> QSplashScreen:
    """Crea un splash screen con fondo oscuro y mensaje de carga."""
    pix = QPixmap(480, 220)
    pix.fill(QColor("#1A2B4A"))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop,
                     "\n\nAVISTA CPAnalisis")

    painter.setFont(QFont("Segoe UI", 10))
    painter.setPen(QColor("#93c5fd"))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "Iniciando aplicativo...")

    painter.setFont(QFont("Segoe UI", 8))
    painter.setPen(QColor("#64748b"))
    painter.drawText(pix.rect().adjusted(0, 0, -10, -10),
                     Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, "v1.1.0")
    painter.end()

    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash


def main() -> None:
    _set_taskbar_icon()

    app = QApplication(sys.argv)

    # Ícono global
    icon_path = _find_icon()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # ── Políticas — solo la primera vez ────────────────────────────────
    if not politicas_ya_aceptadas():
        dlg = PoliticasDialog(icon=app.windowIcon())
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)

    # ── Verificar / configurar MySQL ────────────────────────────────────
    if not _ensure_mysql(app.windowIcon()):
        sys.exit(0)

    # ── Splash screen — mostrar mientras se cargan las tablas ───────────
    splash = _make_splash(app)
    _W = QColor("white")
    _AL = Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft
    splash.showMessage("  Conectando a la base de datos...", _AL, _W)
    app.processEvents()

    # ── Reiniciar el pool de DB con los valores actuales ────────────────
    from app.database.conexion_mysql import DB
    DB._pool = None  # forzar reconexión con nuevos valores del .env

    # ── Inicializar tablas ──────────────────────────────────────────────
    try:
        splash.showMessage("  Creando tablas...", _AL, _W)
        app.processEvents()
        from app.database.schema import initialize_database
        initialize_database()
    except Exception as exc:
        splash.close()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "Error al crear tablas",
            f"No se pudieron crear las tablas en la base de datos.\n\n{exc}"
        )
        sys.exit(1)

    # ── Abrir ventana principal ─────────────────────────────────────────
    splash.showMessage("  Cargando interfaz...", _AL, _W)
    app.processEvents()

    from app.views.main_window import MainWindow
    window = MainWindow()
    window.show()
    splash.finish(window)   # splash desaparece cuando la ventana está lista
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
