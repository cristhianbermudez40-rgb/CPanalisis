"""Minimal SNMP v2c reader using raw UDP sockets — sin dependencias externas."""
from __future__ import annotations

import ipaddress
import re
import socket


# ---------- BER encoder ----------

def _ber_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    parts: list[int] = []
    while n:
        parts.append(n & 0xFF)
        n >>= 8
    parts.reverse()
    return bytes([0x80 | len(parts)] + parts)


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(content)) + content


def _ber_int(n: int) -> bytes:
    if n == 0:
        return _tlv(0x02, b"\x00")
    parts: list[int] = []
    while n:
        parts.append(n & 0xFF)
        n >>= 8
    parts.reverse()
    if parts[0] & 0x80:
        parts.insert(0, 0x00)
    return _tlv(0x02, bytes(parts))


def _ber_str(s: bytes) -> bytes:
    return _tlv(0x04, s)


def _ber_null() -> bytes:
    return _tlv(0x05, b"")


def _ber_seq(content: bytes) -> bytes:
    return _tlv(0x30, content)


def _ber_oid(oid_str: str) -> bytes:
    parts = [int(x) for x in oid_str.strip(".").split(".")]
    body = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p == 0:
            body += b"\x00"
        else:
            chunks: list[int] = []
            t = p
            while t:
                chunks.append(t & 0x7F)
                t >>= 7
            chunks.reverse()
            body += bytes([c | 0x80 for c in chunks[:-1]]) + bytes([chunks[-1]])
    return _tlv(0x06, body)


# ---------- BER decoder ----------

def _decode_len(data: bytes, pos: int) -> tuple[int, int]:
    b = data[pos]
    if b < 0x80:
        return b, pos + 1
    n_bytes = b & 0x7F
    return int.from_bytes(data[pos + 1 : pos + 1 + n_bytes], "big"), pos + 1 + n_bytes


def _decode_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    tag = data[pos]
    length, next_pos = _decode_len(data, pos + 1)
    return tag, data[next_pos : next_pos + length], next_pos + length


# ---------- SNMP packet builder ----------

def _build_snmp_get(community: str, oid: str) -> bytes:
    varbind = _ber_seq(_ber_oid(oid) + _ber_null())
    pdu = _tlv(
        0xA0,  # GetRequest-PDU
        _ber_int(1) + _ber_int(0) + _ber_int(0) + _ber_seq(varbind),
    )
    # SNMPv2c: version field = 1
    return _ber_seq(_ber_int(1) + _ber_str(community.encode()) + pdu)


# ---------- SNMP response parser ----------

def _parse_snmp_value(data: bytes) -> int:
    """Extrae el primer valor numerico de un paquete GetResponse BER."""
    _, msg_body, _ = _decode_tlv(data, 0)

    pos = 0
    _, _, pos = _decode_tlv(msg_body, pos)   # version
    _, _, pos = _decode_tlv(msg_body, pos)   # community
    _, pdu_body, _ = _decode_tlv(msg_body, pos)  # GetResponse-PDU

    pos = 0
    _, _, pos = _decode_tlv(pdu_body, pos)             # request-id
    _, err_bytes, pos = _decode_tlv(pdu_body, pos)     # error-status
    error = int.from_bytes(err_bytes, "big")
    if error:
        raise ValueError(f"SNMP error-status: {error}")
    _, _, pos = _decode_tlv(pdu_body, pos)             # error-index
    _, vbl_body, _ = _decode_tlv(pdu_body, pos)        # VarBindList

    _, vb_body, _ = _decode_tlv(vbl_body, 0)           # VarBind
    _, _, vb_pos = _decode_tlv(vb_body, 0)             # skip OID
    tag, val_bytes, _ = _decode_tlv(vb_body, vb_pos)  # value

    # INTEGER=0x02, Counter32=0x41, Gauge32=0x42, TimeTicks=0x43, Counter64=0x46
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46, 0x47):
        return int.from_bytes(val_bytes, "big")
    raise ValueError(f"Tipo SNMP no soportado: 0x{tag:02x}")


# ---------- OIDs utiles ----------

# Printer-MIB estandar (RFC 3805) — contador de vida total
OID_TOTAL_PAGES = "1.3.6.1.2.1.43.10.2.1.4.1.1"
# Kyocera especifico
OID_KYOCERA_TOTAL = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.1"
OID_KYOCERA_MONO  = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.2"
OID_KYOCERA_COLOR = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.3"

# Variantes comunes para total pages en equipos que no exponen indice 1.1
OID_TOTAL_CANDIDATES = [
    "1.3.6.1.2.1.43.10.2.1.4.1.1",
    "1.3.6.1.2.1.43.10.2.1.4.1.2",
    "1.3.6.1.2.1.43.10.2.1.4.1.3",
    OID_KYOCERA_TOTAL,
]


def _snmp_get_first_available(ip: str, oids: list[str], community: str) -> tuple[int | None, str | None]:
    """Retorna el primer OID con respuesta numerica valida."""
    for oid in oids:
        try:
            val = snmp_get(ip, oid, community)
            return val, oid
        except Exception:
            continue
    return None, None


def pjl_pagecount(ip: str, timeout: float = 3.0, port: int = 9100) -> int | None:
    """Consulta contador por PJL (Raw 9100). En muchos equipos coincide con el panel frontal."""
    cmd = b"\x1b%-12345X@PJL INFO PAGECOUNT\r\n\x1b%-12345X\r\n"
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(cmd)
        response = sock.recv(4096)

    text = response.decode("latin-1", errors="ignore")
    match = re.search(r"PAGECOUNT\s*=\s*(\d+)", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Fallback: si no llega formato PAGECOUNT=, intenta extraer numero grande.
    nums = [int(n) for n in re.findall(r"\b\d{4,}\b", text)]
    return max(nums) if nums else None


def _is_tcp_open(ip: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def _http_server_header(ip: str, timeout: float = 2.0) -> str | None:
    try:
        with socket.create_connection((ip, 80), timeout=timeout) as sock:
            sock.settimeout(timeout)
            req = (
                f"HEAD / HTTP/1.1\r\n"
                f"Host: {ip}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii", errors="ignore")
            sock.sendall(req)
            raw = sock.recv(2048).decode("latin-1", errors="ignore")
        for line in raw.splitlines():
            if line.lower().startswith("server:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def diagnose_device(ip: str) -> dict:
    return {
        "ping_hint": "reachable" if _is_tcp_open(ip, 80) or _is_tcp_open(ip, 443) else "unknown",
        "tcp_9100": _is_tcp_open(ip, 9100),
        "tcp_80": _is_tcp_open(ip, 80),
        "tcp_443": _is_tcp_open(ip, 443),
        "server_header": _http_server_header(ip),
    }


# ---------- API publica ----------

def snmp_get(ip: str, oid: str, community: str = "public",
             port: int = 161, timeout: float = 3.0) -> int:
    """Envia un SNMP v2c GET y retorna el valor numerico."""
    packet = _build_snmp_get(community, oid)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (ip, port))
        response, _ = sock.recvfrom(4096)
    return _parse_snmp_value(response)


def consultar_contadores(ip: str, community: str = "public") -> dict:
    """Consulta contadores de paginas via SNMP. Retorna dict con valores.

    Intenta con la comunidad indicada; si falla completamente prueba
    con las comunidades de reserva ('Admin', 'public').
    """
    _FALLBACK = ["Admin", "public", "private"]
    communities_to_try = [community] + [c for c in _FALLBACK if c != community]

    last_err: Exception | None = None
    for comm in communities_to_try:
        resultado: dict[str, int | None] = {}

        total_paginas, total_oid = _snmp_get_first_available(ip, OID_TOTAL_CANDIDATES, comm)
        resultado["total_paginas"] = total_paginas

        try:
            resultado["kyocera_total"] = snmp_get(ip, OID_KYOCERA_TOTAL, comm)
        except Exception:
            resultado["kyocera_total"] = None
        try:
            resultado["mono"] = snmp_get(ip, OID_KYOCERA_MONO, comm)
        except Exception:
            resultado["mono"] = None
        try:
            resultado["color"] = snmp_get(ip, OID_KYOCERA_COLOR, comm)
        except Exception:
            resultado["color"] = None

        try:
            resultado["pjl_pagecount"] = pjl_pagecount(ip)
        except Exception:
            resultado["pjl_pagecount"] = None

        # Elegimos contador efectivo priorizando PJL (si existe) y luego SNMP.
        candidates = [
            resultado.get("pjl_pagecount"),
            resultado.get("total_paginas"),
            resultado.get("kyocera_total"),
        ]
        non_null = [int(v) for v in candidates if v is not None and int(v) > 0]
        contador_efectivo = non_null[0] if non_null else None
        fuente_efectiva = None
        if contador_efectivo is not None:
            if resultado.get("pjl_pagecount") == contador_efectivo:
                fuente_efectiva = "PJL:PAGECOUNT"
            elif resultado.get("kyocera_total") == contador_efectivo:
                fuente_efectiva = OID_KYOCERA_TOTAL
            elif resultado.get("total_paginas") == contador_efectivo:
                fuente_efectiva = total_oid or OID_TOTAL_PAGES

        resultado["contador_efectivo"] = contador_efectivo
        resultado["oid_total_detectado"] = total_oid
        resultado["oid_efectivo"] = fuente_efectiva

        if any(v is not None for v in resultado.values()):
            resultado["_community_used"] = comm
            return resultado
        last_err = RuntimeError(f"Sin respuesta SNMP de {ip} con comunidad '{comm}'")

    diag = diagnose_device(ip)
    server = diag.get("server_header") or "desconocido"
    raise RuntimeError(
        f"Sin respuesta SNMP de {ip}. "
        "Verifique la IP, el puerto UDP 161 y la comunidad SNMP configurada. "
        f"Diagnostico: TCP9100={'abierto' if diag.get('tcp_9100') else 'cerrado'}, "
        f"HTTP80={'abierto' if diag.get('tcp_80') else 'cerrado'}, "
        f"HTTPS443={'abierto' if diag.get('tcp_443') else 'cerrado'}, "
        f"Server={server}."
    ) from last_err


def validate_ipv4(ip: str) -> str:
    """Valida y normaliza una direccion IPv4. Lanza ValueError si es invalida."""
    try:
        addr = ipaddress.ip_address(ip.strip())
        if not isinstance(addr, ipaddress.IPv4Address):
            raise ValueError("Solo se soportan direcciones IPv4")
        return str(addr)
    except ValueError as exc:
        raise ValueError(f"Direccion IP invalida: {ip}") from exc
