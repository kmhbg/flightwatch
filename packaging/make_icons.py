"""Draw the app icon (rounded square, airplane) and write icon.png / .ico / .icns.

    python packaging/make_icons.py      # needs Pillow; writes src/flightwatch/assets/ and packaging/
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BG, FG, ACCENT = (17, 28, 24), (230, 236, 214), (80, 148, 117)


def plane(size):
    """Airplane pointing up-right, as polygons in a 0..1 box."""
    body = [(0.47, 0.08), (0.53, 0.08), (0.56, 0.16), (0.56, 0.84), (0.50, 0.94), (0.44, 0.84), (0.44, 0.16)]
    wings = [(0.44, 0.40), (0.56, 0.40), (0.95, 0.60), (0.95, 0.66), (0.56, 0.56), (0.44, 0.56), (0.05, 0.66), (0.05, 0.60)]
    tail = [(0.45, 0.78), (0.55, 0.78), (0.72, 0.88), (0.72, 0.92), (0.50, 0.87), (0.28, 0.92), (0.28, 0.88)]
    a = math.radians(45)

    def rot(pts):
        out = []
        for x, y in pts:
            x, y = x - 0.5, y - 0.5
            out.append(((x * math.cos(a) - y * math.sin(a)) * 0.78 + 0.5, (x * math.sin(a) + y * math.cos(a)) * 0.78 + 0.5))
        return [(x * size, y * size) for x, y in out]
    return [rot(p) for p in (body, wings, tail)]


def draw(size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size * 0.06
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size * 0.2, fill=BG, outline=ACCENT,
                        width=round(size * 0.035))
    for poly in plane(size):
        d.polygon(poly, fill=FG)
    return img


def main():
    img = draw()
    assets = ROOT / "src/flightwatch/assets"
    assets.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(assets / "icon.png")
    out = ROOT / "packaging"
    img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.resize((512, 512), Image.LANCZOS).save(out / "icon.icns")
    img.resize((512, 512), Image.LANCZOS).save(out / "icon.png")


if __name__ == "__main__":
    main()
