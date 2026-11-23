"""Styled-on-model shots, gated.

Rule (owner): model imagery is Black and Latino/Latina models only, never white models, for every generated or selected
shot. This repo ships NO model photos. A photo is usable only when listed in an owner-approved manifest:

    models/approved.json = [{"id": "m1", "image": "m1.jpg", "group": "black" | "latino", "approvedBy": "<owner>",
                             "approvedAt": "2026-11-23", "garments": {"tee": [[x,y],[x,y],[x,y],[x,y]]}}]

`garments[type]` is the chest quad (TL, TR, BR, BL in pixels) the flat product shot is warped into.
Anything not in the manifest, or with another group, is ignored. With no approved models the shot is skipped and the
store keeps garment-only images (the safe default)."""
import json
import pathlib

ALLOWED_GROUPS = {"black", "latino"}


def approved_models(models_dir):
    mf = pathlib.Path(models_dir) / "approved.json"
    if not mf.exists():
        return []
    out = []
    for m in json.loads(mf.read_text()):
        img = pathlib.Path(models_dir) / m.get("image", "")
        if m.get("group") in ALLOWED_GROUPS and m.get("approvedBy") and m.get("approvedAt") and img.exists() and m.get("garments"):
            out.append({**m, "path": img})
    return out


def pick_model(models_dir, garment_type, seed=0):
    ok = [m for m in approved_models(models_dir) if garment_type in m["garments"]]
    return ok[seed % len(ok)] if ok else None


def composite(model, garment_type, garment_png, out_png):
    """Warp the flat garment cut-out (RGBA) onto the model's chest quad, with the original photo's shading multiplied over it."""
    import numpy as np
    from PIL import Image
    import cv2

    base = np.array(Image.open(model["path"]).convert("RGB"))
    g = np.array(Image.open(garment_png).convert("RGBA"))
    h, w = g.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32(model["garments"][garment_type])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(g, M, (base.shape[1], base.shape[0]), flags=cv2.INTER_LINEAR)
    a = warped[..., 3:4].astype(np.float32) / 255.0
    shade = cv2.GaussianBlur(cv2.cvtColor(base, cv2.COLOR_RGB2GRAY), (0, 0), 6).astype(np.float32) / 255.0
    shade = np.clip(shade / (shade.mean() + 1e-6), 0.6, 1.3)[..., None]
    mixed = base * (1 - a) + np.clip(warped[..., :3] * shade, 0, 255) * a
    Image.fromarray(mixed.astype(np.uint8)).save(out_png)
