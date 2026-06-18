"""
AVISTA CPAnalisis — Microservicio SNMP Proxy v1.0
==================================================
Archivo UNICO. Se deja corriendo en el computador de la oficina remota
(el que tenga acceso a las impresoras en la LAN local, ej: 192.168.1.x).

El servidor principal (tu PC) le pregunta a este proxy por HTTP,
evitando el problema de que las IPs 192.168.x.x no son alcanzables
directamente desde otra red.

Uso rapido en el PC de la oficina:
    python microservicio_snmp_proxy.py

Por defecto escucha en 0.0.0.0:8765  (cambiable con --port y --host).

Endpoints:
    GET  /ping
         -> {"ok": true, "sitio": "...", "version": "1.0"}

    GET  /contadores?ip=192.168.1.50&community=Admin
         -> {"ok": true, "ip": "...", "contadores": {...}}

    GET  /scan
         -> escanea todas las IPs registradas en printers.json
            y devuelve lista con resultados

    POST /register   body JSON: {"nombre":"...","oficina":"...","ip":"...","community":"Admin"}
         -> guarda en printers.json para /scan

Requisitos: Python 3.9+  —  SIN instalar nada extra (stdlib pura).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

VERSION = "1.0"
PRINTERS_FILE = Path(__file__).parent / "printers.json"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
SNMP_TIMEOUT = 4.0

# Token de autenticacion simple (puede cambiarse en la linea de comandos o
# dejarse en blanco para desactivar la verificacion).
# Si se define, el cliente debe enviar el header:   X-Proxy-Token: <token>
DEFAULT_TOKEN = os.environ.get("PROXY_TOKEN", "")

# ---------------------------------------------------------------------------
# SNMP v2c — codificacion BER minima (sin dependencias externas)
# ---------------------------------------------------------------------------

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

def _build_snmp_get(community: str, oid: str) -> bytes:
    varbind = _ber_seq(_ber_oid(oid) + _ber_null())
    pdu = _tlv(
        0xA0,
        _ber_int(1) + _ber_int(0) + _ber_int(0) + _ber_seq(varbind),
    )
    return _ber_seq(_ber_int(1) + _ber_str(community.encode()) + pdu)

def _decode_len(data: bytes, pos: int) -> tuple[int, int]:
    b = data[pos]
    if b < 0x80:
        return b, pos + 1
    n_bytes = b & 0x7F
    return int.from_bytes(data[pos + 1: pos + 1 + n_bytes], "big"), pos + 1 + n_bytes

def _decode_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    tag = data[pos]
    length, next_pos = _decode_len(data, pos + 1)
    return tag, data[next_pos: next_pos + length], next_pos + length

def _parse_snmp_value(data: bytes) -> int:
    _, msg_body, _ = _decode_tlv(data, 0)
    pos = 0
    _, _, pos = _decode_tlv(msg_body, pos)
    _, _, pos = _decode_tlv(msg_body, pos)
    _, pdu_body, _ = _decode_tlv(msg_body, pos)
    pos = 0
    _, _, pos = _decode_tlv(pdu_body, pos)
    _, err_bytes, pos = _decode_tlv(pdu_body, pos)
    error = int.from_bytes(err_bytes, "big")
    if error:
        raise ValueError(f"SNMP error-status: {error}")
    _, _, pos = _decode_tlv(pdu_body, pos)
    _, vbl_body, _ = _decode_tlv(pdu_body, pos)
    _, vb_body, _ = _decode_tlv(vbl_body, 0)
    _, _, vb_pos = _decode_tlv(vb_body, 0)
    tag, val_bytes, _ = _decode_tlv(vb_body, vb_pos)
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46, 0x47):
        return int.from_bytes(val_bytes, "big")
    raise ValueError(f"Tipo SNMP no soportado: 0x{tag:02x}")

def snmp_get(ip: str, oid: str, community: str = "public",
             port: int = 161, timeout: float = SNMP_TIMEOUT) -> int:
    packet = _build_snmp_get(community, oid)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (ip, port))
        response, _ = sock.recvfrom(4096)
    return _parse_snmp_value(response)

# OIDs Kyocera M3655idn
OID_TOTAL_CANDIDATES = [
    "1.3.6.1.2.1.43.10.2.1.4.1.1",
    "1.3.6.1.2.1.43.10.2.1.4.1.2",
    "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.1",
]
OID_KYOCERA_TOTAL = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.1"
OID_KYOCERA_MONO  = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.2"
OID_KYOCERA_COLOR = "1.3.6.1.4.1.1347.42.2.1.1.1.6.1.3"

def consultar_contadores(ip: str, community: str = "Admin") -> dict:
    """Consulta contadores SNMP locales. Falla rapido con error legible."""
    resultado: dict[str, int | None] = {}
    total_paginas = None
    total_oid = None

    for oid in OID_TOTAL_CANDIDATES:
        try:
            total_paginas = snmp_get(ip, oid, community)
            total_oid = oid
            break
        except Exception:
            continue

    resultado["total_paginas"] = total_paginas

    for key, oid in [
        ("kyocera_total", OID_KYOCERA_TOTAL),
        ("mono", OID_KYOCERA_MONO),
        ("color", OID_KYOCERA_COLOR),
    ]:
        try:
            resultado[key] = snmp_get(ip, oid, community)
        except Exception:
            resultado[key] = None

    # PJL 9100
    try:
        result = _pjl_pagecount(ip)
        resultado["pjl_pagecount"] = result
    except Exception:
        resultado["pjl_pagecount"] = None

    candidates = [
        resultado.get("pjl_pagecount"),
        resultado.get("total_paginas"),
        resultado.get("kyocera_total"),
    ]
    non_null = [int(v) for v in candidates if v is not None and int(v) > 0]
    contador_efectivo = non_null[0] if non_null else None

    if not any(v is not None for v in resultado.values()):
        raise RuntimeError(f"Sin respuesta SNMP de {ip} — verifica IP, UDP 161 y comunidad SNMP")

    resultado["contador_efectivo"] = contador_efectivo
    resultado["oid_detectado"] = total_oid
    resultado["leido_en"] = datetime.now().isoformat(timespec="seconds")
    return resultado

def _pjl_pagecount(ip: str, timeout: float = 3.0, port: int = 9100) -> int | None:
    cmd = b"\x1b%-12345X@PJL INFO PAGECOUNT\r\n\x1b%-12345X\r\n"
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(cmd)
        response = sock.recv(4096)
    text = response.decode("latin-1", errors="ignore")
    match = re.search(r"PAGECOUNT\s*=\s*(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    nums = [int(n) for n in re.findall(r"\b\d{4,}\b", text)]
    return max(nums) if nums else None

def validate_ipv4(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip.strip())
        if not isinstance(addr, ipaddress.IPv4Address):
            raise ValueError("Solo IPv4")
        return str(addr)
    except ValueError as exc:
        raise ValueError(f"IP invalida: {ip}") from exc

# ---------------------------------------------------------------------------
# Registro de impresoras locales (printers.json)
# ---------------------------------------------------------------------------

_lock = threading.Lock()

def _load_printers() -> list[dict]:
    if not PRINTERS_FILE.exists():
        return []
    try:
        return json.loads(PRINTERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def _save_printers(data: list[dict]) -> None:
    PRINTERS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

def _register_printer(nombre: str, oficina: str, ip: str, community: str) -> dict:
    safe_ip = validate_ipv4(ip)
    with _lock:
        printers = _load_printers()
        existing = next((p for p in printers if p["ip"] == safe_ip), None)
        entry = {
            "nombre": nombre[:120],
            "oficina": oficina[:120],
            "ip": safe_ip,
            "community": community or "Admin",
            "registrado_en": datetime.now().isoformat(timespec="seconds"),
        }
        if existing:
            existing.update(entry)
        else:
            printers.append(entry)
        _save_printers(printers)
    return entry

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class ProxyHandler(BaseHTTPRequestHandler):
    token: str = DEFAULT_TOKEN

    def log_message(self, format: str, *args):  # noqa: A002
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {self.address_string()} — {format % args}")

    def _auth_ok(self) -> bool:
        if not self.token:
            return True
        return self.headers.get("X-Proxy-Token", "") == self.token

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "X-Proxy-Token, Content-Type")
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            self._send_json({"ok": False, "error": "Token invalido"}, 401)
            return

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        path = parsed.path.rstrip("/")

        if path == "/ping":
            self._send_json({
                "ok": True,
                "sitio": os.environ.get("PROXY_SITIO", "Oficina remota"),
                "version": VERSION,
                "hora": datetime.now().isoformat(timespec="seconds"),
            })
            return

        if path == "/contadores":
            ip = qs.get("ip", [""])[0].strip()
            community = qs.get("community", ["Admin"])[0].strip() or "Admin"
            if not ip:
                self._send_json({"ok": False, "error": "Parametro 'ip' requerido"}, 400)
                return
            try:
                safe_ip = validate_ipv4(ip)
                contadores = consultar_contadores(safe_ip, community)
                self._send_json({"ok": True, "ip": safe_ip, "contadores": contadores})
            except Exception as exc:
                self._send_json({"ok": False, "ip": ip, "error": str(exc)}, 500)
            return

        if path == "/scan":
            printers = _load_printers()
            if not printers:
                self._send_json({"ok": True, "resultados": [], "mensaje": "No hay impresoras registradas"})
                return
            resultados = []
            for p in printers:
                try:
                    c = consultar_contadores(p["ip"], p.get("community", "Admin"))
                    resultados.append({
                        "nombre": p["nombre"],
                        "oficina": p["oficina"],
                        "ip": p["ip"],
                        "ok": True,
                        "contadores": c,
                    })
                except Exception as exc:
                    resultados.append({
                        "nombre": p["nombre"],
                        "oficina": p["oficina"],
                        "ip": p["ip"],
                        "ok": False,
                        "error": str(exc),
                    })
            self._send_json({"ok": True, "resultados": resultados})
            return

        if path == "/printers":
            self._send_json({"ok": True, "printers": _load_printers()})
            return

        self._send_json({"ok": False, "error": "Ruta no encontrada"}, 404)

    def do_POST(self):
        if not self._auth_ok():
            self._send_json({"ok": False, "error": "Token invalido"}, 401)
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/register":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({"ok": False, "error": "JSON invalido"}, 400)
                return

            ip = (body.get("ip") or "").strip()
            nombre = (body.get("nombre") or "Impresora").strip()
            oficina = (body.get("oficina") or "").strip()
            community = (body.get("community") or "Admin").strip()

            if not ip:
                self._send_json({"ok": False, "error": "'ip' es obligatorio"}, 400)
                return

            try:
                entry = _register_printer(nombre, oficina, ip, community)
                self._send_json({"ok": True, "registrado": entry})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if path == "/unregister":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send_json({"ok": False, "error": "JSON invalido"}, 400)
                return
            ip = (body.get("ip") or "").strip()
            with _lock:
                printers = _load_printers()
                before = len(printers)
                printers = [p for p in printers if p["ip"] != ip]
                _save_printers(printers)
            self._send_json({"ok": True, "eliminados": before - len(printers)})
            return

        self._send_json({"ok": False, "error": "Ruta no encontrada"}, 404)

# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AVISTA SNMP Proxy")
    parser.add_argument("--host", default=os.environ.get("PROXY_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PROXY_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--token", default=os.environ.get("PROXY_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--sitio", default=os.environ.get("PROXY_SITIO", "Oficina remota"),
                        help="Nombre del sitio (aparece en /ping)")
    args = parser.parse_args()

    os.environ["PROXY_SITIO"] = args.sitio
    ProxyHandler.token = args.token

    print("=" * 60)
    print("  AVISTA CPAnalisis — Microservicio SNMP Proxy")
    print(f"  Version : {VERSION}")
    print(f"  Sitio   : {args.sitio}")
    print(f"  Escucha : http://{args.host}:{args.port}")
    print(f"  Token   : {'activado' if args.token else 'desactivado (sin seguridad)'}")
    print(f"  Archivo : {PRINTERS_FILE}")
    print("=" * 60)
    print("Ctrl+C para detener.\n")

    server = HTTPServer((args.host, args.port), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")

if __name__ == "__main__":
    main()
