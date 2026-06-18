from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Dict

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from app.config import APP_CONFIG

# Brand colors
MAGENTA = colors.HexColor("#E83C6C")
NAVY    = colors.HexColor("#1A2B4A")
BLUE    = colors.HexColor("#0055A4")
LIGHT   = colors.HexColor("#F4F7FB")
WHITE   = colors.white
GRAY    = colors.HexColor("#64748B")
GREEN   = colors.HexColor("#00A86B")
RED     = colors.HexColor("#E83C6C")


def _fmt(value, is_num: bool = False) -> str:
    if value is None:
        return "—"
    if is_num:
        try:
            return f"{int(value):,}".replace(",", ".")
        except (ValueError, TypeError):
            return str(value)
    return str(value)


class ReportService:
    def __init__(self) -> None:
        APP_CONFIG.report_dir.mkdir(parents=True, exist_ok=True)

    def export_to_excel(self, report_data: Dict, filename: str) -> str:
        output_path = APP_CONFIG.report_dir / filename
        rows = report_data.get("comparativo", [])
        delta = report_data.get("delta", {})

        df_comp = pd.DataFrame(rows)
        # Rename columns for clarity
        rename = {
            "periodo": "Periodo", "oficina": "Oficina", "ciudad": "Ciudad",
            "impresora": "Impresora", "numero_serie": "Numero Serie",
            "volumen": "Total Paginas", "paginas_mono": "Mono",
            "paginas_color": "Color", "ultimo_contador": "Ultimo Contador",
            "primer_contador": "Primer Contador", "dias_activos": "Dias Activos",
            "total_trabajos": "Total Trabajos",
        }
        df_comp.rename(columns={k: v for k, v in rename.items() if k in df_comp.columns}, inplace=True)

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_comp.to_excel(writer, sheet_name="Comparativo", index=False)
            if delta:
                df_delta = pd.DataFrame([{
                    "Descripcion": "Volumen " + report_data.get("periodo_a", "A"),
                    "Valor": delta.get("volumen_a"),
                }, {
                    "Descripcion": "Volumen " + report_data.get("periodo_b", "B"),
                    "Valor": delta.get("volumen_b"),
                }, {
                    "Descripcion": "Variacion de Paginas",
                    "Valor": delta.get("variacion"),
                }, {
                    "Descripcion": "% Cambio",
                    "Valor": f"{delta.get('porcentaje_cambio', 0)}%",
                }, {
                    "Descripcion": "Tendencia",
                    "Valor": delta.get("tendencia"),
                }, {
                    "Descripcion": "Ultimo Contador " + report_data.get("periodo_a", "A"),
                    "Valor": delta.get("contador_a"),
                }, {
                    "Descripcion": "Ultimo Contador " + report_data.get("periodo_b", "B"),
                    "Valor": delta.get("contador_b"),
                }, {
                    "Descripcion": "Variacion Contador",
                    "Valor": delta.get("variacion_contador"),
                }])
                df_delta.to_excel(writer, sheet_name="Resumen Delta", index=False)

        return str(output_path)

    def export_to_pdf(self, report_data: Dict, filename: str) -> str:
        output_path = APP_CONFIG.report_dir / filename
        serial      = report_data.get("serial", "—")
        periodo_a   = report_data.get("periodo_a", "—")
        periodo_b   = report_data.get("periodo_b", "—")
        rows        = report_data.get("comparativo", [])
        delta       = report_data.get("delta", {})

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title", parent=styles["Heading1"],
            textColor=NAVY, fontSize=20, spaceAfter=4, fontName="Helvetica-Bold",
        )
        sub_style = ParagraphStyle(
            "Sub", parent=styles["Normal"],
            textColor=GRAY, fontSize=10, spaceAfter=2,
        )
        label_style = ParagraphStyle(
            "Label", parent=styles["Normal"],
            textColor=NAVY, fontSize=9, fontName="Helvetica-Bold",
        )
        cell_style = ParagraphStyle(
            "Cell", parent=styles["Normal"],
            textColor=NAVY, fontSize=8, leading=9,
        )

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(letter),
            leftMargin=1.8*cm, rightMargin=1.8*cm,
            topMargin=1.8*cm, bottomMargin=1.8*cm,
        )

        story = []

        # ── Header brand bar ──────────────────────────────────────────
        header_data = [[
            Paragraph(f"<font color='#{NAVY.hexval()[2:]}' size='18'><b>AVISTA</b></font> "
                      f"<font color='#{MAGENTA.hexval()[2:]}'>CPAnálisis</font>", styles["Normal"]),
            Paragraph(
                f"<font size='9' color='#64748B'>Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}</font>",
                styles["Normal"],
            ),
        ]]
        header_tbl = Table(header_data, colWidths=["70%", "30%"])
        header_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT]),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("RIGHTPADDING", (0, 0), (-1, -1), 16),
            ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 0.35*cm))

        story.append(Paragraph(f"Reporte Impresora <b>{serial}</b>", title_style))
        story.append(Paragraph(f"Comparativo: {periodo_a}  vs  {periodo_b}", sub_style))
        story.append(HRFlowable(width="100%", thickness=2, color=MAGENTA, spaceAfter=10))

        # ── Period rows table ─────────────────────────────────────────
        col_headers = [
            "Periodo", "Oficina", "Ciudad", "Impresora",
            "Total Pags", "Mono", "Color",
            "Ultimo Contador", "Días Activos", "Trabajos",
        ]
        tbl_data = [col_headers]
        for r in rows:
            tbl_data.append([
                Paragraph(_fmt(r.get("periodo")), cell_style),
                Paragraph(_fmt(r.get("oficina")), cell_style),
                Paragraph(_fmt(r.get("ciudad")), cell_style),
                Paragraph(_fmt(r.get("impresora")), cell_style),
                _fmt(r.get("volumen"), True),
                _fmt(r.get("paginas_mono"), True),
                _fmt(r.get("paginas_color"), True),
                _fmt(r.get("ultimo_contador"), True),
                _fmt(r.get("dias_activos"), True),
                _fmt(r.get("total_trabajos"), True),
            ])

        # Must fit landscape letter frame (~24.3cm with current margins)
        col_w = [1.5*cm, 2.7*cm, 4.1*cm, 3.3*cm, 1.8*cm, 1.4*cm, 1.4*cm, 2.1*cm, 1.9*cm, 1.9*cm]
        detail_tbl = Table(tbl_data, colWidths=col_w, repeatRows=1)
        detail_tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("FONTSIZE",    (0, 1), (-1, -1), 8),
            ("TEXTCOLOR",   (0, 1), (-1, -1), NAVY),
            ("ALIGN",       (4, 0), (-1, -1), "RIGHT"),
            ("ALIGN",       (0, 0), (3, -1), "LEFT"),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",(0, 0), (-1, -1), 5),
            ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
            ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ]))
        story.append(detail_tbl)
        story.append(Spacer(1, 0.5*cm))

        # ── Delta / verdict section ───────────────────────────────────
        if delta:
            tendencia = delta.get("tendencia", "ESTABLE")
            variacion = delta.get("variacion", 0) or 0
            pct = delta.get("porcentaje_cambio", 0) or 0
            tend_color = GREEN if variacion <= 0 else RED

            story.append(Paragraph("Análisis Comparativo entre Períodos", label_style))
            story.append(Spacer(1, 0.2*cm))

            delta_data = [
                ["Indicador", periodo_a, periodo_b, "Variación", "% Cambio", "Tendencia"],
                [
                    "Total Páginas",
                    _fmt(delta.get("volumen_a"), True),
                    _fmt(delta.get("volumen_b"), True),
                    f"{'+' if variacion >= 0 else ''}{_fmt(variacion, True)}",
                    f"{'+' if pct >= 0 else ''}{pct}%",
                    tendencia,
                ],
                [
                    "Contador Impresora",
                    _fmt(delta.get("contador_a"), True),
                    _fmt(delta.get("contador_b"), True),
                    _fmt(delta.get("variacion_contador"), True),
                    "—", "—",
                ],
            ]

            delta_tbl = Table(delta_data, colWidths=[4.5*cm, 3.5*cm, 3.5*cm, 3.5*cm, 2.8*cm, 2.8*cm])
            delta_tbl.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
                ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
                ("TEXTCOLOR",   (0, 1), (-1, -1), NAVY),
                ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
                ("ALIGN",       (0, 0), (0, -1), "LEFT"),
                ("TOPPADDING",  (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                # Color the tendency cell
                ("TEXTCOLOR",   (5, 1), (5, 1), tend_color),
                ("FONTNAME",    (5, 1), (5, 1), "Helvetica-Bold"),
                ("TEXTCOLOR",   (3, 1), (3, 1), tend_color),
                ("FONTNAME",    (3, 1), (3, 1), "Helvetica-Bold"),
            ]))
            story.append(delta_tbl)
            story.append(Spacer(1, 0.4*cm))

            # Verdict pill
            verdict_label = (
                "↓ REDUCCIÓN DE VOLUMEN — Tendencia favorable"
                if variacion < 0 else
                ("↑ AUMENTO DE VOLUMEN — Revisar uso" if variacion > 0 else "= SIN VARIACIÓN")
            )
            verdict_data = [[Paragraph(
                f"<font color='white'><b>{verdict_label}</b></font>", styles["Normal"]
            )]]
            verdict_tbl = Table(verdict_data, colWidths=["100%"])
            verdict_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), tend_color),
                ("TOPPADDING",    (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING",   (0, 0), (-1, -1), 16),
                ("ROUNDEDCORNERS", [8, 8, 8, 8]),
            ]))
            story.append(verdict_tbl)

        doc.build(story)
        return str(output_path)

    def export_general_to_excel(self, report_data: Dict, filename: str) -> str:
        output_path = APP_CONFIG.report_dir / filename
        resumen = report_data.get("resumen_oficinas", [])
        detalle = report_data.get("detalle_impresoras", [])
        comparativo = report_data.get("resumen_comparativo", [])
        totales = report_data.get("totales", {})

        df_resumen = pd.DataFrame(resumen)
        df_detalle = pd.DataFrame(detalle)
        df_comparativo = pd.DataFrame(comparativo)
        df_totales = pd.DataFrame([
            {"Indicador": "Oficinas", "Valor": totales.get("oficinas", 0)},
            {"Indicador": "Impresoras activas", "Valor": totales.get("impresoras_activas", 0)},
            {"Indicador": "Usuarios activos", "Valor": totales.get("usuarios_activos", 0)},
            {"Indicador": "Total trabajos", "Valor": totales.get("total_trabajos", 0)},
            {"Indicador": "Total paginas", "Valor": totales.get("total_paginas", 0)},
            {"Indicador": "Paginas mono", "Valor": totales.get("paginas_mono", 0)},
            {"Indicador": "Paginas color", "Valor": totales.get("paginas_color", 0)},
            {"Indicador": "Periodo", "Valor": report_data.get("periodo", "GENERAL")},
        ])

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_resumen.to_excel(writer, sheet_name="Resumen Oficinas", index=False)
            df_detalle.to_excel(writer, sheet_name="Detalle Impresoras", index=False)
            if not df_comparativo.empty:
                df_comparativo.to_excel(writer, sheet_name="Comparativo Mensual", index=False)
            df_totales.to_excel(writer, sheet_name="Totales", index=False)

        return str(output_path)

    def export_general_to_pdf(self, report_data: Dict, filename: str) -> str:
        """Exports the general report to PDF using the new email-counter-based data."""
        output_path = APP_CONFIG.report_dir / filename
        periodo = report_data.get("periodo", "GENERAL")
        resumen = report_data.get("resumen_oficinas", [])
        detalle = report_data.get("detalle_impresoras", [])
        totales = report_data.get("totales", {})

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleGeneral", parent=styles["Heading1"],
            textColor=NAVY, fontSize=18, spaceAfter=4, fontName="Helvetica-Bold",
        )
        sub_style = ParagraphStyle(
            "SubGeneral", parent=styles["Normal"],
            textColor=GRAY, fontSize=10, spaceAfter=6,
        )
        section_style = ParagraphStyle(
            "SectionGeneral", parent=styles["Heading2"],
            textColor=BLUE, fontSize=12, spaceAfter=4, fontName="Helvetica-Bold",
        )

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(letter),
            leftMargin=1.6 * cm,
            rightMargin=1.6 * cm,
            topMargin=1.6 * cm,
            bottomMargin=1.6 * cm,
        )

        tbl_style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TEXTCOLOR", (0, 1), (-1, -1), NAVY),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])

        story = []
        story.append(Paragraph("Reporte General de Impresoras", title_style))
        story.append(Paragraph(f"Periodo: {periodo}", sub_style))
        story.append(Paragraph(
            f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} — Fuente: Correos IMAP",
            sub_style,
        ))
        story.append(Spacer(1, 0.3 * cm))

        # ── Resumen por oficina ──────────────────────────────────────────────────
        story.append(Paragraph("Resumen por Oficina", section_style))
        headers = ["Oficina", "Impresoras", "Con correo", "Suma Contadores", "Pág. Excel"]
        table_data = [headers]
        for row in resumen:
            table_data.append([
                _fmt(row.get("oficina")),
                _fmt(row.get("impresoras_total"), True),
                _fmt(row.get("impresoras_con_datos"), True),
                _fmt(row.get("suma_contadores"), True),
                _fmt(row.get("paginas_excel"), True),
            ])
        office_table = Table(
            table_data,
            colWidths=[5.5 * cm, 2.4 * cm, 2.4 * cm, 3.5 * cm, 2.8 * cm],
            repeatRows=1,
        )
        office_table.setStyle(tbl_style)
        story.append(office_table)
        story.append(Spacer(1, 0.4 * cm))

        # ── Detalle por impresora ────────────────────────────────────────────────
        if detalle:
            story.append(Paragraph("Detalle por Impresora", section_style))
            det_headers = ["Oficina", "Impresora", "Serie", "Área / Canal", "Contador Máq.", "Tóner", "Última lectura"]
            det_data = [det_headers]
            for row in detalle:
                area = row.get("area") or ""
                canal = row.get("canal") or "-"
                generic = ["Oficina Interna", "Oficina Comercial", ""]
                label = area if (area and area not in generic) else canal
                cnt = row.get("contador_maquina")
                toner = row.get("toner_pct")
                det_data.append([
                    _fmt(row.get("oficina")),
                    _fmt(row.get("impresora")),
                    _fmt(row.get("numero_serie")),
                    label,
                    _fmt(cnt, True),
                    f"{toner}%" if toner is not None else "—",
                    _fmt(row.get("ultima_lectura")),
                ])
            det_table = Table(
                det_data,
                colWidths=[3.4 * cm, 3.2 * cm, 2.8 * cm, 3.0 * cm, 2.8 * cm, 1.6 * cm, 2.8 * cm],
                repeatRows=1,
            )
            det_table.setStyle(tbl_style)
            story.append(det_table)
            story.append(Spacer(1, 0.4 * cm))

        # ── Totales ──────────────────────────────────────────────────────────────
        totals_data = [
            ["Indicador", "Valor"],
            ["Oficinas", _fmt(totales.get("oficinas"), True)],
            ["Total impresoras", _fmt(totales.get("impresoras_total"), True)],
            ["Con datos de correo", _fmt(totales.get("impresoras_con_datos"), True)],
        ]
        totals_table = Table(totals_data, colWidths=[7.0 * cm, 4.0 * cm])
        totals_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(totals_table)

        doc.build(story)
        return str(output_path)
