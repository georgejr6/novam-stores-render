"""Shared Blender helpers: colour, materials, meshes, camera framing, studio set. Runs inside Blender (bpy)."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

S = 0.0254  # inches -> metres


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h, lin=True):
    h = (h or "#808080").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    v = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(srgb_to_lin(x) for x in v) if lin else tuple(v)


def lum(h):
    r, g, b = hex_rgb(h, lin=False)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mix_hex(a, b, t):
    ra, rb = hex_rgb(a, lin=False), hex_rgb(b, lin=False)
    return "#%02X%02X%02X" % tuple(int(round((ra[i] * (1 - t) + rb[i] * t) * 255)) for i in range(3))


def setin(node, name, value):
    """Set a node input by name, ignoring names that this Blender version does not have."""
    sock = node.inputs.get(name)
    if sock is not None:
        sock.default_value = value


# ---------------------------------------------------------------- materials
def mat_fabric(name, hexcol, rough=0.9, sheen=0.35, bump=0.35, grain=700.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*hex_rgb(hexcol), 1.0)
    setin(b, "Roughness", rough)
    setin(b, "Sheen Weight", sheen * (0.25 + 0.75 * min(1.0, lum(hexcol) * 2.0)))  # dark cloth stays dark
    setin(b, "Sheen Roughness", 0.5)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = grain
    noise.inputs["Detail"].default_value = 6
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    # woven look: crossed waves on top of the grain
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = grain * 0.18
    wave.inputs["Distortion"].default_value = 2.0
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    mixn = nt.nodes.new("ShaderNodeMixRGB")
    mixn.inputs["Fac"].default_value = 0.5
    nt.links.new(noise.outputs["Fac"], mixn.inputs["Color1"])
    nt.links.new(wave.outputs["Fac"], mixn.inputs["Color2"])
    bn = nt.nodes.new("ShaderNodeBump")
    bn.inputs["Strength"].default_value = bump
    bn.inputs["Distance"].default_value = 0.002
    nt.links.new(mixn.outputs["Color"], bn.inputs["Height"])
    nt.links.new(bn.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_plain(name, hexcol, rough=0.5, metal=0.0, coat=0.0, emissive=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*hex_rgb(hexcol), 1.0)
    setin(b, "Roughness", rough)
    setin(b, "Metallic", metal)
    setin(b, "Coat Weight", coat)
    return m


def mat_decal(name, image_path, embroidery=False, rough=0.72):
    """Logo decal: the image's alpha cuts the shape. `embroidery` adds thread relief and a sheen."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.load(image_path)
    img.alpha_mode = "STRAIGHT"
    tex.image = img
    tex.interpolation = "Cubic"
    tex.extension = "CLIP"
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    nt.links.new(tr.outputs["BSDF"], mix.inputs[1])
    nt.links.new(bsdf.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    setin(bsdf, "Roughness", rough)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 900
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    bn = nt.nodes.new("ShaderNodeBump")
    if embroidery:
        setin(bsdf, "Roughness", 0.42)
        setin(bsdf, "Sheen Weight", 0.6)
        wave = nt.nodes.new("ShaderNodeTexWave")
        wave.wave_type = "BANDS"
        wave.bands_direction = "DIAGONAL"
        wave.inputs["Scale"].default_value = 620
        wave.inputs["Distortion"].default_value = 1.5
        nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
        h = nt.nodes.new("ShaderNodeMath")
        h.operation = "MULTIPLY_ADD"
        h.inputs[1].default_value = 0.35
        nt.links.new(wave.outputs["Fac"], h.inputs[0])
        nt.links.new(tex.outputs["Alpha"], h.inputs[2])
        nt.links.new(h.outputs["Value"], bn.inputs["Height"])
        bn.inputs["Strength"].default_value = 0.9
        bn.inputs["Distance"].default_value = 0.0025
    else:
        nt.links.new(noise.outputs["Fac"], bn.inputs["Height"])
        bn.inputs["Strength"].default_value = 0.12
        bn.inputs["Distance"].default_value = 0.001
    nt.links.new(bn.outputs["Normal"], bsdf.inputs["Normal"])
    return m, img


def mat_image_flat(name, image_path, rough=0.6):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = bpy.data.images.load(image_path)
    tex.image = img
    nt.links.new(tex.outputs["Color"], b.inputs["Base Color"])
    setin(b, "Roughness", rough)
    return m, img


# ---------------------------------------------------------------- geometry
def chaikin(pts, passes=2):
    for _ in range(passes):
        out = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        pts = out
    return pts


def mirror_poly(right):
    """`right` runs from the centre line (x=0) at the top down to the centre line at the bottom. Returns the closed outline."""
    left = [(-x, z) for x, z in reversed(right) if abs(x) > 1e-6]
    return list(right) + left


def dist_to_outline(pts_xz, outline):
    """Distance (same unit as the inputs) from each point to the closed polyline `outline`."""
    P = np.asarray(pts_xz, dtype=np.float64)
    O = np.asarray(outline, dtype=np.float64)
    A, B = O, np.roll(O, -1, axis=0)
    AB = B - A
    L2 = np.maximum((AB**2).sum(1), 1e-12)
    out = np.empty(len(P))
    for s in range(0, len(P), 8000):
        p = P[s : s + 8000, None, :]
        t = np.clip(((p - A[None]) * AB[None]).sum(2) / L2[None], 0, 1)
        proj = A[None] + t[..., None] * AB[None]
        out[s : s + 8000] = np.sqrt(((p - proj) ** 2).sum(2)).min(1)
    return out


def activate(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def apply_mod(o, mod):
    activate(o)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def make_sheet(name, outline_in, thick_in=0.5, voxel_in=0.14, inflate_in=0.9, wrinkle_in=0.22, mat=None, seed=1, edge_in=3.5, smooth=5):
    """A pillow-shaped fabric piece in the XZ plane (front faces -Y) from an outline in inches.

    Flat polygon -> solidify -> voxel remesh (even quads) -> push each vertex out by a smooth function of its distance
    to the outline (inflate) plus low-frequency wrinkles -> smooth. Returns the object."""
    bm = bmesh.new()
    vs = [bm.verts.new((x * S, 0, z * S)) for x, z in outline_in]
    bm.faces.new(vs)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    sol = o.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = thick_in * S
    sol.offset = 0
    apply_mod(o, sol)
    rm = o.modifiers.new("rm", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = voxel_in * S
    apply_mod(o, rm)

    n = len(o.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    xin, zin, y = co[:, 0] / S, co[:, 2] / S, co[:, 1]
    d = dist_to_outline(np.stack([xin, zin], 1), outline_in)
    u = np.clip(d / edge_in, 0, 1)
    h = inflate_in * (u * u * (3 - 2 * u))  # smoothstep: flat rim, full puff inside
    h = np.maximum(h, 0.0)
    rng = np.random.default_rng(seed)
    w = np.zeros(n)
    for _ in range(7):
        ang = rng.uniform(0, math.pi)
        k = rng.uniform(0.25, 0.7)
        ph = rng.uniform(0, 6.28)
        amp = rng.uniform(0.3, 1.0)
        w += amp * np.sin(k * (xin * math.cos(ang) + zin * math.sin(ang)) + ph)
    w *= wrinkle_in / 3.0 * np.clip(d / 1.2, 0, 1)
    off = (thick_in / 2.0 + h + w) * S
    co[:, 1] = np.where(y < 0, -off, off)
    o.data.vertices.foreach_set("co", co.reshape(-1))
    o.data.update()
    if smooth:
        sm = o.modifiers.new("sm", "SMOOTH")
        sm.factor = 0.5
        sm.iterations = smooth
        apply_mod(o, sm)
    activate(o)
    bpy.ops.object.shade_smooth()
    if mat:
        o.data.materials.append(mat)
    return o


def make_cord(name, pts_in, radius_in, mat, flatten=1.0):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius_in * S
    cu.bevel_resolution = 4
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts_in) - 1)
    for p, (x, y, z) in zip(sp.points, pts_in):
        p.co = (x * S, y * S, z * S, 1)
    o = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(o)
    o.scale = (1, flatten, 1)
    o.data.materials.append(mat)
    return o


def smooth_curve(ctrl, n=40):
    """Catmull-Rom through 3D control points."""
    P = [np.array(c, dtype=float) for c in ctrl]
    P = [P[0]] + P + [P[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(n // (len(ctrl) - 1)):
            t = k / (n // (len(ctrl) - 1))
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3))
    out.append(P[-2])
    return [tuple(p) for p in out]


def make_grid(name, w_m, h_m, res_u=96, res_v=96, warp=None):
    """Grid in the XZ plane facing -Y, centred on the origin, UVs 0..1. `warp(x, z, u, v) -> (x, y, z)` may bend it."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    verts = []
    for j in range(res_v + 1):
        row = []
        for i in range(res_u + 1):
            u, v = i / res_u, j / res_v
            x, z = (u - 0.5) * w_m, (v - 0.5) * h_m
            row.append(bm.verts.new(warp(x, z, u, v) if warp else (x, 0.0, z)))
        verts.append(row)
    for j in range(res_v):
        for i in range(res_u):
            f = bm.faces.new((verts[j][i], verts[j][i + 1], verts[j + 1][i + 1], verts[j + 1][i]))
            for lp in f.loops:
                idx = [(a, b) for a in range(2) for b in range(2)]
                vv = lp.vert
                for (jj, ii) in ((j, i), (j, i + 1), (j + 1, i + 1), (j + 1, i)):
                    if verts[jj][ii] == vv:
                        lp[uv].uv = (ii / res_u, jj / res_v)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    return o


def make_decal_plane(name, w_in, h_in, cx_in, cy, cz_in, mat, res=96):
    """Subdivided plane facing -Y, w x h inches, centred at (cx, cy[m], cz). UVs 0..1 cover the whole plane."""
    o = make_grid(name, w_in * S, h_in * S, res, res)
    o.location = (cx_in * S, cy, cz_in * S)
    o.data.materials.append(mat)
    o.visible_shadow = False
    return o


def shrinkwrap_project(o, target, offset_m=0.0007, axis="Y", positive=True):
    sw = o.modifiers.new("sw", "SHRINKWRAP")
    sw.target = target
    sw.wrap_method = "PROJECT"
    sw.use_project_y = True
    sw.use_negative_direction = not positive
    sw.use_positive_direction = positive
    sw.cull_face = "OFF"
    sw.offset = offset_m
    apply_mod(o, sw)
    activate(o)
    bpy.ops.object.shade_smooth()


def fit_contain(img_w, img_h, area_w, area_h, scale=1.0):
    k = min(area_w / img_w, area_h / img_h) * scale
    return img_w * k, img_h * k


# ---------------------------------------------------------------- studio
def cyclorama(name, mat, wall_y, floor_z, half_w=3.0, radius=0.35, height=3.0, depth=3.0):
    """Floor + curved coving + wall as one sweep, so the backdrop has no seam line."""
    prof = []
    prof.append((-depth, floor_z))
    prof.append((wall_y - radius, floor_z))
    for i in range(1, 13):
        a = (math.pi / 2) * i / 12
        prof.append((wall_y - radius + radius * math.sin(a), floor_z + radius - radius * math.cos(a)))
    prof.append((wall_y, floor_z + height))
    bm = bmesh.new()
    rows = []
    for y, z in prof:
        rows.append([bm.verts.new((-half_w, y, z)), bm.verts.new((half_w, y, z))])
    for a, b in zip(rows[:-1], rows[1:]):
        bm.faces.new((a[0], a[1], b[1], b[0]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(mat)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def add_area(name, loc, target, energy, size, color=(1, 1, 1), shape="SQUARE"):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.size = size
    ld.shape = shape
    ld.color = color
    o = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(o)
    o.location = loc
    d = Vector(target) - Vector(loc)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return o


def bbox_world(objs):
    pts = []
    for o in objs:
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    xs, ys, zs = zip(*[(p.x, p.y, p.z) for p in pts])
    lo, hi = Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))
    return lo, hi


def frame_camera(cam, scene, center, dir_vec, pts, lens=70.0, margin=0.1, aim=None):
    """Place `cam` on the ray from `center` along `dir_vec` (unit) far enough that every point in `pts` fits."""
    cam.data.lens = lens
    cam.data.sensor_width = 36.0
    cam.data.sensor_fit = "AUTO"
    d = Vector(dir_vec).normalized()
    tgt = Vector(aim) if aim is not None else Vector(center)
    lo_d, hi_d = 0.05, 12.0
    from bpy_extras.object_utils import world_to_camera_view

    for _ in range(26):
        mid = (lo_d + hi_d) / 2
        cam.location = tgt + d * mid
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        ok = True
        for p in pts:
            v = world_to_camera_view(scene, cam, Vector(p))
            if v.z <= 0 or v.x < margin or v.x > 1 - margin or v.y < margin or v.y > 1 - margin:
                ok = False
                break
        if ok:
            hi_d = mid
        else:
            lo_d = mid
    cam.location = tgt + d * hi_d
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()


def corners(lo, hi):
    return [(x, y, z) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
