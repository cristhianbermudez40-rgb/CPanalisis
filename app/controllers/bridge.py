from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from app.controllers.print_controller import PrintController


class _ImportWorker(QThread):
    """Runs IMAP import in a background thread so the Qt event loop stays responsive."""
    finished = Signal(str)

    def __init__(self, controller: PrintController, kwargs: dict) -> None:
        super().__init__()
        self._controller = controller
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            payload = self._controller.importar_lecturas_desde_correo(**self._kwargs)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error importando lecturas por correo: {exc}"}
        self.finished.emit(json.dumps(payload, ensure_ascii=False, default=str))


class AppBridge(QObject):
    # Emitted when the background IMAP import completes; carries the JSON result string.
    importacionLista = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.controller = PrintController()
        self._importing: bool = False
        self._current_worker: _ImportWorker | None = None

    def _on_import_done(self) -> None:
        self._importing = False
        self._current_worker = None

    def cleanup(self) -> None:
        """Detiene el hilo IMAP si sigue corriendo al cerrar la app."""
        if self._current_worker is not None and self._current_worker.isRunning():
            self._current_worker.quit()
            self._current_worker.wait(3000)   # espera máximo 3 segundos
            self._current_worker = None
        self._importing = False

    @staticmethod
    def _json_default(value):
        if isinstance(value, Decimal):
            # Keep integers as int and fractional values as float for JS charts/tables.
            return int(value) if value == value.to_integral_value() else float(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)

    def _to_json(self, payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, default=self._json_default)

    @Slot(str, str, result=str)
    def iniciarSesion(self, username: str, password: str) -> str:
        try:
            payload = self.controller.autenticar_acceso(username, password)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error de autenticacion: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def validarAdmin(self, admin_password: str) -> str:
        try:
            payload = self.controller.validar_admin(admin_password)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error validando admin: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def actualizarCredenciales(self, user: str, user_password: str, admin_password: str) -> str:
        try:
            payload = self.controller.actualizar_credenciales(user, user_password, admin_password)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error actualizando credenciales: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def openExcelDialog(self) -> str:
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Seleccionar archivo Excel",
            "",
            "Excel Files (*.xlsx *.xls)",
        )
        return file_path or ""

    @Slot(result=str)
    def openFolderDialog(self) -> str:
        folder_path = QFileDialog.getExistingDirectory(
            None,
            "Seleccionar carpeta con archivos Excel",
            "",
        )
        return folder_path or ""

    @Slot(str, result=str)
    def cargarExcel(self, file_path: str) -> str:
        try:
            safe_path = str(file_path).strip()
            if not safe_path or safe_path == ".":
                return self._to_json({"ok": False, "mensaje": "Ruta de archivo invalida"})

            source = Path(safe_path)
            if not source.exists() or not source.is_file():
                return self._to_json({"ok": False, "mensaje": "El archivo no existe o no es valido"})

            payload = self.controller.cargar_excel(safe_path)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error cargando Excel: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def cargarExcelMasivo(self, folder_path: str) -> str:
        try:
            safe_path = str(folder_path).strip()
            if not safe_path or safe_path == ".":
                return self._to_json({"ok": False, "mensaje": "Ruta de carpeta invalida"})

            source = Path(safe_path)
            if not source.exists() or not source.is_dir():
                return self._to_json({"ok": False, "mensaje": "La carpeta no existe o no es valida"})

            payload = self.controller.cargar_excel_masivo(safe_path)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error en carga masiva: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def limpiarRegistros(self) -> str:
        try:
            payload = self.controller.limpiar_registros()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error limpiando registros: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def reiniciarContadorAnalisis(self) -> str:
        try:
            payload = self.controller.reiniciar_contador_analisis()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error reiniciando analisis: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def generarEstadisticas(self) -> str:
        try:
            payload = self.controller.generar_estadisticas()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error generando estadisticas: {exc}"}
        return self._to_json(payload)

    @Slot(str, int, int, result=str)
    def compararContadores(self, numero_serie: str, contador_proveedor: int, contador_maquina: int) -> str:
        try:
            payload = self.controller.comparar_contadores(numero_serie, contador_proveedor, contador_maquina)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error comparando contadores: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, int, result=str)
    def compararContadoresMensual(self, numero_serie: str, periodo: str, contador_proveedor: int) -> str:
        try:
            payload = self.controller.comparar_contadores_mensual(numero_serie, periodo, contador_proveedor)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error comparando contadores por mes: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def generarReporteMensual(self, numero_serie: str, periodo_a: str, periodo_b: str) -> str:
        try:
            payload = self.controller.generar_reporte_mensual(numero_serie, periodo_a, periodo_b)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error generando reporte: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def exportarReporteExcel(self, numero_serie: str, periodo_a: str, periodo_b: str) -> str:
        try:
            output = self.controller.exportar_reporte_excel(numero_serie, periodo_a, periodo_b)
            payload = {"ok": True, "archivo": output}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error exportando Excel: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def exportarReportePDF(self, numero_serie: str, periodo_a: str, periodo_b: str) -> str:
        try:
            output = self.controller.exportar_reporte_pdf(numero_serie, periodo_a, periodo_b)
            payload = {"ok": True, "archivo": output}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error exportando PDF: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def generarReporteGeneral(self, periodo: str) -> str:
        try:
            payload = self.controller.generar_reporte_general_oficinas(periodo)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error generando reporte general: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def exportarReporteGeneralExcel(self, periodo: str) -> str:
        try:
            output = self.controller.exportar_reporte_general_excel(periodo)
            payload = {"ok": True, "archivo": output}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error exportando reporte general Excel: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def exportarReporteGeneralPDF(self, periodo: str) -> str:
        try:
            output = self.controller.exportar_reporte_general_pdf(periodo)
            payload = {"ok": True, "archivo": output}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error exportando reporte general PDF: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def backupReporteGeneralMensual(self) -> str:
        try:
            payload = self.controller.backup_reporte_general_mensual()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error generando backup: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def consultarContadoresIP(self, ip: str) -> str:
        try:
            payload = self.controller.consultar_contadores_ip(ip)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error al consultar impresora: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def consultarContadoresCorreo(self, serial: str, email_user: str = "", email_password: str = "") -> str:
        try:
            payload = self.controller.consultar_contadores_correo(
                serial, 
                email_user=email_user or "",
                email_password=email_password or ""
            )
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error consultando por correo: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, str, str, str, result=str)
    def registrarImpresoraIP(self, nombre: str, oficina: str, ip: str, numero_serie: str, modelo: str, canal: str = "") -> str:
        try:
            payload = self.controller.registrar_impresora_ip(nombre, oficina, ip, numero_serie, modelo, canal=canal)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error registrando impresora: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def cargarImpresorasLote(self, json_impresoras: str) -> str:
        """Carga múltiples impresoras de una lista JSON."""
        try:
            import json as json_lib
            impresoras_lista = json_lib.loads(json_impresoras)
            if not isinstance(impresoras_lista, list):
                raise ValueError("Se esperaba una lista de impresoras")
            payload = self.controller.cargar_impresoras_lote(impresoras_lista)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error cargando impresoras: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def listarImpresorasIP(self) -> str:
        try:
            payload = {"ok": True, "impresoras": self.controller.listar_impresoras_ip()}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando impresoras: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def abrirMailto(self, url: str) -> str:
        try:
            QDesktopServices.openUrl(QUrl(url))
            return self._to_json({"ok": True})
        except Exception as exc:
            return self._to_json({"ok": False, "mensaje": str(exc)})

    @Slot(result=str)
    def cargarImpresorasBase(self) -> str:
        try:
            payload = self.controller.cargar_impresoras_base()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error cargando impresoras base: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def eliminarImpresoraIP(self, numero_serie: str) -> str:
        try:
            payload = self.controller.eliminar_impresora_ip(numero_serie)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error eliminando impresora: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def historialLecturasIP(self, numero_serie: str) -> str:
        try:
            payload = {"ok": True, "historial": self.controller.historial_lecturas_ip(numero_serie)}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error obteniendo historial: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, str, str, str, bool, int, result=str)
    def importarLecturasCorreo(
        self,
        email_user: str,
        email_password: str,
        imap_host: str,
        folder: str,
        sender_filter: str,
        subject_filter: str,
        only_unseen: bool,
        max_messages: int,
    ) -> str:
        """Launches IMAP import in a background thread and returns immediately.
        The JS side should listen for the `importacionLista` signal for the actual result."""
        try:
            if self._importing:
                return self._to_json({"ok": False, "mensaje": "Ya hay una importación en curso, espera que finalice."})
            self._importing = True
            kwargs = dict(
                email_user=email_user,
                email_password=email_password,
                imap_host=imap_host,
                folder=folder,
                sender_filter=sender_filter,
                subject_filter=subject_filter,
                only_unseen=bool(only_unseen),
                max_messages=max_messages,
            )
            worker = _ImportWorker(self.controller, kwargs)
            self._current_worker = worker
            worker.finished.connect(self.importacionLista)
            worker.finished.connect(self._on_import_done)
            worker.finished.connect(worker.deleteLater)
            worker.start()
            return self._to_json({"ok": True, "en_proceso": True})
        except Exception as exc:
            self._importing = False
            return self._to_json({"ok": False, "mensaje": f"Error iniciando importación: {exc}"})

    @Slot(int, result=str)
    def listarLecturasCorreo(self, limit: int) -> str:
        try:
            payload = {"ok": True, "lecturas": self.controller.listar_lecturas_email(limit)}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando lecturas de correo: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, str, result=str)
    def procesarCorreosLocales(self, carpeta_entrada: str, carpeta_archivo: str, patron: str) -> str:
        try:
            payload = self.controller.procesar_correos_locales(
                carpeta_entrada=carpeta_entrada or "",
                carpeta_archivo=carpeta_archivo or "",
                patron=patron or "*.txt",
            )
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error procesando correos locales: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def procesarCorreoArchivo(self, archivo_ruta: str) -> str:
        try:
            payload = self.controller.procesar_correo_archivo(archivo_ruta)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error procesando archivo: {exc}"}
        return self._to_json(payload)

    @Slot(str, str, result=str)
    def diagnosticarArchivosCorreos(self, carpeta: str, patron: str) -> str:
        try:
            payload = self.controller.diagnosticar_archivos_correos(
                carpeta=carpeta or "",
                patron=patron or "*.txt,*.htm,*.html",
            )
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error diagnosticando archivos: {exc}"}
        return self._to_json(payload)

    @Slot(int, result=str)
    def listarSerialessEnBD(self, limit: int) -> str:
        try:
            payload = self.controller.listar_seriales_en_bd(limit=limit or 100)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando seriales: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def crearNuevaBaseDatos(self, config_json: str) -> str:
        try:
            import json as _json
            cfg = _json.loads(config_json)
            payload = self.controller.setup_nueva_bd(
                host=cfg.get("host", "127.0.0.1"),
                port=int(cfg.get("port", 3306)),
                user=cfg.get("user", "root"),
                password=cfg.get("password", ""),
                db_name=cfg.get("db_name", "print_analytics"),
            )
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error creando base de datos: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def autoCompararMesActual(self) -> str:
        try:
            payload = self.controller.auto_comparar_mes_actual()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error en auto-comparativo: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def listarComparativosPeriodo(self, periodo: str) -> str:
        try:
            rows = self.controller.listar_comparativos_periodo(periodo)
            payload = {"ok": True, "comparativos": rows}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando comparativos: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def listarPeriodosComparativos(self) -> str:
        try:
            periodos = self.controller.listar_periodos_comparativos()
            payload = {"ok": True, "periodos": periodos}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando periodos: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def obtenerHistoricoImpresora(self, serial: str) -> str:
        try:
            payload = self.controller.obtener_historico_impresora(serial)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error obteniendo historial: {exc}"}
        return self._to_json(payload)

    @Slot(bool, result=str)
    def sincronizarMantenimientos(self, regenerar: bool) -> str:
        """Sincroniza mantenimientos calculados a la BD.

        Args:
            regenerar: Si true, elimina y recalcula todos. Si false, solo agrega nuevos.

        Returns:
            JSON: {ok, mensaje, generados, existentes, total}
        """
        try:
            payload = self.controller.sincronizar_mantenimientos(regenerar=regenerar)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error sincronizando mantenimientos: {exc}"}
        return self._to_json(payload)

    # ── Backups mensuales ──────────────────────────────────────────────────
    @Slot(str, result=str)
    def backupDatosMes(self, periodo: str) -> str:
        try:
            payload = self.controller.backup_datos_mes(periodo or None)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error en backup: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def listarBackups(self) -> str:
        try:
            payload = self.controller.listar_backups()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando backups: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def cargarDatosBackup(self, periodo: str) -> str:
        try:
            payload = self.controller.cargar_datos_backup(periodo)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error cargando backup: {exc}"}
        return self._to_json(payload)

    @Slot(str, result=str)
    def sincronizarBackupARed(self, periodo: str) -> str:
        try:
            payload = self.controller.sincronizar_backup_a_red(periodo or None)
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error sincronizando: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def listarBackupsRed(self) -> str:
        try:
            payload = self.controller.listar_backups_red()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error listando backups de red: {exc}"}
        return self._to_json(payload)

    @Slot(result=str)
    def obtenerEstadisticasMensuales(self) -> str:
        try:
            payload = self.controller.obtener_estadisticas_mensuales()
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error obteniendo estadísticas: {exc}"}
        return self._to_json(payload)

    # ── Actualizaciones ────────────────────────────────────────────────────
    @Slot(result=str)
    def checkActualizacion(self) -> str:
        try:
            payload = self.controller.check_actualizacion()
        except Exception as exc:
            payload = {"ok": False, "hay_actualizacion": False, "mensaje": str(exc)}
        return self._to_json(payload)

    @Slot(result=str)
    def obtenerUpdateFolder(self) -> str:
        import os
        from app.config import APP_CONFIG
        carpeta = (os.environ.get("UPDATE_FOLDER") or APP_CONFIG.update_folder or "").strip()
        return self._to_json({"ok": True, "carpeta": carpeta})

    @Slot(str, result=str)
    def configurarUpdateFolder(self, carpeta: str) -> str:
        try:
            payload = self.controller.configurar_update_folder(carpeta)
            # Notificar a la ventana principal para que reconfigure el watcher
            win = self.parent()
            if win and hasattr(win, "_reconfigura_watcher"):
                win._reconfigura_watcher(carpeta)
        except Exception as exc:
            payload = {"ok": False, "mensaje": str(exc)}
        return self._to_json(payload)

    @Slot(result=str)
    def instalarActualizacion(self) -> str:
        try:
            payload = self.controller.instalar_actualizacion()
            if payload.get("ok"):
                # Cierra la app tras 2 s para que el bat pueda capturar el PID
                from PySide6.QtCore import QTimer
                from PySide6.QtWidgets import QApplication
                QTimer.singleShot(2000, QApplication.quit)
        except Exception as exc:
            payload = {"ok": False, "mensaje": str(exc)}
        return self._to_json(payload)

    @Slot(result=str)
    def obtenerMantenimientosVigentes(self) -> str:
        try:
            mantenimientos = self.controller.obtener_mantenimientos_vigentes()
            if not mantenimientos:
                # Auto-sincronizar si la tabla está vacía
                self.controller.sincronizar_mantenimientos(regenerar=True)
                mantenimientos = self.controller.obtener_mantenimientos_vigentes()
            payload = {"ok": True, "mantenimientos": mantenimientos}
        except Exception as exc:
            payload = {"ok": False, "mensaje": f"Error obteniendo mantenimientos: {exc}"}
        return self._to_json(payload)
