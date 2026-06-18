from __future__ import annotations

from app.controllers.print_controller import PrintController


class AnalyticsService:
    def __init__(self) -> None:
        self.controller = PrintController()

    def get_dashboard_payload(self) -> dict:
        return self.controller.generar_estadisticas()
