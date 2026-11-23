"""Automated sanity gate for every product photo before it is uploaded. A photo that fails is never shipped.

Checks: resolution, not blank, and the logo is actually in the picture (the logo's own colours must show up).
The gate is deliberately simple; it catches "the provider returned an empty/placeholder image" and "the logo did not land",
not taste. Taste is checked by looking at the sample set (README, "Quality gate")."""
import io

from PIL import Image

MIN_SIDE = 800
MIN_STDDEV = 9.0
PALETTE_SHARE = 0.03  # a logo colour must cover at least this share of the logo's opaque pixels
NEAR_GARMENT = 48  # logo colours this close to the product colour are invisible by design: not usable as evidence
MATCH_DIST = 40  # an image pixel counts as "logo colour" when this close (RGB distance); embroidery shifts colours a little
MIN_LOGO_SHARE = 0.0012  # share of picture pixels that must be logo-coloured


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def logo_palette(logo: Image.Image, garment_hex: str) -> list[tuple[int, int, int]]:
    """Dominant opaque colours of the logo that are distinguishable from the product colour."""
    im = logo.convert("RGBA")
    im.thumbnail((200, 200))
    counts: dict[tuple[int, int, int], int] = {}
    total = 0
    for r, g, b, a in im.getdata():
        if a < 230:
            continue
        total += 1
        k = (r // 16 * 16 + 8, g // 16 * 16 + 8, b // 16 * 16 + 8)
        counts[k] = counts.get(k, 0) + 1
    if not total:
        return []
    gar = _hex_rgb(garment_hex)
    out = []
    for k, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if n / total >= PALETTE_SHARE and _dist(k, gar) > NEAR_GARMENT:
            if all(_dist(k, o) > 40 for o in out):
                out.append(k)
        if len(out) >= 4:
            break
    return out


def check_image(png_or_jpg: bytes, palette: list[tuple[int, int, int]], *, min_side: int = MIN_SIDE) -> tuple[bool, str]:
    """(ok, reason). `palette` empty means the logo is the product colour: logo presence cannot be judged, other checks still apply."""
    try:
        im = Image.open(io.BytesIO(png_or_jpg))
        im.load()
    except Exception:  # noqa: BLE001
        return False, "not a readable image"
    if min(im.size) < min_side:
        return False, f"too small ({im.size[0]}x{im.size[1]})"
    rgb = im.convert("RGB")
    small = rgb.copy()
    small.thumbnail((400, 400))
    gray = list(small.convert("L").getdata())
    mean = sum(gray) / len(gray)
    sd = (sum((v - mean) ** 2 for v in gray) / len(gray)) ** 0.5
    if sd < MIN_STDDEV:
        return False, "image is blank"
    if palette:
        px = list(small.getdata())
        hits = sum(1 for p in px if any(_dist(p, c) <= MATCH_DIST for c in palette))
        if hits / len(px) < MIN_LOGO_SHARE:
            return False, "logo not found in the picture"
    return True, "ok"
