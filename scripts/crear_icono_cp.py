"""
Genera el icono AVISTA CPAnalisis (CP sobre fondo navy+magenta).
Produce:
  app/views/web/assets/cp_icon.png  (256x256 para ventana Qt)
  app/views/web/assets/cp_icon.ico  (multi-size real para EXE Windows)
  cp_icon.ico                       (raiz del proyecto, para avistaimpr.spec)

Usa escritura manual del formato ICO (BMP 32-bit) para garantizar
compatibilidad total con Windows Explorer y PyInstaller.
"""
from __future__ import annotations

import io
import shutil
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Colores AVISTA ─────────────────────────────────────────────────────────────
NAVY    = (26,  43,  74, 255)
MAGENTA = (232, 60, 108, 255)
WHITE   = (255, 255, 255, 255)


# ── Dibuja el icono CP a un tamaño dado ───────────────────────────────────────
def make_cp_icon(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(2, size // 16)
    r   = max(6, size // 8)

    # Fondo navy redondeado
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=r, fill=NAVY,
    )

    # Franja magenta inferior
    stripe_h = max(4, size // 8)
    draw.rounded_rectangle(
        [pad, size - pad - stripe_h, size - pad - 1, size - pad - 1],
        radius=r, fill=MAGENTA,
    )
    draw.rectangle(
        [pad, size - pad - stripe_h, size - pad - 1, size - pad - stripe_h + r],
        fill=MAGENTA,
    )

    # Texto "CP"
    font_size = max(8, int(size * 0.46))
    font = None
    for fc in [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/verdanab.ttf",
        "arialbd.ttf", "calibrib.ttf",
    ]:
        try:
            font = ImageFont.truetype(fc, font_size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except Exception:
            font = ImageFont.load_default()

    text = "CP"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    usable_h = size - stripe_h - 2 * pad
    ty = pad + (usable_h - th) // 2 - bbox[1]

    shadow_off = max(1, size // 64)
    draw.text((tx + shadow_off, ty + shadow_off), text, font=font, fill=(0, 0, 0, 120))
    draw.text((tx, ty), text, font=font, fill=WHITE)

    # Punto decorativo magenta (esquina superior derecha)
    dot_r = max(2, size // 14)
    dot_x = size - pad - dot_r - max(1, size // 20)
    dot_y = pad + dot_r + max(1, size // 20)
    draw.ellipse(
        [dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
        fill=MAGENTA,
    )

    return img


# ── Escritura manual de ICO (formato BMP 32-bit) ──────────────────────────────
def _img_to_bmp_ico_entry(img: Image.Image) -> bytes:
    """Convierte una imagen RGBA a datos BMP para ICO (BITMAPINFOHEADER + pixels + mask)."""
    img = img.convert("RGBA")
    w, h = img.size

    # BITMAPINFOHEADER (40 bytes) — altura x2 (XOR + AND mask)
    bmp_header = struct.pack(
        "<IiiHHIIiiII",
        40,      # biSize
        w,       # biWidth
        h * 2,   # biHeight (doble para ICO)
        1,       # biPlanes
        32,      # biBitCount
        0,       # biCompression (BI_RGB)
        0,       # biSizeImage
        0, 0,    # XPelsPerMeter, YPelsPerMeter
        0, 0,    # ClrUsed, ClrImportant
    )

    # Pixeles BGRA de abajo hacia arriba (formato Windows)
    pixels = bytearray()
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = img.getpixel((x, y))
            pixels += bytes([b, g, r, a])

    # AND mask (todo ceros — el alpha del canal RGBA controla transparencia)
    mask_stride = ((w + 31) // 32) * 4
    and_mask = bytes(mask_stride * h)

    return bmp_header + bytes(pixels) + and_mask


def build_ico(images: list[Image.Image]) -> bytes:
    """Construye un archivo ICO real a partir de una lista de imágenes RGBA."""
    num = len(images)

    # Offset inicial: 6 (cabecera ICO) + 16 * num (directorio)
    offset = 6 + 16 * num
    entries: list[bytes] = []
    blobs:   list[bytes] = []

    for img in images:
        blob = _img_to_bmp_ico_entry(img)
        s = img.size[0]
        # ICONDIRENTRY (16 bytes)
        entry = struct.pack(
            "<BBBBHHII",
            s if s < 256 else 0,   # bWidth  (0 = 256)
            s if s < 256 else 0,   # bHeight (0 = 256)
            0,                      # bColorCount
            0,                      # bReserved
            1,                      # wPlanes
            32,                     # wBitCount
            len(blob),              # dwBytesInRes
            offset,                 # dwImageOffset
        )
        entries.append(entry)
        blobs.append(blob)
        offset += len(blob)

    # ICONDIR header (6 bytes)
    header = struct.pack("<HHH", 0, 1, num)
    return header + b"".join(entries) + b"".join(blobs)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    base = Path(__file__).resolve().parent.parent
    out  = base / "app" / "views" / "web" / "assets"
    out.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 256]
    images = [make_cp_icon(s) for s in sizes]

    # PNG 256 para Qt (ventana)
    png_path = out / "cp_icon.png"
    images[-1].save(str(png_path))
    print(f"[OK] PNG: {png_path}  ({png_path.stat().st_size:,} bytes)")

    # ICO multi-size (escritura manual)
    ico_bytes = build_ico(images)
    ico_asset = out / "cp_icon.ico"
    ico_asset.write_bytes(ico_bytes)
    print(f"[OK] ICO assets: {ico_asset}  ({len(ico_bytes):,} bytes)")

    # Copiar ICO a la raíz del proyecto (referenciado en avistaimpr.spec)
    ico_root = base / "cp_icon.ico"
    shutil.copy2(str(ico_asset), str(ico_root))
    print(f"[OK] ICO raiz:   {ico_root}  ({ico_root.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
