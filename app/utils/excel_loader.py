from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


COLUMN_ALIASES = {
    "fecha": "fecha",
    "usuario": "usuario",
    "oficina": "oficina",
    "ciudad": "ciudad",
    "impresora": "impresora",
    "numero de serie": "numero_serie",
    "número de serie": "numero_serie",
    "tipo de documento": "tipo_documento",
    "cantidad de paginas": "paginas",
    "cantidad de páginas": "paginas",
    "contador actual": "contador_actual",
    "tipo de impresion": "tipo_impresion",
    "tipo de impresión": "tipo_impresion",
    "modelo": "modelo",
}

REQUIRED_COLUMNS = ["fecha", "usuario", "oficina", "impresora", "numero_serie", "paginas"]

# Layout expected from the provider report shown by the user.
PROVIDER_ORDER = [
    "source.name",
    "nombre del modelo",
    "numero del serie",
    "ubicacion",
    "direccion 1",
    "estado",
    "observaciones",
    "direccion",
    "contacto",
    "fecha/hora (obtener datos)",
    "total contador",
    "blanco y negro total",
    "total a todo color",
]

# Allowed header variants in each fixed column position.
PROVIDER_POSITION_RULES = [
    ("source.name",),
    ("nombre del modelo",),
    ("numero del seri", "numero de seri", "nro de serie", "numero de serie"),
    ("ubicacion",),
    ("direccion 1", "direccion1", "direccion ip", "ip"),
    ("estado",),
    ("observaciones",),
    ("direccion",),
    ("contacto",),
    ("fecha/hora (obtener datos)", "fecha hora (obtener datos)", "fecha/hora"),
    ("total contador",),
    ("blanco y negro total", "blanco negro total", "bn total"),
    ("total a todo color", "total color"),
]


def _normalize_column_name(name: str) -> str:
    return name.strip().lower().replace("_", " ")


def _remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_for_compare(name: str) -> str:
    value = _normalize_column_name(name)
    value = _remove_accents(value)
    value = " ".join(value.split())
    return value


def _normalize_tipo_impresion(value: str) -> str:
    if not value:
        return "BN"
    value = str(value).strip().lower()
    return "Color" if value in {"color", "colour", "c"} else "BN"


def _is_provider_layout(df: pd.DataFrame) -> bool:
    if len(df.columns) < len(PROVIDER_ORDER):
        return False
    first = _normalize_for_compare(str(df.columns[0]))
    second = _normalize_for_compare(str(df.columns[1])) if len(df.columns) > 1 else ""
    return first == "source.name" and second == "nombre del modelo"


def _is_kfs_layout(df: pd.DataFrame) -> bool:
    """Detects KFS report format: starts with 'Nombre del modelo', 'Número de serie'."""
    if len(df.columns) < 7:
        return False
    first = _normalize_for_compare(str(df.columns[0]))
    second = _normalize_for_compare(str(df.columns[1]))
    return first == "nombre del modelo" and "serie" in second


def _find_kfs_header_row(raw_df: pd.DataFrame, scan_rows: int = 10) -> Optional[int]:
    """Scans first rows looking for a KFS header (title row may precede the real header)."""
    limit = min(scan_rows, len(raw_df))
    for idx in range(limit):
        row = [_normalize_for_compare(str(v)) for v in raw_df.iloc[idx].tolist()]
        if len(row) >= 2 and row[0] == "nombre del modelo" and "serie" in row[1]:
            return idx
    return None


def _read_kfs_records(df: pd.DataFrame) -> List[Dict]:
    """Parses KFS sheet: Nombre del modelo, Número de serie, Ubicación, Dirección IP,
    Dirección, Contacto, Fecha/hora (obtener datos), Total Contador."""
    records: List[Dict] = []
    for _, row in df.fillna("").iterrows():
        fecha = _parse_provider_datetime(row.iloc[6])
        if pd.isna(fecha):
            continue
        modelo = str(row.iloc[0]).strip() or "M3655idn"
        numero_serie = str(row.iloc[1]).strip()
        if not numero_serie or numero_serie.lower() == "nan":
            continue
        oficina = str(row.iloc[2]).strip() or "Sin oficina"
        ciudad = str(row.iloc[4]).strip() or None
        usuario = str(row.iloc[5]).strip() or "Sistema"
        total_contador = _to_int(row.iloc[7]) if len(row) > 7 else 0

        records.append({
            "fecha": fecha.date(),
            "usuario": usuario,
            "oficina": oficina,
            "ciudad": ciudad,
            "impresora": modelo,
            "numero_serie": numero_serie,
            "tipo_documento": "Reporte contador",
            "paginas": total_contador,
            "contador_actual": total_contador,
            "tipo_impresion": "BN",
            "modelo": modelo,
        })
    if not records:
        raise ValueError("No se encontraron filas válidas en la hoja KFS (fecha vacía o inválida).")
    return records


def _find_provider_header_row(raw_df: pd.DataFrame, scan_rows: int = 12) -> Optional[int]:
    limit = min(scan_rows, len(raw_df))
    for idx in range(limit):
        row_values = [
            _normalize_for_compare(str(value))
            for value in raw_df.iloc[idx].tolist()
        ]
        if len(row_values) < 2:
            continue
        if row_values[0] == "source.name" and row_values[1] == "nombre del modelo":
            return idx
    return None


def _validate_provider_order(df: pd.DataFrame) -> None:
    current = [_normalize_for_compare(str(c)) for c in list(df.columns)[: len(PROVIDER_POSITION_RULES)]]
    invalid_positions = []

    for idx, current_name in enumerate(current):
        allowed_prefixes = tuple(_normalize_for_compare(v) for v in PROVIDER_POSITION_RULES[idx])
        if not any(current_name.startswith(prefix) for prefix in allowed_prefixes):
            invalid_positions.append((idx + 1, current_name, PROVIDER_POSITION_RULES[idx]))

    if invalid_positions:
        details = "; ".join(
            f"columna {pos}='{actual}' (esperado parecido a {allowed})"
            for pos, actual, allowed in invalid_positions
        )
        raise ValueError(
            "El orden de columnas del Excel no coincide con la plantilla requerida.\n"
            f"Detalle: {details}\n"
            f"Esperado: {PROVIDER_ORDER}"
        )


def _to_int(value: object) -> int:
    text = str(value).strip().replace(",", "")
    if text == "" or text.lower() == "nan":
        return 0
    return int(float(text))


def _parse_provider_datetime(value: object):
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return pd.NaT

    # Provider files usually use dd/mm/yyyy-HH:MM:SS.
    parsed = pd.to_datetime(text, format="%d/%m/%Y-%H:%M:%S", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return parsed


def _read_provider_records(df: pd.DataFrame) -> List[Dict]:
    _validate_provider_order(df)

    records: List[Dict] = []
    for _, row in df.fillna("").iterrows():
        fecha = _parse_provider_datetime(row.iloc[9])
        if pd.isna(fecha):
            continue

        modelo = str(row.iloc[1]).strip() or "M3655idn"
        numero_serie = str(row.iloc[2]).strip()
        oficina = str(row.iloc[3]).strip() or "Sin oficina"
        ciudad = str(row.iloc[7]).strip() or None
        usuario = str(row.iloc[8]).strip() or "Sistema"
        total_contador = _to_int(row.iloc[10])
        total_bn = _to_int(row.iloc[11])
        total_color = _to_int(row.iloc[12])

        tipo_impresion = "Color" if total_color > 0 else "BN"
        paginas = total_contador if total_contador > 0 else (total_bn + total_color)

        records.append(
            {
                "fecha": fecha.date(),
                "usuario": usuario,
                "oficina": oficina,
                "ciudad": ciudad,
                "impresora": modelo,
                "numero_serie": numero_serie,
                "tipo_documento": "Reporte contador",
                "paginas": paginas,
                "contador_actual": total_contador,
                "tipo_impresion": tipo_impresion,
                "modelo": modelo,
            }
        )
    if not records:
        raise ValueError("No se encontraron filas validas en el Excel (fecha vacia o invalida).")

    return records


def _read_standard_records(df: pd.DataFrame) -> List[Dict]:
    mapped_columns = {}
    for col in df.columns:
        normalized = _normalize_column_name(str(col))
        mapped_columns[col] = COLUMN_ALIASES.get(normalized, normalized.replace(" ", "_"))

    df = df.rename(columns=mapped_columns)

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"Falta la columna requerida: {col}")

    df = df.fillna("")
    records: List[Dict] = []

    for _, row in df.iterrows():
        fecha = pd.to_datetime(row["fecha"], errors="coerce")
        if pd.isna(fecha):
            continue

        paginas = int(row.get("paginas", 0) or 0)
        contador_actual = row.get("contador_actual", None)
        contador_actual = int(contador_actual) if str(contador_actual).strip() else None

        record = {
            "fecha": fecha.date(),
            "usuario": str(row.get("usuario", "")).strip(),
            "oficina": str(row.get("oficina", "")).strip(),
            "ciudad": str(row.get("ciudad", "")).strip() or None,
            "impresora": str(row.get("impresora", "")).strip(),
            "numero_serie": str(row.get("numero_serie", "")).strip(),
            "tipo_documento": str(row.get("tipo_documento", "Otro")).strip() or "Otro",
            "paginas": paginas,
            "contador_actual": contador_actual,
            "tipo_impresion": _normalize_tipo_impresion(str(row.get("tipo_impresion", "BN"))),
            "modelo": str(row.get("modelo", "M3655idn")).strip() or "M3655idn",
        }
        records.append(record)

    return records


def read_excel_records(file_path: Path) -> List[Dict]:
    workbook = pd.read_excel(file_path, sheet_name=None)
    all_records: List[Dict] = []
    parse_errors: List[str] = []

    for sheet_name, df in workbook.items():
        try:
            if _is_provider_layout(df):
                all_records.extend(_read_provider_records(df))
                continue

            if _is_kfs_layout(df):
                all_records.extend(_read_kfs_records(df))
                continue

            # Try to detect layouts when header is not in first row.
            raw_df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

            header_idx = _find_provider_header_row(raw_df)
            if header_idx is not None:
                shifted_df = pd.read_excel(file_path, sheet_name=sheet_name, header=header_idx)
                all_records.extend(_read_provider_records(shifted_df))
                continue

            kfs_idx = _find_kfs_header_row(raw_df)
            if kfs_idx is not None:
                shifted_df = pd.read_excel(file_path, sheet_name=sheet_name, header=kfs_idx)
                all_records.extend(_read_kfs_records(shifted_df))
                continue

            all_records.extend(_read_standard_records(df))
        except Exception as exc:
            parse_errors.append(f"{sheet_name}: {exc}")

    if not all_records and parse_errors:
        raise ValueError("No se pudieron leer hojas del Excel. " + " | ".join(parse_errors[:3]))

    return all_records
