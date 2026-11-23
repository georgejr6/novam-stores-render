"""Turn one recipe into images: download the logo, run Blender, convert to WebP.

Used by poll.py (production jobs) and directly for the sample jobs (`python worker/render_job.py samples/jobs/tee.json out/`)."""
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_LOGO_BYTES = 6 * 1024 * 1024


def fetch_png(url: str, dest: pathlib.Path, base: str | None = None) -> tuple[int, int]:
    if url.startswith("/") and base:
        url = base.rstrip("/") + url
    if not url.startswith("https://"):
        raise ValueError("only https image URLs are accepted")
    req = urllib.request.Request(url, headers={"User-Agent": "novam-stores-render/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("image too large")
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    im.thumbnail((2000, 2000))
    im.save(dest, "PNG")
    return im.size


def blender_bin() -> str:
    return os.environ.get("BLENDER", "blender")


def run_blender(job: dict, work: pathlib.Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    (work / "job.json").write_text(json.dumps(job))
    out = work / "out"
    shutil.rmtree(out, ignore_errors=True)
    cmd = [blender_bin(), "-b", "--factory-startup", "-P", str(ROOT / "blender" / "scene.py"), "--", str(work / "job.json"), str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 40)
    sys.stdout.write(p.stdout[-4000:])
    if p.returncode != 0 or not (out / "render.json").exists():
        raise RuntimeError("blender failed: " + (p.stderr or p.stdout)[-1500:])
    return json.loads((out / "render.json").read_text())


def to_webp(png: pathlib.Path, quality: int = 90) -> bytes:
    im = Image.open(png).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=5)
    return buf.getvalue()


def render_recipe(recipe: dict, work: pathlib.Path, base: str | None = None) -> list[dict]:
    """recipe: {type, printArea, colors:[{name,hex,shots}], logoUrl|logoPath, labelUrl?, brand, size, samples}.
    Returns [{color, shot, webp(bytes), png(path), seconds}]."""
    work.mkdir(parents=True, exist_ok=True)
    job = dict(recipe)
    logo = work / "logo.png"
    if recipe.get("logoPath"):
        shutil.copy(recipe["logoPath"], logo)
    else:
        fetch_png(recipe["logoUrl"], logo, base)
    job["logo"] = str(logo)
    if recipe.get("labelPath") or recipe.get("labelUrl"):
        lab = work / "label.png"
        if recipe.get("labelPath"):
            shutil.copy(recipe["labelPath"], lab)
        else:
            fetch_png(recipe["labelUrl"], lab, base)
        job["label"] = {"path": str(lab), "wIn": recipe.get("labelWIn", 3.0), "hIn": recipe.get("labelHIn", 1.13)}
    else:
        job["label"] = None
    meta = run_blender(job, work)
    out = []
    for r in meta["renders"]:
        png = work / "out" / r["file"]
        out.append({"color": r["color"], "shot": r["shot"], "seconds": r["seconds"], "webp": to_webp(png), "png": png})
    return out


if __name__ == "__main__":
    recipe_path, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    recipe = json.loads(recipe_path.read_text())
    for k in ("logoPath", "labelPath"):
        if recipe.get(k):
            recipe[k] = str((recipe_path.parent / recipe[k]).resolve())
    out_dir.mkdir(parents=True, exist_ok=True)
    res = render_recipe(recipe, out_dir / "_work")
    for r in res:
        dest = out_dir / f"{recipe['type']}__{r['color'].lower().replace(' ', '-')}__{r['shot']}.png"
        shutil.copy(r["png"], dest)
        print("wrote", dest, f"{r['seconds']}s")
