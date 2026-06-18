from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class PrintRecord:
    fecha: date
    usuario: str
    oficina: str
    ciudad: Optional[str]
    impresora: str
    numero_serie: str
    tipo_documento: str
    paginas: int
    contador_actual: Optional[int]
    tipo_impresion: str
    modelo: str = "M3655idn"
