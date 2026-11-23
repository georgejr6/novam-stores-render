"""Turn one recipe into product photos: the provider's own Mockup Generator output for the exact product, colour and print area.

Used by poll.py (production jobs) and directly for the sample jobs (`python worker/render_job.py samples/jobs/tee.json out/`).
Nothing here draws a product: the photographs come from Printful's catalog photography with the brand's logo placed at the
real print position, so the image matches what the customer receives."""
import hashlib
import io
import ipaddress
import json
import os
import pathlib
import shutil
import socket
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gate  # noqa: E402
import printful  # noqa: E402
from plans import PLANS, fit_layer  # noqa: E402

Image.MAX_IMAGE_PIXELS = 40_000_000

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_LOGO_BYTES = 6 * 1024 * 1024
RECIPE_VERSION = 2
OUT_SIZE = (1000, 1000)  # the provider's native size; never upscaled


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a logo URL must not bounce us anywhere else
        return None


def _public_host(host: str) -> bool:
    """True when every address the host resolves to is a public one (no loopback, private, link-local, metadata)."""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def absolute_logo_url(url: str, base: str | None) -> str:
    if url.startswith("/") and base:
        url = base.rstrip("/") + url
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password or not _public_host(u.hostname):
        raise ValueError("only public https image URLs are accepted")
    return url


def fetch_image(url: str, dest: pathlib.Path) -> Image.Image:
    """Downloads the logo (public https only, no redirects, size-capped) so we can measure it. Printful fetches the same URL itself."""
    req = urllib.request.Request(url, headers={"User-Agent": "novam-stores-render/2"})
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as r:
        data = r.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("logo too large")
    im = Image.open(io.BytesIO(data))
    im.load()
    if im.size[0] < 300 or im.size[1] < 300:
        raise ValueError(f"logo is too small to print well ({im.size[0]}x{im.size[1]}); upload at least 300 px")
    rgba = im.convert("RGBA")
    rgba.save(dest, "PNG")
    return rgba


def require_ci() -> None:
    """Runs on GitHub Actions (or an owner cloud droplet) only. Never on a laptop."""
    if os.environ.get("GITHUB_ACTIONS") != "true" and os.environ.get("RENDER_ALLOW_LOCAL") != "cloud-box":
        raise SystemExit("refusing to run outside GitHub Actions (set RENDER_ALLOW_LOCAL=cloud-box only on an owner cloud droplet)")


def to_webp(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "WEBP", quality=quality, method=5)
    return buf.getvalue()


def validate_recipe(recipe: dict) -> dict:
    if recipe.get("v") != RECIPE_VERSION:
        raise ValueError("recipe is from an older renderer; ask the store to make the images again")
    plan = PLANS.get(recipe.get("type", ""))
    if not plan:
        raise ValueError(f"no photo plan for product type {recipe.get('type')!r}")
    if int(recipe.get("providerProductId", 0)) != plan["productId"]:
        raise ValueError("recipe product does not match the photo plan")
    colors = recipe.get("colors") or []
    if not colors or len(colors) > 3:
        raise ValueError("recipe needs 1 to 3 colours")
    for c in colors:
        if not isinstance(c.get("variantId"), int) or c["variantId"] <= 0:
            raise ValueError("every colour needs a provider variant id")
        bad = [s for s in c.get("shots", []) if s not in plan["shots"]]
        if bad:
            raise ValueError(f"shots not available for {recipe['type']}: {', '.join(bad)}")
    return plan


def render_recipe(recipe: dict, work: pathlib.Path, base: str | None = None, *, sleep=time.sleep) -> list[dict]:
    """recipe: {v:2, type, providerProductId, colors:[{name, hex, variantId, shots}], logoUrl, ...}.
    Returns [{color, shot, webp(bytes), png(path), seconds}]. Raises on any problem: the job then fails visibly and is retried."""
    require_ci()
    plan = validate_recipe(recipe)
    work.mkdir(parents=True, exist_ok=True)
    logo_url = absolute_logo_url(recipe["logoUrl"], base)
    logo = fetch_image(logo_url, work / "logo.png")
    layer = fit_layer(plan, *logo.size)
    rows = printful.style_rows(plan["productId"])
    results: list[dict] = []
    for color in recipe["colors"]:
        t0 = time.time()
        wanted: dict[str, int] = {}
        for shot in color["shots"]:
            cat, view = plan["shots"][shot]
            sid = printful.find_style(rows, plan["placement"], plan["area"], cat, view)
            if sid is None:
                raise RuntimeError(f"provider has no '{cat} / {view}' photo for {recipe['type']} (shot {shot})")
            if shot == "model" and sid != plan.get("model_pin"):
                raise RuntimeError(f"model photo for {recipe['type']} changed at the provider (style {sid}); it needs a new review")
            wanted[shot] = sid
        cache = work / "cache"
        cache.mkdir(exist_ok=True)
        key = f"{recipe['type']}-{color['variantId']}-" + hashlib.sha1(json.dumps([logo_url, layer, sorted(wanted.values())], sort_keys=True).encode()).hexdigest()[:12]
        task = None
        cached = {s: cache / f"{key}-{sid}.jpg" for s, sid in wanted.items()}
        if not all(p.exists() for p in cached.values()):  # a retried run inside the same job reuses what it already downloaded
            tid = printful.create_task(plan["productId"], color["variantId"], plan["placement"], plan["technique"], layer, logo_url, sorted(set(wanted.values())))
            task = printful.wait_task(tid, sleep=sleep)
            urls = printful.mockups_by_style(task, plan["placement"])
            for s, sid in wanted.items():
                if sid not in urls:
                    raise RuntimeError(f"provider did not return the {s} photo")
                cached[s].write_bytes(printful.download(urls[sid]))
        palette = gate.logo_palette(logo, color["hex"])
        for shot, path in cached.items():
            raw = path.read_bytes()
            ok, why = gate.check_image(raw, palette)
            if not ok:
                raise RuntimeError(f"quality check failed for {recipe['type']} / {color['name']} / {shot}: {why}")
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if img.size != OUT_SIZE:
                img = img.resize(OUT_SIZE, Image.LANCZOS)
            png = work / f"{recipe['type']}__{color['name'].lower().replace(' ', '-')}__{shot}.png"
            img.save(png)
            results.append({"color": color["name"], "shot": shot, "seconds": int(time.time() - t0), "webp": to_webp(img), "png": png})
    return results


if __name__ == "__main__":
    recipe_path, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    recipe = json.loads(recipe_path.read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    res = render_recipe(recipe, out_dir / "_work")
    for r in res:
        dest = out_dir / r["png"].name
        shutil.copy(r["png"], dest)
        print("wrote", dest.name, f"{r['seconds']}s")
