from __future__ import annotations

import html as html_module
import re
from datetime import datetime
from typing import Any, Dict, List


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = value.strip().replace(",", "")
    if not raw.isdigit():
        return None
    return int(raw)


def _match_first(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def _clean_serial_number(serial: str | None) -> str | None:
    """Limpia y normaliza el número de serie."""
    if not serial:
        return None
    # Remover espacios, tabs, y caracteres especiales comunes
    serial = serial.strip().upper()
    # Permitir solo alfanuméricos, guiones, punto y / (común en seriales)
    serial = re.sub(r"[^A-Z0-9\-./]", "", serial)
    # Remover espacios internos que pudieran haber quedado
    serial = serial.replace(" ", "")
    return serial if serial else None


def _parse_date(raw: str | None) -> str | None:
    if not raw:
        return None

    # Example: Tue 24 Mar 2026 12:51:55
    candidates = [
        "%a %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(raw.strip(), fmt).isoformat(sep=" ", timespec="seconds")
        except ValueError:
            continue
    return None


def _extract_total(block_title: str, text: str) -> int | None:
    lines = text.splitlines()
    start = -1
    label = f"{block_title.strip().lower()}:"

    for idx, line in enumerate(lines):
        if line.strip().lower() == label:
            start = idx + 1
            break

    if start < 0:
        return None

    for idx in range(start, len(lines)):
        current = lines[idx].strip()
        if not current:
            continue

        total_match = re.match(r"^Total:\s*(\d+)\s*$", current, re.IGNORECASE)
        if total_match:
            return _to_int(total_match.group(1))

        # End current block on next section title (e.g. "Scanned Pages:").
        if current.endswith(":") and not re.search(r"\d", current):
            break

    return None


def _extract_simple_counter(label: str, text: str) -> int | None:
    pattern = rf"^\\s*{re.escape(label)}:\\s*(\\d+)\\s*$"
    return _to_int(_match_first(pattern, text))


def _extract_toner_black_pct(text: str) -> int | None:
    values = re.findall(r"^\s*black:\s*(\d+)%\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not values:
        return None
    return _to_int(values[0])


def _extract_events(text: str) -> List[Dict[str, str]]:
    events: List[Dict[str, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        ts_match = re.match(r"^<([^>]+)>$", line)
        if not ts_match:
            i += 1
            continue

        timestamp_raw = ts_match.group(1).strip()
        i += 1
        while i < len(lines):
            event_line = lines[i].strip()
            if not event_line:
                i += 1
                break
            if re.match(r"^<[^>]+>$", event_line):
                break
            if event_line.lower().startswith("black:"):
                i += 1
                continue

            state = None
            desc = event_line
            if event_line.startswith("[*]"):
                state = "ON"
                desc = event_line[3:].strip()
            elif event_line.startswith("[ ]"):
                state = "OFF"
                desc = event_line[3:].strip()

            events.append(
                {
                    "timestamp_raw": timestamp_raw,
                    "state": state or "INFO",
                    "description": desc,
                }
            )
            i += 1

    return events


def _html_to_text(raw_html: str) -> str:
    text = raw_html.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|th|td|h\d)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_meter_email_text(raw_text: str) -> Dict[str, Any]:
    text = (raw_text or "").replace("\r\n", "\n")
    if re.search(r"<\s*[^>]+>", text):
        text = _html_to_text(text)

    model_name = _match_first(r"^\s*Model Name:\s*(.+)$", text)
    serial_number_raw = _match_first(r"^\s*Serial Number:\s*(.+)$", text)
    serial_number = _clean_serial_number(serial_number_raw)
    meter_date_raw = _match_first(r"^\s*MeterDate:\s*(.+)$", text)

    office_hint = _match_first(r"^\s*(KY-[A-Z0-9_\-/]+)\s*$", text, re.IGNORECASE | re.MULTILINE)

    parsed = {
        "model_name": model_name,
        "serial_number": serial_number,
        "serial_number_raw": serial_number_raw,
        "meter_date_raw": meter_date_raw,
        "meter_date": _parse_date(meter_date_raw),
        "printed_total": _extract_total("Printed Pages", text),
        "scanned_total": _extract_total("Scanned Pages", text),
        "duplex_total": _extract_total("Counters by Duplex", text),
        "duplex_1sided": _extract_simple_counter("1-sided", text),
        "duplex_2sided": _extract_simple_counter("2-sided", text),
        "combine_total": _extract_total("Counters by Combine", text),
        "toner_black_pct": _extract_toner_black_pct(text),
        "office_hint": office_hint,
        "events": _extract_events(text),
    }

    # Effective total uses printed pages as the most practical page counter in these mails.
    parsed["contador_efectivo"] = parsed["printed_total"]

    return parsed
