"""Procedural product models (inches, M-size blank). Each builder returns a Product describing the meshes and where the
provider's print area sits on the model, so the logo is placed at true print scale.

Models are built in the XZ plane facing the camera at -Y (garments, tote, poster) or standing on the floor (mug, cap)."""
import math
from dataclasses import dataclass, field

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from common import (S, activate, apply_mod, chaikin, hex_rgb, make_cord, make_grid, make_sheet, mat_fabric, mat_plain, mirror_poly,
                    smooth_curve, mix_hex, lum)


@dataclass
class Product:
    kind: str
    objs: list = field(default_factory=list)
    target: object = None  # mesh the logo decal is projected onto
    anchor: tuple = (0.0, 0.0)  # print-area centre (x, z) in inches
    wall_gap_m: float = 0.22  # distance between the product and the backdrop wall
    on_floor: bool = False
    label_obj: object = None
    label_center: tuple = None  # (x_in, z_in) of the inside label on the back neck
    label_w_in: float = 1.7
    wrap: dict = None  # mug: cylinder radius etc.
    embroidery: bool = False
    height_in: float = 28.0
    notes: list = field(default_factory=list)


def _poly_tee(width=10.0, sleeve_end=(17.6, 19.2, 15.4, 15.2)):
    ox, oz, ix, iz = sleeve_end
    right = [(0, 24.3), (1.9, 24.0), (3.3, 25.0), (3.9, 26.6), (9.4, 25.9), (10.6, 25.0), (ox, oz), (ix, iz), (10.0, 16.8), (width, 15.6), (width, 0.0), (0, 0.0)]
    return mirror_poly(right)


def _poly_long(width, neck_bottom, shoulder_z, sleeve):
    """Long-sleeve body: sleeve is (outer_end(x,z), inner_end(x,z), armpit(x,z))."""
    (ox, oz), (ix, iz), (ax, az) = sleeve
    right = [(0, neck_bottom), (1.9, neck_bottom - 0.3), (3.3, neck_bottom + 0.9), (3.9, shoulder_z + 1.4), (9.6, shoulder_z + 0.3), (10.8, shoulder_z - 0.7),
             (ox, oz), (ix, iz), (ax, az), (width, az - 1.6), (width, 0.0), (0, 0.0)]
    return mirror_poly(right)


def _smooth_poly(poly, passes=2):
    return chaikin(poly, passes)


def _rect(cx, cz, w, h, r=0.3):
    """Rounded rectangle outline (corner radius r in inches)."""
    r = min(r, w / 2 - 0.01, h / 2 - 0.01)
    pts = []
    for ccx, ccz, a0 in ((cx + w / 2 - r, cz + h / 2 - r, 0), (cx - w / 2 + r, cz + h / 2 - r, 90), (cx - w / 2 + r, cz - h / 2 + r, 180), (cx + w / 2 - r, cz - h / 2 + r, 270)):
        for k in range(0, 7):
            a = math.radians(a0 + 90 * k / 6)
            pts.append((ccx + r * math.cos(a), ccz + r * math.sin(a)))
    return pts


def _cuff(mat, outer, inner, sgn, length=2.6):
    """A ribbed cuff band across the sleeve end: `outer`/`inner` are the sleeve end corners (x, z) of the +X sleeve."""
    dx, dz = inner[0] - outer[0], inner[1] - outer[1]
    width = math.hypot(dx, dz)
    ux, uz = dx / width, dz / width
    nx, nz = uz, -ux  # along the sleeve, toward the shoulder (positive z)
    if nz < 0:
        nx, nz = -nx, -nz
    mx, mz = (outer[0] + inner[0]) / 2 + nx * length / 2, (outer[1] + inner[1]) / 2 + nz * length / 2
    c = make_sheet("cuff", _rect(0, 0, width, length, 0.4), thick_in=0.4, voxel_in=0.1, inflate_in=0.45, wrinkle_in=0.02, mat=mat, edge_in=1.0, smooth=3)
    ang = math.atan2(uz, ux)  # in-plane angle of the cuff's long axis (+X sleeve)
    c.rotation_euler[1] = -ang if sgn > 0 else ang
    c.location = (sgn * mx * S, -0.7 * S, mz * S)
    return c


def _shift_y(o, y_in):
    o.location.y += y_in * S


def _label_back_neck(P, shape_pts, mat, z_center):
    """The inside back of the collar, seen through the neck opening. The label is placed on it by the scene."""
    back = make_sheet("backneck", chaikin(shape_pts, 2), thick_in=0.2, voxel_in=0.07, inflate_in=0.2, wrinkle_in=0.03, mat=mat, edge_in=1.5, smooth=6)
    _shift_y(back, 0.55)
    P.objs.append(back)
    P.label_center = (0.0, z_center)
    return back


def build_tee(color, long_sleeve=False, heavy=False):
    P = Product("tee", height_in=28.0)
    fab = mat_fabric("fabric", color, grain=700 if not heavy else 520, bump=0.4 if heavy else 0.32)
    rib = mat_fabric("rib", color, grain=1400, bump=0.8, rough=0.9)
    if long_sleeve:
        poly = _poly_long(10.0, 24.3, 25.2, ((20.6, 6.2), (16.6, 4.6), (10.0, 17.6)))
        P.height_in = 28.0
    else:
        poly = _poly_tee()
    body = make_sheet("body", _smooth_poly(poly), thick_in=0.55, voxel_in=0.1, inflate_in=0.9, mat=fab, seed=3)
    P.objs.append(body)
    P.target = body
    # collar: ribbed band along the front neckline
    neck = [(-3.7, 26.1), (-3.2, 25.0), (-1.9, 24.0), (0, 23.75), (1.9, 24.0), (3.2, 25.0), (3.7, 26.1)]
    ctrl = [(x, -0.55 - 0.75, z) for x, z in neck]
    P.objs.append(make_cord("collar", smooth_curve(ctrl, 56), 0.42, rib, flatten=0.55))
    back = _label_back_neck(P, [(-3.9, 26.8), (-3.3, 25.0), (-1.9, 23.9), (0, 23.7), (1.9, 23.9), (3.3, 25.0), (3.9, 26.8), (0, 27.4)], mat_fabric("inner", mix_hex(color, "#000000", 0.18), grain=700), 26.3)
    # hems
    P.objs.append(_hem(poly, rib, long_sleeve, 10.0))
    P.anchor = (0.0, 23.3)  # top of the print area, 1 in below the collar; centre is set by the scene from the area height
    P.notes.append("anchor_top")
    return P


def _hem(poly, rib, long_sleeve, w=10.0):
    h = make_sheet("hem", _rect(0, 1.1, 2 * w - 0.4, 2.1), thick_in=0.3, voxel_in=0.13, inflate_in=0.35, wrinkle_in=0.02, mat=rib, edge_in=1.0, smooth=1)
    _shift_y(h, -0.35)
    return h


def build_crewneck(color):
    P = Product("crewneck", height_in=27.0)
    fab = mat_fabric("fabric", color, grain=560, bump=0.42)
    rib = mat_fabric("rib", color, grain=1500, bump=0.9)
    poly = _poly_long(11.0, 24.6, 25.4, ((21.4, 6.6), (17.2, 4.8), (10.9, 17.0)))
    body = make_sheet("body", _smooth_poly(poly), thick_in=0.7, voxel_in=0.15, inflate_in=1.1, mat=fab, seed=5)
    P.objs.append(body)
    P.target = body
    neck = [(-3.9, 26.6), (-3.4, 25.3), (-2.0, 24.2), (0, 23.8), (2.0, 24.2), (3.4, 25.3), (3.9, 26.6)]
    ctrl = [(x, -0.7 - 1.0, z) for x, z in neck]
    P.objs.append(make_cord("collar", smooth_curve(ctrl, 56), 0.6, rib, flatten=0.55))
    _label_back_neck(P, [(-4.0, 27.5), (-3.4, 25.1), (-2.0, 24.0), (0, 23.7), (2.0, 24.0), (3.4, 25.1), (4.0, 27.5), (0, 28.1)], mat_fabric("inner", mix_hex(color, "#000000", 0.18), grain=560), 26.3)
    h = make_sheet("hem", _rect(0, 1.2, 21.8, 2.4), thick_in=0.4, voxel_in=0.13, inflate_in=0.4, wrinkle_in=0.02, mat=rib, edge_in=1.0, smooth=1)
    _shift_y(h, -0.5)
    P.objs.append(h)
    for sgn in (1, -1):  # cuffs
        P.objs.append(_cuff(rib, (21.4, 6.6), (17.2, 4.8), sgn))
    P.anchor = (0.0, 22.6)
    P.notes.append("anchor_top")
    return P


def build_hoodie(color):
    P = Product("hoodie", height_in=34.0)
    fab = mat_fabric("fabric", color, grain=520, bump=0.45)
    rib = mat_fabric("rib", color, grain=1500, bump=0.9)
    dark = mat_fabric("hoodin", mix_hex(color, "#000000", 0.35), grain=520, bump=0.4)
    poly = _poly_long(11.3, 25.0, 25.2, ((21.6, 6.2), (17.3, 4.4), (11.2, 17.2)))
    body = make_sheet("body", _smooth_poly(poly), thick_in=0.8, voxel_in=0.16, inflate_in=1.3, mat=fab, seed=7)
    P.objs.append(body)
    P.target = body
    # hood: outer shell behind the shoulders, dark lining in the opening, rolled front edge
    hood = [(0, 34.2), (3.2, 33.6), (5.6, 31.0), (6.4, 27.5), (5.8, 25.0), (4.0, 24.6), (0, 24.4)]
    shell = make_sheet("hoodshell", chaikin(mirror_poly(hood), 2), thick_in=0.9, voxel_in=0.17, inflate_in=1.4, mat=fab, seed=9)
    _shift_y(shell, 1.7)
    P.objs.append(shell)
    lin = [(0, 32.0), (2.6, 31.4), (4.5, 29.4), (4.7, 26.8), (3.8, 25.2), (0, 24.6)]
    lining = make_sheet("hoodlining", chaikin(mirror_poly(lin), 2), thick_in=0.3, voxel_in=0.15, inflate_in=0.2, wrinkle_in=0.05, mat=dark, edge_in=1.5, smooth=1)
    _shift_y(lining, 1.0)
    P.objs.append(lining)
    rim = [(-4.8, 26.5), (-4.6, 29.3), (-2.8, 31.7), (0, 32.4), (2.8, 31.7), (4.6, 29.3), (4.8, 26.5), (3.9, 25.0)]
    P.objs.append(make_cord("hoodrim", smooth_curve([(x, -0.35 - 1.1, z) for x, z in rim], 80), 0.55, fab, flatten=0.8))
    # neckline notch lip + back neck for the label
    _label_back_neck(P, [(-4.0, 27.4), (-3.5, 25.2), (-2.0, 24.2), (0, 23.9), (2.0, 24.2), (3.5, 25.2), (4.0, 27.4), (0, 28.0)], dark, 26.2)
    # kangaroo pocket
    pocket = [(-8.2, 3.2), (-7.4, 11.0), (-3.0, 11.4), (3.0, 11.4), (7.4, 11.0), (8.2, 3.2), (0, 2.8)]
    pk = make_sheet("pocket", chaikin(pocket, 3), thick_in=0.5, voxel_in=0.15, inflate_in=0.6, wrinkle_in=0.05, mat=fab, edge_in=1.2, smooth=2)
    _shift_y(pk, -1.15)
    P.objs.append(pk)
    h = make_sheet("hem", _rect(0, 1.2, 22.4, 2.4), thick_in=0.4, voxel_in=0.13, inflate_in=0.4, wrinkle_in=0.02, mat=rib, edge_in=1.0, smooth=1)
    _shift_y(h, -0.6)
    P.objs.append(h)
    for sgn in (1, -1):
        P.objs.append(_cuff(rib, (21.6, 6.2), (17.3, 4.4), sgn))
    cord = mat_plain("cord", "#E8E3D8", rough=0.7)
    for sgn in (1, -1):
        pts = smooth_curve([(sgn * 1.6, -1.9, 24.4), (sgn * 1.9, -2.0, 21.0), (sgn * 1.8, -2.0, 17.4), (sgn * 2.2, -2.0, 14.0)], 30)
        P.objs.append(make_cord("string", pts, 0.16, cord))
        tip = mat_plain("aglet", "#B8B8B8", rough=0.3, metal=0.9)
        P.objs.append(make_cord("aglet", [(sgn * 2.2, -2.0, 14.4), (sgn * 2.25, -2.0, 13.0)], 0.2, tip))
    P.anchor = (0.0, 23.2)
    P.notes.append("anchor_top")
    return P


def build_tote(color):
    P = Product("tote", height_in=25.0)
    fab = mat_fabric("canvas", color, grain=380, bump=0.55, rough=0.92)
    poly = _rect(0, 8.0, 15.0, 16.0, r=0.9)
    body = make_sheet("body", poly, thick_in=1.0, voxel_in=0.15, inflate_in=0.9, wrinkle_in=0.3, mat=fab, edge_in=2.6, seed=11)
    P.objs.append(body)
    P.target = body
    for k, y in enumerate((-0.7, 0.7)):
        pts = smooth_curve([(-4.4, y, 14.5), (-4.6, y - 0.3 * (1 if y < 0 else 1), 19.0), (-3.2, y - 0.2, 24.0), (0, y - 0.2, 25.4), (3.2, y - 0.2, 24.0), (4.6, y - 0.3, 19.0), (4.4, y, 14.5)], 70)
        P.objs.append(make_cord("strap", pts, 0.55, fab, flatten=0.35))
    P.anchor = (0.0, 14.0)
    P.notes.append("anchor_top")
    return P


def build_poster(color):
    P = Product("poster", height_in=12.0)
    paper = mat_plain("paper", color if color else "#F4F2EC", rough=0.62)
    # sized later from the print area by the scene; here a unit placeholder replaced in scene.build_poster_sized
    return P


def build_poster_sized(color, w_in, h_in):
    P = Product("poster", height_in=h_in)
    paper = mat_plain("paper", color or "#F4F2EC", rough=0.6)

    def warp(x, z, u, v):
        curl = 0.0075 * math.sin(u * 2.6) * (1 - v) + 0.004 * math.sin(v * 3.1 + 0.7)
        return (x, curl, z)

    o = make_grid("poster", w_in * S, h_in * S, 120, 90, warp)
    o.data.materials.append(paper)
    sol = o.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.012 * S * 10
    apply_mod(o, sol)
    activate(o)
    bpy.ops.object.shade_smooth()
    o.location = (0, 0, (h_in / 2 + 6) * S)
    P.objs.append(o)
    P.target = o
    P.anchor = (0.0, h_in / 2 + 6)
    P.wall_gap_m = 0.02
    P.notes.append("anchor_center")
    return P


def build_mug(color, mug_w_in=9.0, mug_h_in=3.5):
    P = Product("mug", on_floor=True, height_in=3.8)
    P.wall_gap_m = 0.30
    R, H = 1.6, 3.7
    glaze = mat_plain("glaze", color or "#FFFFFF", rough=0.12, coat=1.0)
    inner = mat_plain("inside", color or "#FFFFFF", rough=0.15, coat=1.0)
    prof = [(0.0, 0.0), (1.45, 0.0), (1.57, 0.08), (R, 0.3), (R, H - 0.1), (R - 0.05, H), (R - 0.18, H), (R - 0.2, H - 0.12), (R - 0.22, 0.45), (0.0, 0.42)]
    bm = bmesh.new()
    vs = [bm.verts.new((x * S, 0, z * S)) for x, z in prof]
    for a, b in zip(vs[:-1], vs[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], cent=(0, 0, 0), axis=(0, 0, 1), angle=math.radians(359.99), steps=96, use_merge=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new("mug")
    bm.to_mesh(me)
    bm.free()
    cup = bpy.data.objects.new("mug", me)
    bpy.context.collection.objects.link(cup)
    cup.data.materials.append(glaze)
    for p in cup.data.polygons:
        p.use_smooth = True
    P.objs.append(cup)
    P.target = cup
    # handle: D-shaped bevelled curve on the right (+X) side
    pts = []
    for i in range(0, 25):
        t = math.pi * i / 24
        pts.append((R - 0.15 + 1.35 * math.sin(t) * (1.0 if i else 1.0), 0.0, 1.95 + 1.2 * math.cos(t)))
    hnd = make_cord("handle", [(x, y, z) for x, y, z in pts], 0.22, glaze)
    P.objs.append(hnd)
    P.wrap = {"R": R, "H": H, "w_in": mug_w_in, "h_in": mug_h_in, "zc": 1.95}
    return P


def build_cap(color, flat=False, snap=False):
    P = Product("cap", on_floor=True, height_in=5.5, embroidery=True)
    P.wall_gap_m = 0.28
    fab = mat_fabric("twill", color, grain=420, bump=0.12, rough=0.9)
    # seam relief: 6 panels, a seam centred on the front
    m = fab
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    at = nt.nodes.new("ShaderNodeMath")
    at.operation = "ARCTAN2"
    nt.links.new(sep.outputs["Y"], at.inputs[0])
    nt.links.new(sep.outputs["X"], at.inputs[1])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = 3.0
    nt.links.new(at.outputs["Value"], mul.inputs[0])
    cs = nt.nodes.new("ShaderNodeMath")
    cs.operation = "COSINE"
    nt.links.new(mul.outputs["Value"], cs.inputs[0])
    ab = nt.nodes.new("ShaderNodeMath")
    ab.operation = "ABSOLUTE"
    nt.links.new(cs.outputs["Value"], ab.inputs[0])
    sm = nt.nodes.new("ShaderNodeMapRange")
    sm.inputs["From Min"].default_value = 0.0
    sm.inputs["From Max"].default_value = 0.07
    nt.links.new(ab.outputs["Value"], sm.inputs["Value"])
    sbn = nt.nodes.new("ShaderNodeBump")
    sbn.inputs["Strength"].default_value = 0.55
    sbn.inputs["Distance"].default_value = 0.003
    nt.links.new(sm.outputs["Result"], sbn.inputs["Height"])
    prev = b.inputs["Normal"].links[0].from_node
    nt.links.new(prev.outputs["Normal"], sbn.inputs["Normal"])
    nt.links.new(sbn.outputs["Normal"], b.inputs["Normal"])

    rx, ry, rz = (3.55, 4.1, 4.3 if snap else 3.6)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=1.0)
    for v in bm.verts[:]:
        pass
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.02], context="VERTS")
    for v in bm.verts:
        v.co = Vector((v.co.x * rx * S, v.co.y * ry * S, v.co.z * rz * S))
        if snap:  # structured crown: flatter top and straight front
            v.co.z = min(v.co.z, rz * S * 0.96)
    me = bpy.data.meshes.new("crown")
    bm.to_mesh(me)
    bm.free()
    crown = bpy.data.objects.new("crown", me)
    bpy.context.collection.objects.link(crown)
    crown.data.materials.append(fab)
    sol = crown.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.12 * S
    apply_mod(crown, sol)
    activate(crown)
    bpy.ops.object.shade_smooth()
    P.objs.append(crown)
    P.target = crown
    # brim: a fan in front of the crown (+-72 deg), growing out from the crown's own ellipse, curved down at the edges
    n_u, n_v = 40, 10
    bm = bmesh.new()
    rows = []
    reach_y, reach_x = (3.3 if not flat else 3.0), 1.5
    for j in range(n_v + 1):
        t = j / n_v
        row = []
        for i in range(n_u + 1):
            a = math.radians(-72 + 144 * i / n_u)
            x = (rx + t * reach_x) * math.sin(a)
            y = -(ry + t * reach_y) * math.cos(a)
            curve = 0.0 if flat else (0.55 * t * t + 0.5 * t * t * abs(math.sin(a)))
            row.append(bm.verts.new((x * S, y * S, (0.12 - curve - (0.1 * t if flat else 0.0)) * S)))
        rows.append(row)
    for j in range(n_v):
        for i in range(n_u):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    me = bpy.data.meshes.new("brim")
    bm.to_mesh(me)
    bm.free()
    brim = bpy.data.objects.new("brim", me)
    bpy.context.collection.objects.link(brim)
    brim.data.materials.append(fab)
    s2 = brim.modifiers.new("sol", "SOLIDIFY")
    s2.thickness = 0.22 * S
    apply_mod(brim, s2)
    activate(brim)
    bpy.ops.object.shade_smooth()
    P.objs.append(brim)
    # button
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.38 * S)
    me = bpy.data.meshes.new("button")
    bm.to_mesh(me)
    bm.free()
    btn = bpy.data.objects.new("button", me)
    bpy.context.collection.objects.link(btn)
    btn.location = (0, 0, rz * S * (0.96 if snap else 1.0))
    btn.data.materials.append(fab)
    P.objs.append(btn)
    # embroidery sits on the front panel; the scene projects the logo along +Y from the front
    P.anchor = (0.0, rz * 0.5)
    return P
