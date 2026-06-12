"""Generate gradient play-button icons for the Chrome extension."""
from PIL import Image, ImageDraw
from pathlib import Path

ICONS = Path(__file__).parent / "chrome-extension" / "icons"
ICONS.mkdir(parents=True, exist_ok=True)

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
C1 = (124, 92, 255)   # purple
C2 = (255, 92, 168)   # pink

for size in (16, 48, 128):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # diagonal gradient on a rounded square
    grad = Image.new("RGB", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            gd.point((x, y), fill=lerp(C1, C2, t))
    # rounded mask
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = max(3, size // 5)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.paste(grad, (0, 0), mask)
    # white play triangle
    d = ImageDraw.Draw(img)
    cx, cy = size * 0.54, size * 0.5
    w = size * 0.26
    d.polygon([(cx - w * 0.7, cy - w), (cx - w * 0.7, cy + w), (cx + w, cy)], fill=(255, 255, 255, 255))
    img.save(ICONS / f"icon{size}.png")
    print("wrote", ICONS / f"icon{size}.png")
