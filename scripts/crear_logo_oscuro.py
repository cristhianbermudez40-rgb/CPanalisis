"""
Genera avista-logo-dark.png: versión del logo con texto en blanco para modo oscuro.
Los píxeles oscuros/texto se convierten a blanco, los píxeles de color del ícono se mantienen.
"""
from pathlib import Path
from PIL import Image


def es_pixel_texto(r, g, b, a):
    """Detecta píxeles de texto oscuro (no saturados o muy oscuros)."""
    if a < 30:
        return False
    brillo = (r + g + b) / 3
    saturacion = max(r, g, b) - min(r, g, b)
    # Texto: oscuro Y poca saturación (no es un color vivo del ícono)
    return brillo < 140 and saturacion < 80


def crear_logo_oscuro():
    assets_dir = Path(__file__).resolve().parent.parent / "app" / "views" / "web" / "assets"
    src = assets_dir / "avista logo.png"

    if not src.exists():
        print(f"ERROR: No se encontró {src}")
        return

    img = Image.open(src).convert("RGBA")
    datos = img.load()
    ancho, alto = img.size

    for y in range(alto):
        for x in range(ancho):
            r, g, b, a = datos[x, y]
            if es_pixel_texto(r, g, b, a):
                datos[x, y] = (255, 255, 255, a)

    dst = assets_dir / "avista-logo-dark.png"
    img.save(dst, "PNG")
    print(f"Logo oscuro generado: {dst}")
    print(f"Tamaño: {ancho}x{alto} px")


if __name__ == "__main__":
    crear_logo_oscuro()
