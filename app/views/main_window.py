from __future__ import annotations

import calendar
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from app.controllers.bridge import AppBridge


def _find_html() -> Path:
    """Localiza index.html tanto en desarrollo como en exe PyInstaller."""
    if getattr(sys, "frozen", False):
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        candidate = meipass / "app" / "views" / "web" / "index.html"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / "web" / "index.html"


def _find_icon() -> Path:
    """Localiza cp_icon.ico (o .png como fallback) en desarrollo y en exe."""
    if getattr(sys, "frozen", False):
        meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        for candidate in [
            meipass / "cp_icon.ico",
            meipass / "app" / "views" / "web" / "assets" / "cp_icon.png",
        ]:
            if candidate.exists():
                return candidate
    project_root = Path(__file__).resolve().parents[2]
    ico = project_root / "cp_icon.ico"
    if ico.exists():
        return ico
    return Path(__file__).resolve().parent / "web" / "assets" / "cp_icon.png"


def _is_last_day_of_month() -> bool:
    today = datetime.now()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return today.day == last_day


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AVISTA CPAnalisis")
        self.resize(1400, 900)

        icon_path = _find_icon()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.web_view = QWebEngineView(self)
        self.setCentralWidget(self.web_view)

        self.channel = QWebChannel(self.web_view.page())
        self.bridge = AppBridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        html_path = _find_html()
        self.web_view.setUrl(QUrl.fromLocalFile(str(html_path)))

        # ── Timers ────────────────────────────────────────────────────────────
        # Tareas cada hora
        self._tareas_periodicas()
        self._timer_horas = QTimer(self)
        self._timer_horas.timeout.connect(self._tareas_periodicas)
        self._timer_horas.start(60 * 60 * 1000)

        # Check de actualizaciones al inicio (delay 8s para esperar que cargue la web)
        # y luego cada 4 horas
        self._timer_update = QTimer(self)
        self._timer_update.setSingleShot(True)
        self._timer_update.timeout.connect(self._check_update_and_schedule)
        self._timer_update.start(8000)

        # Watcher de la carpeta compartida: detecta cambios inmediatos
        self._update_watcher = QFileSystemWatcher(self)
        self._update_watcher.directoryChanged.connect(self._on_update_folder_changed)
        self._update_watcher.fileChanged.connect(self._on_update_folder_changed)
        QTimer.singleShot(10000, self._init_update_watcher)

    def closeEvent(self, event) -> None:
        self._timer_horas.stop()
        self._timer_update.stop()
        self.bridge.cleanup()
        super().closeEvent(event)

    def _init_update_watcher(self) -> None:
        """Agrega la carpeta de actualizaciones al watcher al iniciar."""
        try:
            from app.config import APP_CONFIG
            folder = APP_CONFIG.update_folder.strip()
            if folder:
                self._reconfigura_watcher(folder)
        except Exception:
            pass

    def _reconfigura_watcher(self, carpeta: str) -> None:
        """Actualiza el watcher cuando el usuario guarda una nueva ruta."""
        from pathlib import Path as _Path
        # Limpiar rutas anteriores
        if self._update_watcher.directories():
            self._update_watcher.removePaths(self._update_watcher.directories())
        if self._update_watcher.files():
            self._update_watcher.removePaths(self._update_watcher.files())
        p = _Path(carpeta)
        if p.exists():
            self._update_watcher.addPath(str(p))
            version_file = p / "version.json"
            if version_file.exists():
                self._update_watcher.addPath(str(version_file))

    def _on_update_folder_changed(self, path: str) -> None:
        """Llamado por QFileSystemWatcher cuando cambia la carpeta compartida."""
        # Pequeño delay para que el archivo termine de escribirse
        QTimer.singleShot(3000, self._check_update_and_schedule)

    def _tareas_periodicas(self) -> None:
        now = datetime.now()

        # Backup Excel día 24
        if now.day == 24:
            try:
                self.bridge.controller.backup_reporte_general_mensual()
            except Exception:
                pass

        # Backup JSON mensual el día 24 también
        if now.day == 24:
            try:
                periodo = now.strftime("%Y-%m")
                self.bridge.controller.backup_datos_mes(periodo)
            except Exception:
                pass

        # Auto-comparativo último día del mes
        if _is_last_day_of_month():
            try:
                self.bridge.controller.auto_comparar_mes_actual()
            except Exception:
                pass

    def _check_update_and_schedule(self) -> None:
        """Verifica actualizaciones y notifica al JS si hay una nueva versión."""
        try:
            result = self.bridge.controller.check_actualizacion()
            if result.get("hay_actualizacion"):
                payload = json.dumps(result, ensure_ascii=False, default=str)
                js = f"window.notificarActualizacion && window.notificarActualizacion({payload});"
                self.web_view.page().runJavaScript(js)
        except Exception:
            pass

        # Reagendar: cada 4 horas
        self._timer_update.setSingleShot(True)
        self._timer_update.timeout.disconnect()
        self._timer_update.timeout.connect(self._check_update_and_schedule)
        self._timer_update.start(4 * 60 * 60 * 1000)
