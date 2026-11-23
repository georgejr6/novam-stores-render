"""Draws the fictional demo brand 'Sol Atlas' (no real brand) at print resolution. python samples/make_logos.py"""
import math
import pathlib
from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent
S = 3  # supersample
W, H = 2400, 2856
ORANGE, CREAM = (228, 87, 46, 255), (255, 245, 230, 255)
FONT = "C:/Windows/Fonts/arialbd.ttf"


def draw(ink, name):
    im = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = W * S // 2, int(H * S * 0.34)
    r = int(W * S * 0.255)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ORANGE)
    r2, r3 = int(r * 0.72), int(r * 0.66)
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=CREAM)
    d.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], fill=ORANGE)
    for i in range(16):
        a = math.radians(i * 22.5)
        ln = 0.19 if i % 2 == 0 else 0.12
        r_in, r_out = r * 1.18, r * (1.18 + ln * 2.1)
        wdt = int(W * S * 0.0125)
        x0, y0 = cx + r_in * math.cos(a), cy + r_in * math.sin(a)
        x1, y1 = cx + r_out * math.cos(a), cy + r_out * math.sin(a)
        d.line([x0, y0, x1, y1], fill=ORANGE, width=wdt)
    f = ImageFont.truetype(FONT, int(W * S * 0.17))
    d.text((cx, cy + 4), "SA", font=f, fill=CREAM, anchor="mm")
    f2 = ImageFont.truetype(FONT, int(W * S * 0.165))
    d.text((cx, int(H * S * 0.80)), "SOL ATLAS", font=f2, fill=ink, anchor="mm")
    f3 = ImageFont.truetype(FONT, int(W * S * 0.075))
    d.text((cx, int(H * S * 0.93)), "SUNDAY GOODS CO.", font=f3, fill=ORANGE, anchor="mm")
    im = im.resize((W, H), Image.LANCZOS)
    im.crop(im.getbbox()).save(OUT / name)


draw((29, 42, 58, 255), "sol-atlas-on-light.png")
draw(CREAM, "sol-atlas-on-dark.png")
