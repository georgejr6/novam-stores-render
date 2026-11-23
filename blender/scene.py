"""Render one product job headlessly.

    blender -b -P scene.py -- <job.json> <out_dir>

job.json (see worker/README): type, printArea {w,h,dpi} px, colors [{name, hex, shots[]}], logo <png path>, label {path,wIn,hIn}|null,
brand {accent, ink, backdrop}, size [w,h], samples. Output: <out_dir>/<color-slug>/<shot>.png and <out_dir>/render.json.
Cycles on CPU with low samples + denoise: made for free GitHub Actions runners (no GPU)."""
import json
import math
import os
import re
import sys
import time

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import products as PR  # noqa: E402
from common import S  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1 :]
JOB = json.load(open(argv[0], encoding="utf-8"))
OUT = argv[1]

GARMENT_LABEL_TYPES = {"tee", "heavy-tee", "long-sleeve", "hoodie", "crewneck"}
SLUG = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"  # noqa: E731


def reset_scene(size, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.03
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:  # noqa: BLE001
        pass
    sc.cycles.max_bounces = 5
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 3
    sc.cycles.transparent_max_bounces = 6
    sc.cycles.sample_clamp_indirect = 8
    sc.render.resolution_x, sc.render.resolution_y = size
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.render.film_transparent = False
    for vt in ("Khronos PBR Neutral", "AgX", "Standard"):
        try:
            sc.view_settings.view_transform = vt
            break
        except TypeError:
            continue
    try:
        sc.view_settings.look = "None"
    except TypeError:
        pass
    sc.view_settings.exposure = float(JOB.get("exposure", -0.8))
    return sc


def pick_backdrop(garment_hex):
    brand = JOB.get("brand") or {}
    bd = brand.get("backdrop")
    if not bd:
        acc = brand.get("accent")
        bd = C.mix_hex(acc, "#FFFFFF", 0.84) if acc else "#E9E4DA"
    if abs(C.lum(bd) - C.lum(garment_hex)) < 0.26:
        if C.lum(garment_hex) > 0.45:  # light product: a deep tone of the brand accent
            bd = C.mix_hex(brand.get("accent") or "#6B6F76", "#121212", 0.72)
        else:
            bd = "#ECE8DF"
    return bd


def build_product(kind, color_hex):
    t = JOB["type"]
    area = JOB["printArea"]
    aw, ah = area["w"] / area["dpi"], area["h"] / area["dpi"]
    if kind in ("tee", "heavy-tee"):
        return PR.build_tee(color_hex, heavy=(kind == "heavy-tee"))
    if kind == "long-sleeve":
        return PR.build_tee(color_hex, long_sleeve=True)
    if kind == "crewneck":
        return PR.build_crewneck(color_hex)
    if kind == "hoodie":
        return PR.build_hoodie(color_hex)
    if kind == "tote":
        return PR.build_tote(color_hex)
    if kind == "poster":
        return PR.build_poster_sized(color_hex, aw, ah)
    if kind == "mug":
        return PR.build_mug(color_hex, aw, ah)
    if kind in ("dad-hat", "snapback"):
        return PR.build_cap(color_hex, flat=(kind == "snapback"), snap=(kind == "snapback"))
    raise SystemExit(f"unsupported product type {t}")


def place_logo(P, kind):
    area = JOB["printArea"]
    aw, ah = area["w"] / area["dpi"], area["h"] / area["dpi"]
    mat, img = C.mat_decal("logo", JOB["logo"], embroidery=P.embroidery, rough=0.25 if kind == "mug" else 0.72)
    lw, lh = img.size
    w_in, h_in = C.fit_contain(lw, lh, aw, ah, float(JOB.get("logoScale", 1.0)))
    cx = P.anchor[0]
    cz = P.anchor[1] - ah / 2 if "anchor_top" in P.notes else P.anchor[1]
    if kind == "mug":
        R = P.wrap["R"] + 0.004
        arc = w_in / R

        def warp(x, z, u, v):
            th = (u - 0.5) * arc
            return (R * math.sin(th) * S, -R * math.cos(th) * S, (P.wrap["zc"] + (v - 0.5) * h_in) * S)

        d = C.make_grid("logo", w_in * S, h_in * S, 120, 40, warp)
        d.data.materials.append(mat)
        d.visible_shadow = False
    else:
        res = int(min(220, max(80, w_in * 11)))
        d = C.make_decal_plane("logo", w_in, h_in, cx, -0.6, cz, mat, res=res)
        C.shrinkwrap_project(d, P.target, offset_m=0.0006 if not P.embroidery else 0.0012)
    P.decal = d
    P.logo_box = (w_in, h_in, cx, cz)
    return d


def place_label(P):
    lab = JOB.get("label")
    if not lab or JOB["type"] not in GARMENT_LABEL_TYPES or P.label_center is None:
        return None
    mat, img = C.mat_decal("label", lab["path"], rough=0.85)
    w = float(lab.get("wIn", 3.0))
    h = float(lab.get("hIn", 1.13))
    lw, lh = img.size
    if lw and lh:
        h = w * lh / lw if abs(w * lh / lw - h) > 0.01 else h
    w = min(w, 3.2)
    d = C.make_decal_plane("label", w, h, P.label_center[0], -0.6, P.label_center[1], mat, res=40)
    back = next((o for o in P.objs if o.name.startswith("backneck")), None)
    if back is None:
        return None
    C.shrinkwrap_project(d, back, offset_m=0.0006)
    P.label_obj = d
    return d


def lights(kind, center, scale, backdrop_hex, styled=False):
    created = []
    cx, cy, cz = center
    k = scale
    created.append(C.add_area("key", (cx - 1.1 * k, cy - 1.5 * k, cz + 1.1 * k), center, 330 * k * k, 1.6 * k))
    created.append(C.add_area("fill", (cx + 1.5 * k, cy - 1.1 * k, cz + 0.2 * k), center, 110 * k * k, 2.0 * k))
    created.append(C.add_area("rim", (cx + 0.2 * k, cy + 0.8 * k, cz + 1.6 * k), center, 80 * k * k, 1.2 * k))
    return created


def set_world(sc, hexcol, strength=0.5):
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*C.hex_rgb(hexcol), 1.0)
    bg.inputs["Strength"].default_value = strength


def shot_camera(P, shot, lo, hi, kind):
    cam_d = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_d)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    center = (lo + hi) / 2
    pts = C.corners(lo, hi)
    floor = P.on_floor
    az = lambda deg, el: (math.sin(math.radians(deg)) * math.cos(math.radians(el)), -math.cos(math.radians(deg)) * math.cos(math.radians(el)), math.sin(math.radians(el)))  # noqa: E731
    cam_d.dof.use_dof = False
    if shot == "flat":
        C.frame_camera(cam, bpy.context.scene, center, az(0, 3 if floor else 0), pts, lens=85, margin=0.1 if not floor else 0.14)
    elif shot == "angle":
        C.frame_camera(cam, bpy.context.scene, center, az(34, 22 if floor else 9), pts, lens=60, margin=0.1 if not floor else 0.12)
    elif shot == "styled":
        C.frame_camera(cam, bpy.context.scene, center, az(-20, 16 if floor else 6), pts, lens=50, margin=0.12 if not floor else 0.16)
    elif shot == "detail":
        w_in, h_in, cx, cz = P.logo_box
        dc = P.decal
        dlo, dhi = C.bbox_world([dc])
        c = (dlo + dhi) / 2
        pad = max(dhi.x - dlo.x, dhi.z - dlo.z) * 0.55 + 0.01
        dpts = [(c.x + sx * pad * (0.8 if kind != "mug" else 1.0), c.y, c.z + sz * pad * 1.25) for sx in (-1, 1) for sz in (-1, 1)]
        dpts += C.corners(dlo, dhi)
        C.frame_camera(cam, bpy.context.scene, c, az(10, 14), dpts, lens=100, margin=0.06, aim=c)
        cam_d.dof.use_dof = True
        cam_d.dof.focus_distance = (cam.location - c).length
        cam_d.dof.aperture_fstop = 4.0
    elif shot == "label":
        lc = P.label_obj
        llo, lhi = C.bbox_world([lc])
        c = (llo + lhi) / 2
        pad = 0.05
        lpts = [(c.x + sx * pad * 1.5, c.y, c.z + sz * pad) for sx in (-1, 1) for sz in (-1, 1)] + C.corners(llo, lhi)
        C.frame_camera(cam, bpy.context.scene, c, az(0, 32), lpts, lens=100, margin=0.1, aim=c)
        cam_d.dof.use_dof = True
        cam_d.dof.focus_distance = (cam.location - c).length
        cam_d.dof.aperture_fstop = 5.6
    return cam


def render_color(color):
    name, hexcol = color["name"], color["hex"]
    sc = reset_scene(tuple(JOB.get("size", [1200, 1500])), int(JOB.get("samples", 48)))
    P = build_product(JOB["type"], hexcol)
    bpy.context.view_layer.update()
    place_logo(P, JOB["type"])
    place_label(P)
    bpy.context.view_layer.update()
    lo, hi = C.bbox_world([o for o in P.objs])
    print("BBOX", JOB["type"], tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi), [(o.name, tuple(round(v,2) for v in o.dimensions)) for o in P.objs])
    backdrop = pick_backdrop(hexcol)
    wall_y = hi.y + P.wall_gap_m
    floor_z = 0.0 if P.on_floor else lo.z - 0.9
    m_bg = C.mat_plain("backdrop", backdrop, rough=0.92)
    C.cyclorama("set", m_bg, wall_y, floor_z, half_w=3.0, radius=0.3 if P.on_floor else 0.5, height=3.0, depth=3.0)
    set_world(sc, backdrop, 0.45)
    center = (lo + hi) / 2
    scale = max(0.5, min(1.6, (hi - lo).length * 1.2))
    base_lights = lights(JOB["type"], tuple(center), scale, backdrop)
    out_dir = os.path.join(OUT, f"{JOB['colors'].index(color)}-{SLUG(name)}")
    os.makedirs(out_dir, exist_ok=True)
    done = []
    for shot in color.get("shots", ["flat"]):
        if shot == "label" and P.label_obj is None:
            continue
        extras = []
        if shot == "styled":
            # lifestyle: an accent disc on the wall and window-blind shadow stripes from a low sun
            acc = (JOB.get("brand") or {}).get("accent") or "#C9A24A"
            disc_hex = acc if abs(C.lum(acc) - C.lum(hexcol)) > 0.2 else C.mix_hex(acc, "#FFFFFF", 0.4)
            disc_m = C.mat_plain("disc", C.mix_hex(disc_hex, backdrop, 0.35), rough=0.9)
            r = max(hi.x - lo.x, hi.z - lo.z) * 0.78
            bpy.ops.mesh.primitive_circle_add(vertices=96, radius=r, fill_type="NGON", location=(center.x - r * 0.12, wall_y - 0.004, max(center.z, lo.z + r * 0.9) if P.on_floor else center.z))
            disc = bpy.context.object
            disc.rotation_euler[0] = math.radians(90)
            disc.data.materials.append(disc_m)
            extras.append(disc)
            sun = bpy.data.lights.new("sun", "SUN")
            sun.energy = 2.6
            sun.angle = math.radians(1.6)
            so = bpy.data.objects.new("sun", sun)
            bpy.context.collection.objects.link(so)
            so.rotation_euler = (math.radians(58), 0, math.radians(-38))
            extras.append(so)
            blind = C.mat_plain("blind", "#222222")
            bs = scale
            for i in range(-6, 7):
                bpy.ops.mesh.primitive_cube_add(size=1, location=(center.x - 0.9 * bs, center.y - 1.6 * bs, center.z + i * 0.17 * bs * 0.8 + 0.5 * bs))
                sl = bpy.context.object
                sl.scale = (2.4 * bs, 0.02, 0.055 * bs)
                sl.rotation_euler[0] = math.radians(-35)
                sl.data.materials.append(blind)
                sl.visible_camera = False
                extras.append(sl)
            for lg in base_lights:  # sun is the key; keep a soft fill so the print stays readable
                if lg.name.startswith("key"):
                    lg.data.energy *= 0.25
        cam = shot_camera(P, shot, lo, hi, JOB["type"])
        path = os.path.join(out_dir, f"{shot}.png")
        sc.render.filepath = path
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"rendered {name}/{shot} in {time.time() - t0:.1f}s")
        done.append({"color": name, "shot": shot, "file": os.path.relpath(path, OUT).replace("\\", "/"), "seconds": round(time.time() - t0, 1)})
        for o in extras:
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.objects.remove(cam, do_unlink=True)
        for lg in base_lights:
            if lg.name.startswith("key"):
                lg.data.energy = 330 * scale * scale
    return done


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    for color in JOB["colors"]:
        results += render_color(color)
    json.dump({"type": JOB["type"], "blender": bpy.app.version_string, "renders": results}, open(os.path.join(OUT, "render.json"), "w"), indent=1)


main()
