"""The EQ icon: a curve with a red point on black. One drawing, used by the
exe (build.py) and by the tray icon (tray.py)."""

import math


def image(size=256):
    """The icon as a PIL image, drawn big and reduced so small sizes keep their weight."""
    from PIL import Image, ImageDraw
    big = 1024
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 40, big - 40, big - 40), radius=230, fill=(0, 0, 0, 255),
                        outline=(40, 40, 40, 255), width=12)
    pts = []
    for i in range(201):
        x = 170 + i * (big - 340) / 200
        t = (x - 170) / (big - 340)
        y = big / 2 - 210 * math.exp(-((t - 0.32) / 0.13) ** 2) + 150 * math.exp(-((t - 0.74) / 0.12) ** 2)
        pts.append((x, y))
    d.line(pts, fill=(255, 255, 255, 255), width=44, joint="curve")
    px, py = pts[64]
    d.ellipse((px - 70, py - 70, px + 70, py + 70), fill=(215, 25, 32, 255))
    return im.resize((size, size), Image.LANCZOS)


def save_ico(path, sizes=(16, 32, 48, 64, 128, 256)):
    image(256).save(path, sizes=[(s, s) for s in sizes])
    return path
