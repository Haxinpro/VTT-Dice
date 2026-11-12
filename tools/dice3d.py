# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Haxinpro
"""Renders one realistic die picture (black marble, engraved gold numbers) with Blender / Cycles.

Run headless (always cap the threads):
  blender -b -t 8 -P dice3d.py -- --die d8 --result 1 --seed 1 --out d8_1.png [--res 1024 --samples 128]
  blender -b -t 8 -P dice3d.py -- --die d8 --glb d8.glb [--tex 2048]     (web model + d8.faces.json, no render)
  blender -b -t 8 -P dice3d.py -- --die d4 --result 2 --out d4_2.png [--pose edge|face --tilt 25]
  blender -b -t 8 -P dice3d.py -- --die d6 --result 3 --out d6_3.png [--tilt -35 --mirror]     (rolled face on top, seen from above)
  blender -b -t 8 -P dice3d.py -- --die d10 --result 7 --out d10_7.png [--tilt -40 --mirror]   (digits 0-9, the 0 face counts as 10)
  blender -b -t 8 -P dice3d.py -- --die d10 --glb d10.glb                                      (web model + d10.faces.json)
  blender -b -t 8 -P dice3d.py -- --die d10 [--mirror] --faces d10.faces.json    (only the .faces.json: no scene, font, render or bake)
  blender -b -t 8 -P dice3d.py -- --die d10t --result 7 --out d10t_70.png [--tilt -40 --mirror]   (percentile tens die 00-90; --result is the d10 face 0-9, so 7 shows "70")
  blender -b -t 8 -P dice3d.py -- --die d10t --glb d10t.glb                                    (web model + d10t.faces.json: text "00".."90", value 0..90)
  blender -b -t 8 -P dice3d.py -- --die d12 --result 5 --out d12_5.png [--tilt -60 --mirror]   (pentagon faces, opposites add to 13)
  blender -b -t 8 -P dice3d.py -- --die d12 --glb d12.glb                                      (web model + d12.faces.json)
  blender -b -t 8 -P dice3d.py -- --die d20 --result 17 --out d20_17.png [--tilt -75 --mirror]   (triangle faces, opposites add to 21)
  blender -b -t 8 -P dice3d.py -- --die d20 --glb d20.glb                                      (web model + d20.faces.json)
  blender -b -t 8 -P dice3d.py -- --die d100 --result 73 --out d100_73.png [--tilt -60]        (100 small flat faces with grooves, opposites add to 101)
  blender -b -t 8 -P dice3d.py -- --die d100 --glb d100.glb                                    (web model + d100.faces.json, physics "sphere"; the boolean is slow)
  blender -b -t 8 -P dice3d.py -- --die d20 --results 1-20 --out results/d20/{n}.png            (batch: scene built once, one picture per result)
  blender -b -t 8 -P dice3d.py -- --die d10 --results 0-9 --out results/d10/{n}.png             (--results: "1-20", "1,5,9", "0-9,12" or "all" = every face / corner)
  blender -b -t 8 -P dice3d.py -- --die d100 --results all --out results/d100/{n}.png --device cpu   (--device auto (default: OPTIX, then CUDA, else CPU), cpu, gpu)
  blender -b -t 8 -P dice3d.py -- --die d20 --glb d20.glb [--no-mark]     (the maker's mark "Haxinpro" is cut into the gold of the lowest number by default; --no-mark skips it)

In batch mode {n} in --out is the face's printed text (d10t: "30") or else its number; only that result's digits are bright gold,
the marble seed (--seed) is the same for the whole batch (one physical die).

The die is built from DICE (plain data: vertices, faces, numbers, "up" vertex per face), so a new die is one more
table entry. The rolled face is turned to face the camera with its "up" vertex pointing up, then tilted back a little
so the face below it shows. A die with "read": "vertex" (the d4) is read at its top corner instead: that corner points
up and --pose picks what faces the camera (an edge or a face touching it). Output: square PNG with alpha (transparent
background, no ground)."""
import argparse
import functools
import itertools
import json
import math
import random
import struct
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from bpy_extras.object_utils import world_to_camera_view

# --------------------------------------------------------------------------- die data

def octa_faces(numbers, mirror=False):
    """Octahedron faces from {(sx, sy, sz): number}. Vertices 0..5 are +x,-x,+y,-y,+z,-z. Like a real d8, every digit's
    top points to its own face's tip on the z axis (+z apex for upper faces, -z apex for lower ones), so a face shown
    upright stands tip-up and the numbers on the other half of the die look upside down.
    "away": True would point the top away from the tip instead."""
    faces = []
    for (sx, sy, sz), number in numbers.items():
        if mirror:      # the other (mirror-image) handedness of the same numbering
            sx = -sx
        ids = (0 if sx > 0 else 1, 2 if sy > 0 else 3, 4 if sz > 0 else 5)
        faces.append({"verts": ids, "number": number, "up": ids[2], "away": False})
    return faces


T = 1 / math.sqrt(3)
TETRA_IDS = [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]    # wound counter-clockwise seen from outside


def tetra_faces(mirror=False):
    """Tetrahedron faces. Corner k (index k-1) owns number k; every face carries one label per corner, each with its
    top toward that corner. `mirror` swaps the numbers of corners 3 and 4 (the other handedness)."""
    nums = [1, 2, 4, 3] if mirror else [1, 2, 3, 4]
    return [{"verts": ids, "labels": [{"number": nums[i], "up": i} for i in ids]} for ids in TETRA_IDS]


# Cube corners: index = (0 if x>0 else 4) + (0 if y>0 else 2) + (0 if z>0 else 1). Each face: (corner quad, number, digit-top direction).
CUBE_VERTS = [(sx * T, sy * T, sz * T) for sx in (1, -1) for sy in (1, -1) for sz in (1, -1)]
CUBE_FACES = [
    ((0, 1, 3, 2), 1, (0, 0, 1)),   # +X
    ((0, 1, 5, 4), 2, (0, 0, 1)),   # +Y
    ((0, 2, 6, 4), 3, (0, 1, 0)),   # +Z
    ((1, 3, 7, 5), 4, (0, 1, 0)),   # -Z
    ((2, 3, 7, 6), 5, (0, 0, 1)),   # -Y
    ((4, 5, 7, 6), 6, (0, 0, 1)),   # -X
]


def cube_faces(mirror=False):
    """Cube faces. Digit tops come from a direction ("up_vec"), not a vertex. `mirror` swaps 2 and 5 (other handedness)."""
    swap = {2: 5, 5: 2} if mirror else {}
    return [{"verts": ids, "number": swap.get(n, n), "up_vec": up} for ids, n, up in CUBE_FACES]


D10_A = 1.0                                                     # pole height before scaling
D10_COS = math.cos(math.radians(36))
D10_B = D10_A * (1 - D10_COS) / (1 + D10_COS)                   # ring height (about 0.1056) that makes every kite flat
D10_UPPER = [2, 8, 0, 4, 6]     # kites around the top pole at azimuth 0, 72, 144, 216, 288
D10_LOWER = [5, 3, 7, 1, 9]     # kites around the bottom pole at azimuth 36, 108, ... (9 minus the upper face opposite)


def d10_verts():
    """Pentagonal trapezohedron, circumradius 1. Index 0/1 = poles (+z/-z); 2..6 = upper ring at azimuth 36+72k, z=+B;
    7..11 = lower ring at azimuth 72k, z=-B."""
    def ring(deg, z):
        return (math.cos(math.radians(deg)), math.sin(math.radians(deg)), z)
    pts = [(0.0, 0.0, D10_A), (0.0, 0.0, -D10_A)]
    pts += [ring(36 + 72 * k, D10_B) for k in range(5)] + [ring(72 * k, -D10_B) for k in range(5)]
    r = max(math.sqrt(x * x + y * y + z * z) for x, y, z in pts)     # the ring corners are a hair beyond the poles
    return [(x / r, y / r, z / r) for x, y, z in pts]


def d10_faces(mirror=False):
    """The ten kites. Upper kite k (azimuth 72k) = [pole, ring 72k-36, lower ring 72k, ring 72k+36]; lower kite k
    (azimuth 36+72k) = [pole, lower ring 72k, upper ring 36+72k, lower ring 72k+72]. Each digit's top points to its own
    pole. `mirror` numbers by azimuth -a instead of a (the other handedness); opposites still add to 9. The 0 reads 10."""
    faces = []
    for k in range(5):
        num_u = D10_UPPER[-k % 5 if mirror else k]
        num_l = D10_LOWER[(-k - 1) % 5 if mirror else k]
        faces.append({"verts": (0, 2 + (k - 1) % 5, 7 + k, 2 + k), "number": num_u, "up": 0, "away": False})
        faces.append({"verts": (1, 7 + k, 2 + k, 7 + (k + 1) % 5), "number": num_l, "up": 1, "away": False})
    for f in faces:
        if f["number"] == 0:
            f["value"] = 10         # shown as 0, read as 10
    return faces


def d10t_faces(mirror=False):
    """The same ten kites as the percentile (tens) die: numbering, digit tops and handedness are the d10's, but a face prints
    its tens ("00", "10" ... "90") as "text" and reads as n * 10 (the 00 as 0). "number" stays the d10 digit 0-9 (--result picks it)."""
    faces = d10_faces(mirror)
    for f in faces:
        f["text"], f["value"] = f"{f['number']}0", f["number"] * 10
    return faces


def poly_from_normals(normals):
    """Convex solid bounded by the planes n.x = 1, one per unit normal n. Returns (verts, faces): the vertices scaled to
    circumradius 1, and for every normal (same order) its vertex indices counter-clockwise seen from outside."""
    ns = [tuple(n) for n in normals]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    pts = []
    for a, b, c in itertools.combinations(ns, 3):       # three planes meet in one point (Cramer's rule)
        det = dot(a, cross(b, c))
        if abs(det) < 1e-9:
            continue
        bc, ca, ab = cross(b, c), cross(c, a), cross(a, b)
        p = tuple((bc[k] + ca[k] + ab[k]) / det for k in range(3))
        if all(dot(n, p) <= 1 + 1e-6 for n in ns) and all(math.dist(p, q) > 1e-6 for q in pts):
            pts.append(p)                               # a real corner: no plane cuts it off, and not seen before
    faces = []
    for n in ns:
        ids = [i for i, p in enumerate(pts) if abs(dot(n, p) - 1) < 1e-6]
        c = tuple(sum(pts[i][k] for i in ids) / len(ids) for k in range(3))
        axis = min(((1, 0, 0), (0, 1, 0), (0, 0, 1)), key=lambda e: abs(dot(e, n)))
        u = cross(n, axis)                              # u, w span the face plane and u x w = n: counter-clockwise from outside
        w = cross(n, u)
        ids.sort(key=lambda i: math.atan2(dot([pts[i][k] - c[k] for k in range(3)], w), dot([pts[i][k] - c[k] for k in range(3)], u)))
        faces.append(ids)
    r = max(math.sqrt(dot(p, p)) for p in pts)
    return [tuple(x / r for x in p) for p in pts], faces


def poly_from_near_normals(normals, max_deg=50.0):
    """poly_from_normals for many planes (the d100): same result and format, but only plane triples whose normals all lie within
    `max_deg` degrees of each other are intersected (a corner is made by neighbouring planes), instead of every triple. The
    solid is then checked and a ValueError is raised if it is not sound: every face a convex polygon of 4-8 corners, every edge
    shared by exactly two faces, Euler's V - E + F = 2."""
    ns = [tuple(n) for n in normals]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    cut = math.cos(math.radians(max_deg))
    near = [{j for j, m in enumerate(ns) if j != i and dot(n, m) > cut} for i, n in enumerate(ns)]
    pts = []
    for i, j in ((i, j) for i in range(len(ns)) for j in sorted(near[i]) if j > i):
        for k in sorted(near[i] & near[j]):         # i < j < k, all three pairs close
            if k <= j:
                continue
            a, b, c = ns[i], ns[j], ns[k]
            det = dot(a, cross(b, c))
            if abs(det) < 1e-9:
                continue
            bc, ca, ab = cross(b, c), cross(c, a), cross(a, b)
            p = tuple((bc[m] + ca[m] + ab[m]) / det for m in range(3))
            if all(dot(n, p) <= 1 + 1e-6 for n in ns) and all(math.dist(p, q) > 1e-6 for q in pts):
                pts.append(p)                           # a real corner: no plane cuts it off, and not seen before
    faces = []
    for n in ns:
        ids = [i for i, p in enumerate(pts) if abs(dot(n, p) - 1) < 1e-6]
        if len(ids) < 3:
            raise ValueError("a plane touches the solid in fewer than three corners")
        c = tuple(sum(pts[i][m] for i in ids) / len(ids) for m in range(3))
        axis = min(((1, 0, 0), (0, 1, 0), (0, 0, 1)), key=lambda e: abs(dot(e, n)))
        u = cross(n, axis)                              # u, w span the face plane and u x w = n: counter-clockwise from outside
        w = cross(n, u)
        ids.sort(key=lambda i: math.atan2(dot([pts[i][m] - c[m] for m in range(3)], w), dot([pts[i][m] - c[m] for m in range(3)], u)))
        faces.append(ids)
    edges = {}
    for ids in faces:
        for a, b in zip(ids, ids[1:] + ids[:1]):
            edges[frozenset((a, b))] = edges.get(frozenset((a, b)), 0) + 1
    def convex(n, ids):                                 # every turn along the outline bends the same way (toward n)
        q = [pts[i] for i in ids]
        turns = [dot(cross([y - x for x, y in zip(a, b)], [y - x for x, y in zip(b, c)]), n) for a, b, c in zip(q, q[1:] + q[:1], q[2:] + q[:2])]
        return all(t > 0 for t in turns)
    if not (all(4 <= len(ids) <= 8 for ids in faces) and all(v == 2 for v in edges.values())
            and len(pts) - len(edges) + len(faces) == 2 and all(convex(n, ids) for n, ids in zip(ns, faces))):
        raise ValueError("the planes do not bound a sound solid (face sizes, shared edges, Euler or convexity failed)")
    r = max(math.sqrt(dot(p, p)) for p in pts)
    return [tuple(x / r for x in p) for p in pts], faces


# d12: face = (ring, azimuth in degrees) -> number, reference layout of a common commercial d12; opposites add to 13 (lower ring at +180).
# The 12 is the +z face, the 1 the -z face; both rings sit at elevation atan(1/2) of a regular dodecahedron.
D12_NUM = {(1, 0): 9, (1, 72): 7, (1, 144): 8, (1, 216): 10, (1, 288): 11,
           (-1, 36): 3, (-1, 108): 2, (-1, 180): 4, (-1, 252): 6, (-1, 324): 5}


def d12_normals():
    """Unit face normals: +z, -z, then the ten ring faces in D12_NUM order."""
    e = math.atan(0.5)
    ring = [(math.cos(e) * math.cos(math.radians(a)), math.cos(e) * math.sin(math.radians(a)), r * math.sin(e)) for r, a in D12_NUM]
    return [(0.0, 0.0, 1.0), (0.0, 0.0, -1.0)] + ring


D12_VERTS, D12_IDS = poly_from_normals(d12_normals())


def d12_top(verts, ids, want):
    """Digit top of a pentagon: its one vertex most toward `want`; when an edge ties for it, the direction itself."""
    d = [sum(a * b for a, b in zip(verts[i], want)) for i in ids]
    top = [i for i, x in zip(ids, d) if x > max(d) - 1e-6]
    return {"up": top[0]} if len(top) == 1 else {"up_vec": want}


def d12_faces(mirror=False):
    """The twelve pentagons. Digit tops point toward their own half's pole, like the d8/d10: upper ring toward the 12, lower ring
    toward the 1 (both edges); the 12 toward +x (edge with the 9), the 1 toward -x (edge with the 4). One rule for both halves.
    `mirror` numbers by azimuth -a instead of a (the other handedness); opposites still add to 13."""
    faces = []
    for i, ids in enumerate(D12_IDS):
        if i < 2:
            number, want = (12, 1)[i], ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0))[i]
        else:
            ring, deg = list(D12_NUM)[i - 2]
            number, want = D12_NUM[(ring, -deg % 360 if mirror else deg)], (0.0, 0.0, float(ring))
        faces.append({"verts": tuple(ids), "number": number, "away": False, **d12_top(D12_VERTS, ids, want)})
    return faces


# d20: the 30 face adjacencies of the standard d20 layout (20 touches 2, 8, 14; opposites add to 21).
D20_EDGES = [(12, 10), (10, 8), (8, 16), (16, 6), (6, 9), (9, 11), (11, 13), (13, 5), (5, 15), (15, 12),      # band
             (12, 2), (10, 17), (8, 20), (16, 3), (6, 14), (9, 19), (11, 4), (13, 1), (5, 18), (15, 7),         # caps
             (2, 20), (20, 14), (14, 4), (4, 18), (18, 2), (17, 3), (3, 19), (19, 1), (1, 7), (7, 17)]          # rings A, B
D20_NEXT = {n: {b if a == n else a for a, b in D20_EDGES if n in (a, b)} for n in range(1, 21)}   # number -> its 3 neighbours


def d20_normals():
    """The 20 unit face normals = the corners of a regular dodecahedron, turned (one fixed rotation) so the first, the
    corner (1, 1, 1), lies exactly on +z: that face is the 20."""
    phi = (1 + math.sqrt(5)) / 2
    s = (1, -1)
    pts = [(a, b, c) for a in s for b in s for c in s]
    pts += [(0, a / phi, b * phi) for a in s for b in s] + [(a / phi, b * phi, 0) for a in s for b in s]
    pts += [(a * phi, 0, b / phi) for a in s for b in s]
    pts = [tuple(x / math.sqrt(sum(y * y for y in p)) for x in p) for p in pts]
    a = pts[0]                                          # (1, 1, 1) / sqrt 3
    v = (a[1], -a[0], 0.0)                              # a x z, the turning axis (not unit)
    k = [[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]
    k2 = [[sum(k[i][m] * k[m][j] for m in range(3)) for j in range(3)] for i in range(3)]
    rot = [[(i == j) + k[i][j] + k2[i][j] / (1 + a[2]) for j in range(3)] for i in range(3)]   # Rodrigues: a -> +z
    turned = [tuple(sum(rot[i][j] * p[j] for j in range(3)) for i in range(3)) for p in pts]
    return [(0.0, 0.0, 1.0)] + turned[1:]


D20_NORMALS = d20_normals()
D20_VERTS, D20_IDS = poly_from_normals(D20_NORMALS)


def d20_numbers(mirror=False):
    """{face index: number}. The 20 is face 0 (+z). Its three neighbours get 8, 2, 14 clockwise seen from outside (from +z that
    is falling azimuth), the 8 on the one with the smallest azimuth from +x; `mirror` goes counter-clockwise instead. The rest
    follows the net: a face may only take an unused number that is a neighbour of every numbered neighbour's number."""
    near = [{j for j, o in enumerate(D20_IDS) if j != i and len(set(ids) & set(o)) == 2} for i, ids in enumerate(D20_IDS)]
    az = lambda j: round(math.atan2(D20_NORMALS[j][1], D20_NORMALS[j][0]), 9) % (2 * math.pi)     # azimuth from +x, 0..2 pi
    ring = sorted(near[0], key=az)                      # rising azimuth: 8 first
    order = ring if mirror else [ring[0], ring[2], ring[1]]
    num = {0: 20, **dict(zip(order, (8, 2, 14)))}

    def ok(g):
        free = set(range(1, 21)) - set(num.values())
        for h in near[g] & set(num):
            free &= D20_NEXT[num[h]]
        return free

    def fill():
        todo = [g for g in range(20) if g not in num]
        if not todo:
            return True
        g = min(todo, key=lambda g: (len(ok(g)), g))    # the most constrained face first
        for n in sorted(ok(g)):
            num[g] = n
            if fill():
                return True
            del num[g]
        return False

    assert fill(), "d20: the net does not fit the icosahedron"
    assert all((num[i] in D20_NEXT[num[j]]) for i in range(20) for j in near[i]), "d20: adjacency differs from the net"
    return num


def d20_top(ids):
    """Digit top of a triangle: its corner most toward +z (the 20's pole). When an edge is highest (the 20's neighbours), straight
    up at that edge's middle like the d12; the 20 and the 1 (all corners level) take the corner with the largest x, then y."""
    z = [round(D20_VERTS[i][2], 6) for i in ids]
    if z.count(max(z)) == 2:
        return {"up_vec": (0.0, 0.0, 1.0)}
    return {"up": max(ids, key=lambda i: tuple(round(D20_VERTS[i][k], 6) for k in (2, 0, 1)))}


def d20_faces(mirror=False):
    """The twenty triangles, numbered from the net. Digit tops: see d20_top. `mirror` is the other handedness; opposites still add to 21."""
    num = d20_numbers(mirror)
    return [{"verts": tuple(ids), "number": num[i], "away": False, **d20_top(ids)} for i, ids in enumerate(D20_IDS)]


# d100: a "golf ball" of 100 small flat faces, 50 axes with their antipodes (normal k and k + 50 are opposite, k = 0 is +z). Opposites
# add to 101. The normals are a Fibonacci spiral relaxed by repulsion (fixed steps, deterministic); the numbering is D100_NUM, made once
# by d100_anneal() (it is only run to regenerate the table, never while rendering).
D100_RELAX = (2000, 0.004)      # iterations, step of the repulsion


def d100_normals():
    """The 100 unit face normals: the 50 axes first, then their antipodes. Start: a Fibonacci spiral on the upper hemisphere (the
    first point on +z). Every step pushes each axis away from all 99 other points (the 50 axes and the 50 antipodes, 1/r^2 force,
    along the sphere), moves it a fixed step and renormalises; the partner is always the negative, so the pairs stay exactly
    antipodal. At the end one rigid turn puts axis 0 exactly on +z (and its partner on -z)."""
    golden = math.pi * (3 - math.sqrt(5))
    half = []
    for k in range(50):
        z = 1 - k / 50
        r = math.sqrt(1 - z * z)
        half.append((r * math.cos(k * golden), r * math.sin(k * golden), z))
    steps, step = D100_RELAX
    for _ in range(steps):
        moved = []
        for i, p in enumerate(half):
            f = [0.0, 0.0, 0.0]
            for j, q in enumerate(half):
                for sign in (1, -1):                    # the point itself and its antipode
                    if i == j and sign == 1:
                        continue
                    d = [p[m] - sign * q[m] for m in range(3)]
                    r2 = sum(x * x for x in d)
                    for m in range(3):
                        f[m] += d[m] / (r2 * math.sqrt(r2))
            along = sum(f[m] * p[m] for m in range(3))
            q = [p[m] + step * (f[m] - along * p[m]) for m in range(3)]      # only the part of the push along the sphere
            norm = math.sqrt(sum(x * x for x in q))
            moved.append(tuple(x / norm for x in q))
        half = moved                                    # all points moved together from the old positions
    a = half[0]
    v = (a[1], -a[0], 0.0)                              # a x z, the turning axis (not unit)
    k = [[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]
    k2 = [[sum(k[i][m] * k[m][j] for m in range(3)) for j in range(3)] for i in range(3)]
    rot = [[(i == j) + k[i][j] + k2[i][j] / (1 + a[2]) for j in range(3)] for i in range(3)]   # Rodrigues: a -> +z
    turned = [tuple(sum(rot[i][j] * p[j] for j in range(3)) for i in range(3)) for p in half]
    turned[0] = (0.0, 0.0, 1.0)
    return turned + [(-x, -y, -z) for x, y, z in turned]


@functools.lru_cache(maxsize=None)
def d100_shape():
    """(normals, verts, ids) of the d100, worked out on first use: the verts are circumradius 1, ids the corners of each face."""
    normals = d100_normals()
    verts, ids = poly_from_near_normals(normals)
    return normals, verts, ids


def d100_verts():
    return d100_shape()[1]


def d100_near(ids):
    """For every face the faces sharing an edge with it (two corners in common)."""
    sets = [set(f) for f in ids]
    return [[j for j in range(len(ids)) if j != i and len(sets[i] & sets[j]) == 2] for i in range(len(ids))]


def d100_anneal(near, seed=1, iters=600000, lam=0.0005, hot=0.05, cold=0.0005):
    """Simulated annealing of the numbering (fixed seed and count: the same table every time). Faces k and k + 50 are opposite and
    hold v and 101 - v, so a move changes an axis pair at a time: flip one axis, swap two axes (or swap and flip both). Cost = the
    sum over edges of 1 / |a - b| (neighbours far apart) + lam * the sum over faces of (average of its neighbours - 50.5)^2
    (every region mixes high and low). The temperature falls geometrically from `hot` to `cold`. Returns the 100 numbers."""
    rnd = random.Random(seed)
    val = list(range(1, 51))
    rnd.shuffle(val)
    val += [101 - x for x in val]

    def local(faces):                                   # all cost terms that touch these faces
        edges = {(min(f, g), max(f, g)) for f in faces for g in near[f]}
        around = set(faces).union(*(near[f] for f in faces))
        return (sum(1 / abs(val[a] - val[b]) for a, b in edges)
                + lam * sum((sum(val[g] for g in near[f]) / len(near[f]) - 50.5) ** 2 for f in around))

    for it in range(iters):
        t = hot * (cold / hot) ** (it / iters)
        i, j = rnd.randrange(50), rnd.randrange(50)
        if rnd.random() < 0.25:
            j = i                                       # a plain flip of axis i
        touched = [i, i + 50, j, j + 50]
        before, old = local(touched), (val[i], val[j])
        if i == j:
            val[i] = 101 - val[i]
        elif rnd.random() < 0.5:
            val[i], val[j] = val[j], val[i]
        else:
            val[i], val[j] = 101 - val[j], 101 - val[i]
        val[i + 50], val[j + 50] = 101 - val[i], 101 - val[j]
        delta = local(touched) - before
        if delta > 0 and rnd.random() >= math.exp(-delta / t):          # worse: keep it only by chance
            val[i], val[j] = old
            val[i + 50], val[j + 50] = 101 - val[i], 101 - val[j]
    return val


# normal index -> number, made once by d100_anneal(d100_near(ids)) (seed 1: the lowest cost of seeds 1-8); the second half is 101 minus the first.
# To regenerate: run that call after changing D100_RELAX or the cost, and paste the result here.
D100_NUM = (
     59,  35,  79,   7,  15,  98,  85,  46,  24,  64,
     17,  41,  80,  49,  29,   2,  62,  44,  82,  67,
     97,  81,  89,  36,  18,  26,  30,   8,  10,  96,
     68,  61,  88,  54,  14,  53,  70,   1,   6,   9,
     38,  27,  50,  23,  90,  45,  76,  58,  73,  32,
     42,  66,  22,  94,  86,   3,  16,  55,  77,  37,
     84,  60,  21,  52,  72,  99,  39,  57,  19,  34,
      4,  20,  12,  65,  83,  75,  71,  93,  91,   5,
     33,  40,  13,  47,  87,  48,  31, 100,  95,  92,
     63,  74,  51,  78,  11,  56,  25,  43,  28,  69,
)


def d100_faces(mirror=False):
    """The 100 plates. Every digit's top points to +z, except the two poles (they read toward +x). No mirror variant: the shape
    has no mirror symmetry to carry the numbering over."""
    if mirror:
        sys.exit("d100 has no mirror variant")
    assert sorted(D100_NUM) == list(range(1, 101)) and all(D100_NUM[i] + D100_NUM[i + 50] == 101 for i in range(50)), "d100: bad table"
    _, _, ids = d100_shape()
    return [{"verts": tuple(f), "number": D100_NUM[i], "away": False,
             "up_vec": (1.0, 0.0, 0.0) if i % 50 == 0 else (0.0, 0.0, 1.0)} for i, f in enumerate(ids)]


# Real d8 (opposites add to 9). Face 1 is (-,+,+): with it in front, apex up, 7 is on its left, 5 on its right, 6 below
# (standard layout). --mirror flips the handedness (7 right, 5 left).
D8_NUMBERS = {
    (-1, 1, 1): 1, (1, 1, 1): 7, (1, -1, 1): 3, (-1, -1, 1): 5,
    (-1, 1, -1): 6, (1, 1, -1): 4, (1, -1, -1): 8, (-1, -1, -1): 2,
}

# Per die: unit-radius vertices, faces, digit height (relative to the radius) and bevel width. Opposite faces of a d8 add to 9.
# A face has one number + "up" vertex, or a "labels" list of {number, up, at} (digit centre `at` 0..1 from the face
# centroid toward its `up` vertex; default "label_at"). Optional keys: "read" ("face" default, or "vertex") and "tilt"
# (degrees, default 2; positive shows the face below, negative looks down from above). d4: corner k owns k; each face
# shows its three corners' numbers, tops toward their corner; the roll is the top corner. A face or label may give
# "up_vec" (a die-space direction) instead of an "up" vertex. "view": "top" (face dice) turns the rolled face up and
# yaws it by "yaw" degrees, with its digit reading upright from the camera.
# d10: pentagonal trapezohedron, digits 0-9 (opposites add to 9), as on a real die: the even pole reads 2-8-0-4-6 by
# increasing azimuth, the odd pole follows by opposites, every digit's top points to its own pole's apex, and the 0 counts as 10.
# More optional keys: "verts" may be a function (worked out on first use, d100); a face or label may carry "text" (what is printed
# instead of its number); "bars" ("set" default = UNDERLINED, "auto" = whatever reads as another number turned 180 degrees, "none");
# "groove" (radius of a round groove cut along every edge, relative to the die radius); "max_tris" (the --glb limit of this die);
# "physics" (written to the .faces.json so a web viewer can pick a collider).
DICE = {
    "d8": {
        "verts": [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
        "build": lambda mirror=False: octa_faces(D8_NUMBERS, mirror),
        "digit": 0.46,
        "bevel": 0.08,
    },
    "d4": {
        "verts": [(T, T, T), (T, -T, -T), (-T, T, -T), (-T, -T, T)],
        "build": lambda mirror=False: tetra_faces(mirror),
        "digit": 0.30,
        "bevel": 0.10,
        "label_at": 0.5,
        "read": "vertex",
        "tilt": -25.0,       # negative: the top leans toward the camera, seen from above
    },
    # d6: opposites add to 7, Western handedness (1, 2, 3 counter-clockwise round their shared corner), digits square to the edges
    "d6": {
        "verts": CUBE_VERTS,
        "build": lambda mirror=False: cube_faces(mirror),
        "digit": 0.50,
        "bevel": 0.08,
        "view": "top",
        "yaw": 15.0,         # three faces show, top digit only slightly turned
        "tilt": -35.0,
    },
    "d10": {
        "verts": d10_verts(),
        "build": lambda mirror=False: d10_faces(mirror),
        "digit": 0.48,       # large digits, filling the face
        "bevel": 0.08,
        "view": "top",       # rolled face up, its apex pointing away from the camera
        "yaw": 0.0,
        "tilt": -70.0,       # chosen view: seen from 70 deg above
    },
    # d10t: the percentile die. d10 geometry, numbering, tops and view; each kite prints its tens, two digits per face
    "d10t": {
        "verts": d10_verts(),
        "build": lambda mirror=False: d10t_faces(mirror),
        "digit": 0.36,       # "90" (1.51 x 1.03 digit heights, 0.54 wide) must stay inside the kite (inradius 0.43) with room for the bevel
        "bevel": 0.08,
        "bars": "none",
        "view": "top",
        "yaw": 0.0,
        "tilt": -70.0,
    },
    # d12: reference layout of a common commercial d12, opposites add to 13, digit tops toward their own half's pole (12 or 1)
    "d12": {
        "verts": D12_VERTS,
        "build": lambda mirror=False: d12_faces(mirror),
        "digit": 0.34,       # "12" must stay inside the pentagon (circumradius about 0.607)
        "bevel": 0.08,
        "view": "top",
        "yaw": 0.0,
        "tilt": -75.0,       # chosen view: rolled face almost straight at the viewer
    },
    # d20: standard layout (20 touches 2, 8, 14; opposites 21), digit tops toward the
    # corner nearest the 20's pole
    "d20": {
        "verts": D20_VERTS,
        "build": lambda mirror=False: d20_faces(mirror),
        "digit": 0.23,       # "20" (1.49 x 1.02 digit heights) must stay inside the flat triangle (inradius 0.3035 - bevel 0.08)
        "bevel": 0.08,
        "view": "top",
        "yaw": 0.0,
        "tilt": -75.0,
    },
    # d100: 100 small flat plates (opposites add to 101) with a thin groove along every edge, "golf ball" style, so it rolls like a sphere
    "d100": {
        "verts": d100_verts,
        "build": lambda mirror=False: d100_faces(mirror),
        "digit": 0.11,       # "100" (2.27 x 1.03 digit heights, 0.25 wide) must stay inside the plate (inradius 0.15-0.17, minus the groove)
        "bevel": 0.01,
        "groove": 0.012,
        "bars": "auto",
        "view": "top",
        "yaw": 0.0,
        "tilt": -88.0,       # seen from straight above: the rolled number sits in the centre of the ball
        "max_tris": 80000,
        "frame_scales": (1.0,),  # a tight plate gets no frame at all instead of a hair-thin one (that made slivers)
        "digit_res": 2,      # 190 small digits: the coarsest curves that still look round at this size
        "bevel_segments": 2, # the bevel (0.01) is mostly cut away by the grooves anyway
        "physics": "sphere",
    },
}

# Candidate fonts: bold geometric sans, first one found is used.
FONTS = [
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/TTF/FiraSans-SemiBold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]

UNDERLINED = {"6", "9"}   # numbers that get the standard bar underneath, so they cannot be read upside down
TURNED = {"0": "0", "1": "1", "6": "9", "8": "8", "9": "6"}     # digits that still read as a digit after a 180 degree turn
GOLD = {"dark": ((0.96, 0.68, 0.20, 1), 0.10, 0.38), "bright": ((0.92, 0.77, 0.52, 1), 0.10, 0.42)}    # (colour, metallic, roughness)
ENGRAVE = 0.045    # depth of the cut below the face plane (its walls and floor are gold)
FILL_GAP = 0.014    # the gold fill stops this far below the surface

# Triangle budget: detail that only adds smoothness. A die can override these in its DICE entry ("digit_res", "bevel_segments",
# "groove_sides"); --digit-res, --bevel-seg and --groove-sides override both (for before/after comparisons).
DIGIT_RES = 4       # segments per curve piece of the digits (numbers, gold fills, cutters); the old value was 10
BEVEL_SEGMENTS = 3  # segments across every rounded die edge; the old value was 6 (each step turns 90/3 = 30 degrees, still smooth-shaded)
GROOVE_SIDES = 6    # sides of the cylinder cut along every d100 plate edge (a groove 0.024 wide); the old value was 12

# Frames round the numbers (see frame_face)
FRAME_MARGIN = 0.12 # free margin round a number's frame, as a share of the digit height (smaller on a tight face: x0.5, x0.25, x0.1)
FRAME_EDGE = 0.004  # a frame's corners stay at least this far inside the flat polygon of the face

# Maker's mark: MARK_TEXT cut into a side wall of the lowest number's recess (gold wall, tiny, facing sideways), see cut_mark.
MARK_TEXT = "Haxinpro"
MARK_LENGTH = 0.0368    # text length as a share of the digit height: 1/10 of the first (top-surface) version, 0.0085 on the d20
MARK_DEPTH = 2e-4       # how far the letters go into the wall (1/10 of the first version): about 1700 float32 steps at a die size of 1
MARK_OUT = 5e-4         # the cutter also reaches this far out of the wall into the recess, so it crosses the wall cleanly
MARK_RES = 1            # segments per curve piece of the mark's letters: they are far too small for smooth curves
MARK_FRAME = 0.5       # free margin of the wall frame round the text, as a share of the text height
MARK_TOL = MARK_DEPTH / 4   # slack when looking for the letters' floor in the mesh
FLAT_TOL = 0.001    # a polygon whose corners are all this close to a die face plane (unit radius) counts as flat stone

# Written into every .glb (asset.copyright and asset.extras), see stamp_glb.
COPYRIGHT = "\u00a9 Haxinpro"
LICENCE = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"     # LICENSE-ASSETS.md
REPO_URL = "https://github.com/Haxinpro/VTT-Dice"   # written into asset.extras.source of every .glb


# --------------------------------------------------------------------------- helpers

def needs_bar(text, rule="set"):
    """Does the printed text get the underline? rule "set": only the texts in UNDERLINED; "auto": a text that, turned 180 degrees
    (reversed, 6 and 9 swapped), reads as a different number from 1 to 100 without a leading zero; "none": never."""
    if rule == "auto":
        if any(c not in TURNED for c in text):
            return False
        back = "".join(TURNED[c] for c in reversed(text))
        return back != text and not back.startswith("0") and 1 <= int(back) <= 100
    return rule == "set" and text in UNDERLINED


def parse_args():
    """Reads the arguments after Blender's own `--`."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--die", default="d8", choices=sorted(DICE))
    p.add_argument("--result", type=int, default=1, help="the face to show: its number (d10 and d10t: the digit 0-9, d10t 3 shows \"30\", 0 shows \"00\")")
    p.add_argument("--results", default="", help="batch: several results in one run, \"1-20\", \"0-9\", \"1,5,9\" or \"all\" (every face / corner); --out then needs {n}")
    p.add_argument("--seed", type=int, default=1, help="varies the marble veins (the same for a whole --results batch)")
    p.add_argument("--out", default="", help="PNG to render (skipped when empty); {n} = the face's printed text, else its number")
    p.add_argument("--res", type=int, default=1024)
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--tilt", type=float, default=None, help="degrees the roll leans back (default: die's own, else 2)")
    p.add_argument("--yaw", type=float, default=None, help="view \"top\" dice (d6): degrees the view turns off the digit (default: die's own)")
    p.add_argument("--pose", default="edge", choices=["face", "edge"], help="vertex dice (d4): what faces the camera")
    p.add_argument("--lens", type=float, default=250.0, help="focal length in mm (shorter = more perspective)")
    p.add_argument("--fill", type=float, default=0.80, help="die size as a share of the canvas")
    p.add_argument("--font", default="")
    p.add_argument("--mirror", action="store_true", help="mirror-image handedness (d8: 7 right, 5 left of the 1; d4: corners 3 and 4 swap; d6: faces 2 and 5 swap; d10 and d12: numbered by mirrored azimuth; d20: 8, 2, 14 counter-clockwise round the 20; d100: no mirror variant)")
    p.add_argument("--faces", default="", help="write only the .faces.json for --die (and --mirror) to this path and exit (no scene, render or bake)")
    p.add_argument("--blend", default="", help="also save the finished scene here as a .blend (open it in Blender)")
    p.add_argument("--glb", default="", help="export a web-ready .glb (+ .faces.json) with baked textures")
    p.add_argument("--tex", type=int, default=2048, help="baked texture size for --glb")
    p.add_argument("--max-tris", type=int, default=20000, help="decimate the --glb model above this (a die's own \"max_tris\" wins)")
    p.add_argument("--digit-res", type=int, default=0, help="segments per curve piece of the digits (default: the die's own, else DIGIT_RES; the old value was 10)")
    p.add_argument("--bevel-seg", type=int, default=0, help="segments across the rounded edges (default: the die's own, else BEVEL_SEGMENTS; the old value was 6)")
    p.add_argument("--groove-sides", type=int, default=0, help="d100: sides of the groove cutter (default GROOVE_SIDES; the old value was 12)")
    p.add_argument("--drop-hidden", action="store_true", help="--glb: drop the fill walls and bottoms and the cut floors (smaller, but leaves open edges at the gold caps: off by default)")
    p.add_argument("--no-beauty", action="store_true", help="--glb: do not re-triangulate the flat regions with beauty (the Blender default triangles)")
    p.add_argument("--no-frames", action="store_true", help="do not split the faces into frames round the numbers (the old triangulation)")
    p.add_argument("--no-mark", action="store_true", help="do not cut the maker's mark (\"Haxinpro\") into the gold of the lowest number")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "gpu"], help="auto: OPTIX, then CUDA, else CPU; gpu: the same; cpu: force the CPU")
    return p.parse_args(argv)


def parse_results(text, spec):
    """The results a --results text names, in order and without repeats: "all" (every face, or every corner of a vertex die),
    or comma-separated numbers and ranges like "1-20" or "1,5,9"."""
    if spec.get("read") == "vertex":
        every = sorted(corner_numbers(spec).values())
    else:
        every = sorted(f["number"] for f in spec["faces"])
    if text.strip().lower() == "all":
        return every
    out = []
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        try:
            out += range(int(lo), int(hi or lo) + 1)
        except ValueError:
            sys.exit(f"bad --results part {part!r} (use 1-20, 1,5,9 or all)")
    return list(dict.fromkeys(out))


def pose_for(spec, args, result):
    """(front, up, label) that show `result` to the camera: a vertex die (d4) looks at the corner, a face die at the face (view
    "top": face up, turned by the yaw). `label` is what {n} in --out becomes: the printed text, else the number."""
    if spec.get("read") == "vertex":        # d4: the result is the top corner
        corner = next((i for i, n in corner_numbers(spec).items() if n == result), None)
        if corner is None:
            sys.exit(f"{args.die} has no corner {result}")
        front, up = vertex_frame(spec, corner, args.pose)
        return front, up, str(result)
    face = next((f for f in spec["faces"] if f["number"] == result), None)
    if face is None:
        sys.exit(f"{args.die} has no face {result}")
    _, front, up = face_frame(spec["verts"], face)
    if spec.get("view") == "top":           # d6: the face points up, the camera looks along the digit's up direction
        yaw = args.yaw if args.yaw is not None else spec["yaw"]
        turn = Matrix.Rotation(math.radians(yaw), 3, front)
        front, up = turn @ -up, front
    return front, up, str(face.get("text", face["number"]))


def reset_scene():
    """Empty scene with Cycles and a transparent film."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def link(obj, coll=None):
    """Puts an object into the scene (or a given collection)."""
    (coll or bpy.context.scene.collection).objects.link(obj)
    return obj


def face_labels(face, spec):
    """The labels of a face as dicts (number, up vertex or "up_vec", at, away, optional printed "text"). A face without "labels" has just its own number."""
    if "labels" in face:
        return [{"at": spec.get("label_at", 0.0), "away": False, **lb} for lb in face["labels"]]
    lb = {"number": face["number"], "at": 0.0, "away": face.get("away", False)}
    lb.update({k: face[k] for k in ("up", "up_vec", "text") if k in face})     # the digit's top: a vertex or a direction; the printed text
    return [lb]


def corner_numbers(spec):
    """{corner index: number} of a vertex die, read from the face labels."""
    return {lb["up"]: lb["number"] for f in spec["faces"] for lb in face_labels(f, spec)}


def face_frame(verts, face, label=None):
    """Centroid, outward normal and in-plane "up" direction of a face: toward the up vertex of `label` (default the
    face), or along its "up_vec" direction when it has one."""
    lb = label or face
    pts = [Vector(verts[i]) for i in face["verts"]]
    centre = sum(pts, Vector()) / len(pts)
    normal = (pts[1] - pts[0]).cross(pts[2] - pts[0]).normalized()
    if normal.dot(centre) < 0:
        normal = -normal
    if lb.get("up_vec") is not None:
        up = Vector(lb["up_vec"])
    else:
        up = Vector(verts[lb["up"]]) - centre
        if lb.get("away"):
            up = -up
    up = (up - normal * up.dot(normal)).normalized()
    return centre, normal, up


def vertex_frame(spec, corner, pose):
    """(front, up) in die space for a die read at `corner`: up is the corner direction, front the direction of a face
    ("face") or edge ("edge") touching it that looks at the camera. The one with the lowest other corner numbers wins."""
    verts, nums = spec["verts"], corner_numbers(spec)
    up = Vector(verts[corner]).normalized()
    touch = [f for f in spec["faces"] if corner in f["verts"]]
    if pose == "face":
        pick = min(touch, key=lambda f: tuple(sorted(nums[i] for i in f["verts"] if i != corner)))
        d = sum((Vector(verts[i]) for i in pick["verts"]), Vector())      # centroid direction
    else:
        other = min({i for f in touch for i in f["verts"]} - {corner}, key=lambda i: nums[i])
        d = Vector(verts[corner]) + Vector(verts[other])                  # edge midpoint direction
    return (d - up * d.dot(up)).normalized(), up


def face_matrix(centre, normal, up):
    """Matrix placing a flat object (x right, y up, z out of the surface) on a face, upright toward `up`."""
    right = up.cross(normal)
    m = Matrix([right, up, normal]).transposed().to_4x4()
    m.translation = centre
    return m


def bake(obj):
    """Applies all modifiers by replacing the mesh with the evaluated one."""
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    old = obj.data
    obj.modifiers.clear()
    obj.data = mesh
    bpy.data.meshes.remove(old)


def smooth_by_angle(mesh, degrees=35):
    """Smooth shading, but sharp wherever the neighbouring faces meet at more than `degrees`."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(degrees))
    bm.to_mesh(mesh)
    bm.free()


# --------------------------------------------------------------------------- geometry

def build_body(spec):
    """Beveled die body (smooth, rounded edges) built from the vertex/face data."""
    mesh = bpy.data.meshes.new("body")
    mesh.from_pydata([Vector(v) for v in spec["verts"]], [], [f["verts"] for f in spec["faces"]])
    mesh.validate()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)   # all outward
    bm.to_mesh(mesh)
    bm.free()
    body = link(bpy.data.objects.new("body", mesh))
    mod = body.modifiers.new("bevel", "BEVEL")
    mod.width, mod.segments, mod.limit_method = spec["bevel"], spec.get("bevel_segments", BEVEL_SEGMENTS), "NONE"
    mod.profile = 0.5
    bake(body)
    return body


def glyph_mesh(text, size, z0, z1, font, grow=0.0, bars="set", res=DIGIT_RES):
    """Extruded text as a mesh, centred on x/y, spanning z0..z1 (z up out of the face). `bars` is the underline rule (see needs_bar). `res` is the number of
    segments per curve piece of the letters (fewer = coarser curves, far fewer triangles)."""
    curve = bpy.data.curves.new("glyph", "FONT")
    curve.body, curve.font, curve.size = text, font, size
    curve.extrude, curve.offset, curve.resolution_u = (z1 - z0) / 2, grow, res
    curve.align_x, curve.align_y = "CENTER", "CENTER"
    tmp = link(bpy.data.objects.new("glyph", curve))
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(curve)
    xs, ys = [v.co.x for v in mesh.vertices], [v.co.y for v in mesh.vertices]
    mesh.transform(Matrix.Translation(Vector((-(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, (z0 + z1) / 2))))
    if needs_bar(text, bars):
        add_underline(mesh, (max(xs) - min(xs)), (max(ys) - min(ys)), z0, z1)
    return mesh


def add_underline(mesh, w, h, z0, z1):
    """Adds a short bar under a digit (digit is centred at 0,0; w and h are its width and height)."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    cube = bmesh.ops.create_cube(bm, size=1.0)
    for v in cube["verts"]:         # unit cube -> bar: a bit wider than the digit, 0.13 h thick, 0.14 h below it
        v.co = Vector((v.co.x * w * 1.05, -h / 2 - 0.14 * h + v.co.y * 0.13 * h, (z0 + z1) / 2 + v.co.z * (z1 - z0)))
    bm.to_mesh(mesh)
    bm.free()


def groove_data(verts, faces, radius, sides=GROOVE_SIDES):
    """Cutter geometry (plain lists, outward-wound): one thin closed cylinder of `radius` along every edge of the polyhedron, centred
    on the edge line and reaching `radius` past both corners so the corners are rounded off too."""
    edges = sorted({tuple(sorted(e)) for ids in faces for e in zip(ids, ids[1:] + ids[:1])})
    out_v, out_f = [], []
    for a, b in edges:
        pa, pb = Vector(verts[a]), Vector(verts[b])
        d = (pb - pa).normalized()
        pa, pb = pa - d * radius, pb + d * radius
        u = d.cross(Vector((1, 0, 0)) if abs(d.x) < 0.9 else Vector((0, 1, 0))).normalized()
        w = d.cross(u)                                  # u x w = d: growing angle runs counter-clockwise round d
        ring = [u * math.cos(2 * math.pi * k / sides) * radius + w * math.sin(2 * math.pi * k / sides) * radius for k in range(sides)]
        n = len(out_v)
        out_v += [tuple(pa + r) for r in ring] + [tuple(pb + r) for r in ring]
        out_f += [(n + k, n + (k + 1) % sides, n + sides + (k + 1) % sides, n + sides + k) for k in range(sides)]
        out_f += [tuple(range(n + sides, n + 2 * sides)), tuple(reversed(range(n, n + sides)))]      # end caps
    return out_v, out_f


def cut_grooves(body, spec):
    """Cuts the round grooves between the plates: one joined cutter mesh (the cylinders of groove_data) with the marble material, so
    the groove walls stay stone. The cylinders overlap at every corner, so this boolean needs self-intersection and is a pass of its
    own; the numbers are cut afterwards in the usual way."""
    verts, faces = groove_data(spec["verts"], [f["verts"] for f in spec["faces"]], spec["groove"], spec.get("groove_sides", GROOVE_SIDES))
    mesh = bpy.data.meshes.new("grooves")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.materials.append(body.data.materials[0])       # the marble
    coll = bpy.data.collections.new("groove_cutter")
    bpy.context.scene.collection.children.link(coll)
    cut = bpy.data.objects.new("grooves", mesh)
    cut.hide_render = cut.hide_viewport = True
    link(cut, coll)
    mod = body.modifiers.new("grooves", "BOOLEAN")
    mod.operand_type, mod.collection, mod.solver, mod.operation = "COLLECTION", coll, "EXACT", "DIFFERENCE"
    mod.use_self = True
    mod.material_mode = "TRANSFER"
    bake(body)


def gap_in(poly, x, y):
    """Distance from (x, y) to the outline of a 2D polygon: positive inside, negative outside (any simple polygon)."""
    inside, best = False, 1e9
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside                         # a ray to the right crosses this edge
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ((dx * dx + dy * dy) or 1e-30)))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best if inside else -best


def frame_face(bm, faces, labs, digit, scales=(1.0, 0.5, 0.25, 0.1)):
    """Gives the flat polygon of one die face a frame round every label before the numbers are cut: a rectangle (FRAME_MARGIN of the
    digit height free on every side, a smaller margin on a tight face) split into one cell per digit (letter_cuts), and the rest of
    the polygon filled with a Blender triangle fill (beauty on) between the polygon's outline and the rectangles. The cut then only
    triangulates each digit's cell, with the cell's four corners close by, instead of fanning from the digit's outline to the far
    corners of the face. `faces` are the coplanar polygons of the face, `labs` its (label placement, cutter mesh) pairs. Returns None
    when done, else the reason the face was left alone."""
    if not faces:
        return "no flat polygon"
    if len(faces) > 1:
        faces = bmesh.ops.dissolve_faces(bm, faces=faces)["region"]
        if len(faces) != 1:
            return "polygon in pieces"
    old = faces[0]
    old.normal_update()
    fn = old.normal.copy()
    base = labs[0][0].to_3x3()
    proj = lambda p: (p.dot(base.col[0]), p.dot(base.col[1]))      # the face plane as 2D
    outer = list(old.verts)
    poly = [proj(v.co) for v in outer]
    boxes = []
    for at, gm in labs:
        xs, ys = [v.co.x for v in gm.vertices], [v.co.y for v in gm.vertices]
        for scale in scales:
            m = FRAME_MARGIN * digit * scale
            rect = (min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m)
            if m >= 0.002 and all(gap_in(poly, *proj(at @ Vector((x, y, 0.0)))) >= FRAME_EDGE for x in rect[:2] for y in rect[2:]):
                boxes.append((at, rect, letter_cuts(gm)))
                break
        else:
            return "frame does not fit"
    mids = [(proj(at @ Vector(((r[0] + r[1]) / 2, (r[2] + r[3]) / 2, 0.0))), math.hypot(r[1] - r[0], r[3] - r[2]) / 2) for at, r, _ in boxes]
    if any(math.dist(a[0], b[0]) < a[1] + b[1] for i, a in enumerate(mids) for b in mids[i + 1:]):
        return "frames overlap"
    flip = base.col[2].dot(fn) < 0                                  # keep the old polygon's side
    material, smooth, area = old.material_index, old.smooth, old.calc_area()
    outer_edges = list(old.edges)
    bmesh.ops.delete(bm, geom=[old], context="FACES_ONLY")
    cells, ring_edges = [], []
    def add(vs):
        f = bm.faces.new(vs[::-1] if flip else vs)
        f.material_index, f.smooth = material, smooth
        return f
    for at, (x0, x1, y0, y1), cuts in boxes:
        xs = [x0] + cuts + [x1]
        low = [bm.verts.new(at @ Vector((x, y0, 0.0))) for x in xs]
        top = [bm.verts.new(at @ Vector((x, y1, 0.0))) for x in xs]
        cells += [add([low[j], low[j + 1], top[j + 1], top[j]]) for j in range(len(xs) - 1)]
        ring = low + top[::-1]
        ring_edges += [bm.edges.get((ring[k], ring[(k + 1) % len(ring)])) for k in range(len(ring))]
    try:
        got = bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=outer_edges + ring_edges, normal=fn)["geom"]
    except Exception:
        got = []
    fills = [g for g in got if isinstance(g, bmesh.types.BMFace)]
    if fills and abs(sum(f.calc_area() for f in fills) - (area - sum(f.calc_area() for f in cells))) <= 1e-4 * area:
        for f in fills:
            f.normal_update()
            if f.normal.dot(fn) < 0:
                f.normal_flip()
            f.material_index, f.smooth = material, smooth
        return None
    bmesh.ops.delete(bm, geom=fills + cells, context="FACES")       # the fill did not cover exactly the rest: put the polygon back
    back = bm.faces.new(outer)
    back.material_index, back.smooth = material, smooth
    return "fill failed"


def frame_faces(mesh, spec, info):
    """Runs frame_face on every die face that has labels (`info`: face index -> [(label placement, cutter mesh)]) of a body mesh in
    die space, before the numbers are cut. Returns (faces framed, {reason: faces left alone})."""
    wanted, dist = face_planes(spec)
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    on = np.abs(co.reshape(-1, 3) @ wanted.T - dist) < 1e-5            # (vertex, plane): the vertex lies on the plane
    vert_of, start = np.empty(len(mesh.loops), np.int32), np.empty(len(mesh.polygons), np.int32)
    mesh.loops.foreach_get("vertex_index", vert_of)
    mesh.polygons.foreach_get("loop_start", start)
    flat = np.logical_and.reduceat(on[vert_of], start, axis=0)         # (polygon, plane): all its corners do
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    groups = {fi: [bm.faces[i] for i in np.nonzero(flat[:, fi])[0]] for fi in info}
    framed, why = 0, {}
    for fi, labs in info.items():
        reason = frame_face(bm, groups[fi], labs, spec["digit"], spec.get("frame_scales", (1.0, 0.5, 0.25, 0.1)))
        if reason:
            why[reason] = why.get(reason, 0) + 1
        else:
            framed += 1
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return framed, why


def engrave_numbers(body, spec, font, mat_for, mark=False, frames=True):
    """Cuts every number into its face and fills the cut with gold; `mat_for(number)` picks the gold material of a digit. Returns
    (the gold objects, the mark or None). A die with "groove" gets its grooves first. With `mark`, the maker's mark is cut into a
    wall of the recess of the digit 1 (see cut_mark). With `frames`, every face is first split into a frame round each number
    (see frame_face), so the cuts leave short, well-shaped triangles."""
    if spec.get("groove"):
        cut_grooves(body, spec)
    cutters = bpy.data.collections.new("cutters")
    bpy.context.scene.collection.children.link(cutters)
    inserts, info = [], {}
    target = mark_target(spec) if mark else None        # (face index, label index) of the number that carries the mark
    for fi, face in enumerate(spec["faces"]):
        for k, lb in enumerate(face_labels(face, spec)):
            centre, normal, up = face_frame(spec["verts"], face, lb)
            h = normal.dot(centre)          # face plane distance from the middle
            shift = (Vector(spec["verts"][lb["up"]]) - centre) * lb["at"] if lb["at"] else Vector()   # digit centre toward its up vertex
            at = Matrix.Translation(normal * h + shift) @ face_matrix(Vector(), normal, up)
            text, size = lb.get("text", str(lb["number"])), spec["digit"] / 0.72   # printed text; digit height is ~0.72 of the font size
            bars = spec.get("bars", "set")
            mat = mat_for(lb["number"])
            n = len(inserts)                # equal digits exist (d4), so names carry a counter
            res = spec.get("digit_res", DIGIT_RES)
            cut = bpy.data.objects.new(f"cut{text}_{n}", glyph_mesh(text, size, -ENGRAVE, 0.06, font, bars=bars, res=res))
            cut.matrix_world = at
            info.setdefault(fi, []).append((at, cut.data))
            cut.data.materials.append(mat)  # lines the cut in gold
            cut.hide_render = cut.hide_viewport = True
            link(cut, cutters)
            gold = link(bpy.data.objects.new(f"gold{text}_{n}", glyph_mesh(text, size, -ENGRAVE + 0.001, -FILL_GAP, font, bars=bars, res=res)))
            gold.matrix_world = at
            gold.data.materials.append(mat)
            if (fi, k) == target:
                carrier, carrier_text = gold, text
            inserts.append(gold)
    if frames:
        framed, why = frame_faces(body.data, spec, info)
        print(f"framed faces: {framed} of {len(info)}, left alone: {sum(why.values())} {why or ''}")
    mod = body.modifiers.new("engrave", "BOOLEAN")
    mod.operand_type, mod.collection, mod.solver, mod.operation = "COLLECTION", cutters, "EXACT", "DIFFERENCE"
    mod.material_mode = "TRANSFER"          # cut walls take the cutter's gold material (one shared material per number in a batch)
    bake(body)
    found = cut_mark(body, carrier, carrier_text, spec, font) if mark else None      # before the smoothing, so the letters keep sharp edges
    smooth_by_angle(body.data)
    return inserts, found


# --------------------------------------------------------------------------- maker's mark

def mark_target(spec):
    """(face index, label index) of the label that carries the mark: the one printing "1"; a die without it (the tens die) takes
    "10", and one with neither "100". On the d4, every face touching corner 1 shows a 1; the one whose other corners are lowest
    wins (corners 1, 2, 3)."""
    for want in ("1", "10", "100"):
        best = None
        for i, face in enumerate(spec["faces"]):
            labels = face_labels(face, spec)
            for k, lb in enumerate(labels):
                if lb.get("text", str(lb["number"])) == want:
                    key = sorted(o["number"] for j, o in enumerate(labels) if j != k)
                    if best is None or key < best[0]:
                        best = (key, i, k)
        if best:
            return best[1], best[2]
    sys.exit("this die has no label 1, 10 or 100 to carry the mark")


def glyph_tris(mesh):
    """The top cap of a glyph mesh as 2D triangles ((x, y) x 3): the triangles whose corners all sit at the highest z."""
    top = max(v.co.z for v in mesh.vertices)
    mesh.calc_loop_triangles()
    return [tuple((mesh.vertices[i].co.x, mesh.vertices[i].co.y) for i in t.vertices)
            for t in mesh.loop_triangles if all(abs(mesh.vertices[i].co.z - top) < 1e-6 for i in t.vertices)]


def wall_edge(tris):
    """The wall of a "1" for the mark, from 2D triangles (a flat glyph cap): (length, a, b, inward). It is the right-hand side of the
    stem as the digit reads upright, i.e. the outline edges that run straight up with the glyph on their left (inward = -x); all
    pieces on the same vertical line are joined into one run from a (bottom) to b (top). Without such an edge, the longest outline
    edge. An outline edge belongs to just one triangle, whose third corner gives the side of the glyph."""
    seen = {}
    for t in tris:
        for k in range(3):
            a, b, c = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            seen.setdefault(frozenset((tuple(round(x, 7) for x in a), tuple(round(x, 7) for x in b))), []).append((a, b, c))
    edges = []
    for hits in seen.values():
        if len(hits) == 1:
            a, b, c = hits[0]
            length = math.dist(a, b)
            t = Vector((b[0] - a[0], b[1] - a[1], 0.0)) / length
            v = Vector((c[0] - a[0], c[1] - a[1], 0.0))
            edges.append((length, a, b, (v - t * v.dot(t)).normalized()))
    lines = {}
    for e in edges:
        if e[3].x < -0.999:                             # glyph to the left of a straight-up edge
            lines.setdefault(round(e[1][0], 5), []).append(e)
    if not lines:
        return max(edges, key=lambda e: e[0])
    run = max(lines.values(), key=lambda es: sum(e[0] for e in es))
    ys = [p[1] for e in run for p in (e[1], e[2])]
    x = sum(p[0] for e in run for p in (e[1], e[2])) / (2 * len(run))
    return max(ys) - min(ys), (x, min(ys)), (x, max(ys)), run[0][3]


def cut_mark(body, ins, text, spec, font):
    """Cuts MARK_TEXT MARK_DEPTH deep into a side wall of the recess of the digit 1 (`ins` is the gold fill of the label `text`, "1",
    "10" or "100": only its first glyph, the 1, counts). The wall is the right-hand side of the 1's stem (see wall_edge), the same
    spot on every die, centred along the stem. The text runs along the wall, centred
    in the visible height (the wall above the fill, from the face plane down to FILL_GAP), reads from inside the recess, and gets the
    digit's gold. Which wall: the body's recess wall. The fill's own side wall lies exactly on it below FILL_GAP, so it is hidden.
    Before the cut the wall gets a small frame round the text box (see frame_wall), so the boolean only connects the letters to the
    frame's four corners instead of the far ends of the wall (the frame is cut into one cell per letter, see letter_cuts). Returns
    {"at", "half", "frame", "cuts", "wall"}: the placement (mark space to die space: x along the wall, y up, z out of the wall into
    the recess), the half size of the text, the frame margin, the x positions between the letters and the extent of the wall piece
    (half length, y range) that the decimation must keep."""
    digit = spec["digit"]
    tris = glyph_tris(ins.data)
    if len(text) > 1:           # keep only the first glyph (the 1): the triangles left of where a lone 1 would end
        one = glyph_mesh("1", digit / 0.72, 0.0, 0.01, font, bars="none", res=spec.get("digit_res", DIGIT_RES))
        width = max(v.co.x for v in one.vertices) - min(v.co.x for v in one.vertices)
        bpy.data.meshes.remove(one)
        edge = min(p[0] for t in tris for p in t) + width + 1e-6
        tris = [t for t in tris if max(p[0] for p in t) <= edge]
    length, a, b, inward = wall_edge(tris)
    mesh = glyph_mesh(MARK_TEXT, 1.0, -MARK_DEPTH, MARK_OUT, font, bars="none", res=MARK_RES)           # size 1, scaled below
    xs, ys = [v.co.x for v in mesh.vertices], [v.co.y for v in mesh.vertices]
    want = min(MARK_LENGTH * digit, 0.8 * length)       # a short wall (the rings of 0 and 00) makes the text shorter, never longer
    k = want / (max(xs) - min(xs))
    mesh.transform(Matrix.Diagonal((k, k, 1.0, 1.0)))   # x, y only: the depth stays MARK_DEPTH
    up = Vector((0.0, 0.0, 1.0))
    place = Matrix([up.cross(inward), up, inward]).transposed().to_4x4()       # x = up x z, so the text reads from inside the recess
    place.translation = Vector(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, -FILL_GAP / 2))
    at = ins.matrix_world @ place
    half = (k * (max(xs) - min(xs)) / 2, k * (max(ys) - min(ys)) / 2)
    found = {"at": at, "half": half, "frame": MARK_FRAME * 2 * half[1], "cuts": letter_cuts(mesh),
             "wall": (length / 2 + 1e-3, FILL_GAP / 2 - ENGRAVE - 1e-3, FILL_GAP / 2 + 1e-3)}
    before = mark_counts(body.data, found)
    framed = frame_wall(body.data, found)
    mesh.materials.append(ins.data.materials[0])        # the same gold as the digit
    coll = bpy.data.collections.new("mark_cutter")
    bpy.context.scene.collection.children.link(coll)
    cut = bpy.data.objects.new("mark_cut", mesh)
    cut.matrix_world = at
    cut.hide_render = cut.hide_viewport = True
    link(cut, coll)
    mod = body.modifiers.new("mark", "BOOLEAN")
    mod.operand_type, mod.collection, mod.solver, mod.operation = "COLLECTION", coll, "EXACT", "DIFFERENCE"
    mod.material_mode = "TRANSFER"
    bake(body)
    bpy.data.objects.remove(cut)
    bpy.data.meshes.remove(mesh)
    bpy.data.collections.remove(coll)
    region, wall = mark_counts(body.data, found)
    print(f"mark={MARK_TEXT} on the 1 of {text!r}, wall of {ins.name} length={want:.5f} depth={MARK_DEPTH} wall={length:.4f} long")
    print(f"mark triangles: region (frame + letters) {before[0]} -> {region}, wall plane {before[1]} -> {wall}, framed={framed}")
    return found


def letter_cuts(mesh):
    """x positions between the letters of a text mesh: the middle of every gap between the letters' x ranges. A letter is a set of
    connected polygons; pieces whose x ranges overlap (the dot of the i) count as one letter."""
    parent = list(range(len(mesh.vertices)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for poly in mesh.polygons:
        for v in poly.vertices[1:]:
            parent[find(v)] = find(poly.vertices[0])
    spans = {}
    for v in mesh.vertices:
        lo, hi = spans.get(find(v.index), (v.co.x, v.co.x))
        spans[find(v.index)] = (min(lo, v.co.x), max(hi, v.co.x))
    letters = []
    for lo, hi in sorted(spans.values()):
        if letters and lo <= letters[-1][1]:
            letters[-1][1] = max(letters[-1][1], hi)
        else:
            letters.append([lo, hi])
    return [(a[1] + b[0]) / 2 for a, b in zip(letters, letters[1:])]


def frame_wall(mesh, mark):
    """Splits the wall piece the mark sits on into real edges in the wall plane: a rectangle round the text box (MARK_FRAME of the
    text height free on every side) cut into one cell per letter (at mark["cuts"]), and triangles joining the rectangle to the wall's
    four corners. The wall must be one quad (two coplanar triangles are merged first); otherwise nothing changes and False is
    returned. The boolean then only triangulates the cells, each letter against its own cell's corners, so no long thin triangles
    run from the letters across the wall. The extra points on the rectangle's top and bottom edges are joined to the far corners
    by two fans of triangles, so the top and bottom pieces are triangulated here, balanced left and right."""
    inv = mark["at"].inverted()
    wx, y0, y1 = mark["wall"]
    bm = bmesh.new()
    bm.from_mesh(mesh)
    local = lambda v: inv @ v.co
    on = [f for f in bm.faces if all(abs(local(v).z) < 1e-5 and abs(local(v).x) <= wx and y0 <= local(v).y <= y1 for v in f.verts)]
    if len(on) > 1:
        on = bmesh.ops.dissolve_faces(bm, faces=on)["region"]
    hw, hh = mark["half"]
    fx, fy = hw + mark["frame"], hh + mark["frame"]
    corners = list(on[0].verts) if len(on) == 1 else []
    quadrants = {(local(v).x > 0, local(v).y > 0): v for v in corners}
    if len(corners) != 4 or len(quadrants) != 4 or any(abs(local(v).x) <= fx or abs(local(v).y) <= fy for v in corners):
        bm.free()
        return False
    old = on[0]
    old.normal_update()
    flip = old.normal.dot(mark["at"].to_3x3() @ Vector((0.0, 0.0, 1.0))) < 0     # keep the old face's side
    material, smooth = old.material_index, old.smooth
    xs = [-fx] + mark["cuts"] + [fx]
    low = [bm.verts.new(mark["at"] @ Vector((x, -fy, 0.0))) for x in xs]           # inner bottom edge, left to right
    top = [bm.verts.new(mark["at"] @ Vector((x, fy, 0.0))) for x in xs]            # inner top edge
    bl, br, tr, tl = quadrants[(False, False)], quadrants[(True, False)], quadrants[(True, True)], quadrants[(False, True)]
    m = len(xs) - 1
    s = m // 2                                                                      # where the left fan meets the right fan
    rings = [[low[j], low[j + 1], top[j + 1], top[j]] for j in range(m)]           # the cells
    rings += [[bl, low[0], top[0], tl], [br, tr, top[m], low[m]]]                  # left and right pieces
    rings += [[bl, br, low[s]]] + [[br, low[j + 1], low[j]] for j in range(s, m)] + [[bl, low[j + 1], low[j]] for j in range(s)]
    rings += [[tr, tl, top[s]]] + [[tl, top[j], top[j + 1]] for j in range(s)] + [[tr, top[j], top[j + 1]] for j in range(s, m)]
    bmesh.ops.delete(bm, geom=[old], context="FACES_ONLY")
    for ring in rings:
        face = bm.faces.new(ring[::-1] if flip else ring)
        face.material_index, face.smooth = material, smooth
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return True


def mark_counts(mesh, mark):
    """(triangles in the mark region, triangles of the wall plane piece) of a die-space mesh, to see what the mark costs. Region: the
    frame box from the wall plane down to the letters' floor (the frame face, the letters, their walls and floors). Wall piece: the
    faces lying in the wall plane along the wall piece, the frame face and the trapezoids included."""
    inv = np.array(mark["at"].inverted())
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    x, y, z = (co.reshape(-1, 3).astype(np.float64) @ inv[:3, :3].T + inv[:3, 3]).T
    hw, hh = mark["half"]
    wx, y0, y1 = mark["wall"]
    fx, fy = hw + mark["frame"] + MARK_TOL, hh + mark["frame"] + MARK_TOL
    box = (np.abs(x) <= fx) & (np.abs(y) <= fy) & (z >= -MARK_DEPTH - MARK_TOL) & (z <= MARK_TOL)
    plane = (np.abs(z) < 1e-5) & (np.abs(x) <= wx) & (y >= y0) & (y <= y1)
    vert_of = np.empty(len(mesh.loops), np.int32)
    start, total = np.empty(len(mesh.polygons), np.int32), np.empty(len(mesh.polygons), np.int32)
    mesh.loops.foreach_get("vertex_index", vert_of)
    mesh.polygons.foreach_get("loop_start", start)
    mesh.polygons.foreach_get("loop_total", total)
    count = lambda flag: int((total[np.logical_and.reduceat(flag[vert_of], start)] - 2).sum())     # an n-gon is n - 2 triangles
    return count(box), count(plane)


def in_mark(mesh, mark, floor=False):
    """Vertex indices of a die-space mesh near the mark. floor=True: only the floor of the letters (MARK_DEPTH into the wall), for the
    safety check. Otherwise every vertex lying in the wall plane along the wall piece the mark sits on: after frame_wall these are only
    the frame, the letters' rims and the wall's four corners, which the decimation must keep (an edge between a kept and a free
    vertex could still be collapsed and drag the frame away)."""
    inv = mark["at"].inverted()
    hw, hh = mark["half"]
    wx, y0, y1 = mark["wall"]
    out = []
    for v in mesh.vertices:
        x, y, z = inv @ v.co
        if floor:
            ok = abs(x) <= hw + MARK_TOL and abs(y) <= hh + MARK_TOL and abs(z + MARK_DEPTH) <= MARK_TOL
        else:
            ok = abs(x) <= wx and y0 <= y <= y1 and abs(z) <= 2 * MARK_DEPTH
        if ok:
            out.append(v.index)
    return out


# --------------------------------------------------------------------------- materials

def node(nt, kind, **props):
    """New shader node with properties set."""
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def marble_material(seed):
    """Matte black stone with sparse, thin light veins; `seed` moves/rotates the pattern."""
    rnd = random.Random(seed)
    mat = bpy.data.materials.new("marble")
    nt = mat.node_tree
    nt.nodes.clear()
    out = node(nt, "ShaderNodeOutputMaterial")
    bsdf = node(nt, "ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    coord = node(nt, "ShaderNodeTexCoord")
    mp = node(nt, "ShaderNodeMapping")
    mp.inputs["Location"].default_value = [rnd.uniform(0, 50) for _ in range(3)]
    mp.inputs["Rotation"].default_value = [rnd.uniform(0, 6.28) for _ in range(3)]
    nt.links.new(coord.outputs["Object"], mp.inputs["Vector"])

    def vein_layer(scale, distortion, thick, density, strength, direction):
        """One set of thin flowing lines: wavy marble bands cut to their zero crossings, faded by a noise mask."""
        wv = node(nt, "ShaderNodeTexWave", wave_type="BANDS", bands_direction=direction, wave_profile="SIN")
        wv.inputs["Scale"].default_value, wv.inputs["Distortion"].default_value = scale, distortion
        wv.inputs["Detail"].default_value, wv.inputs["Detail Scale"].default_value = 3.0, 1.5
        nt.links.new(mp.outputs["Vector"], wv.inputs["Vector"])
        d = node(nt, "ShaderNodeMath", operation="SUBTRACT")
        d.inputs[1].default_value = 0.5
        nt.links.new(wv.outputs["Fac"], d.inputs[0])
        ab = node(nt, "ShaderNodeMath", operation="ABSOLUTE")
        nt.links.new(d.outputs["Value"], ab.inputs[0])
        line = node(nt, "ShaderNodeMapRange")           # near the zero crossing -> 1 (thin line)
        line.inputs["From Min"].default_value, line.inputs["From Max"].default_value = 0.0, thick
        line.inputs["To Min"].default_value, line.inputs["To Max"].default_value = 1.0, 0.0
        nt.links.new(ab.outputs["Value"], line.inputs["Value"])
        m = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")   # where the veins exist at all
        m.inputs["Scale"].default_value, m.inputs["Detail"].default_value = 1.6, 4
        nt.links.new(mp.outputs["Vector"], m.inputs["Vector"])
        mm = node(nt, "ShaderNodeMapRange")
        mm.inputs["From Min"].default_value, mm.inputs["From Max"].default_value = density, density + 0.10
        nt.links.new(m.outputs["Fac"], mm.inputs["Value"])
        prod = node(nt, "ShaderNodeMath", operation="MULTIPLY", use_clamp=True)
        nt.links.new(line.outputs["Result"], prod.inputs[0])
        nt.links.new(mm.outputs["Result"], prod.inputs[1])
        k = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        k.inputs[1].default_value = strength
        nt.links.new(prod.outputs["Value"], k.inputs[0])
        return k.outputs["Value"]

    def scratch_layer(strength):
        """Faint short scratches: noise squashed into thin plates (random direction), thresholded, sparse."""
        st = node(nt, "ShaderNodeMapping")
        st.inputs["Rotation"].default_value = [rnd.uniform(0, 6.28) for _ in range(3)]
        st.inputs["Scale"].default_value = (14.0, 140.0, 14.0)
        nt.links.new(mp.outputs["Vector"], st.inputs["Vector"])
        n = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")
        n.inputs["Scale"].default_value, n.inputs["Detail"].default_value = 1.0, 1.0
        nt.links.new(st.outputs["Vector"], n.inputs["Vector"])
        th = node(nt, "ShaderNodeMapRange")
        th.inputs["From Min"].default_value, th.inputs["From Max"].default_value = 0.635, 0.665
        nt.links.new(n.outputs["Fac"], th.inputs["Value"])
        m = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")
        m.inputs["Scale"].default_value, m.inputs["Detail"].default_value = 3.0, 2.0
        nt.links.new(mp.outputs["Vector"], m.inputs["Vector"])
        mm = node(nt, "ShaderNodeMapRange")
        mm.inputs["From Min"].default_value, mm.inputs["From Max"].default_value = 0.55, 0.66
        nt.links.new(m.outputs["Fac"], mm.inputs["Value"])
        prod = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        nt.links.new(th.outputs["Result"], prod.inputs[0])
        nt.links.new(mm.outputs["Result"], prod.inputs[1])
        k = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        k.inputs[1].default_value = strength
        nt.links.new(prod.outputs["Value"], k.inputs[0])
        return k.outputs["Value"]

    def speckle_layer(strength):
        """Fine light flecks like in the d20 stone: tiny voronoi dots, thinned out by a noise mask."""
        v = node(nt, "ShaderNodeTexVoronoi", voronoi_dimensions="3D")
        v.inputs["Scale"].default_value = 260.0
        nt.links.new(mp.outputs["Vector"], v.inputs["Vector"])
        dots = node(nt, "ShaderNodeMapRange")
        dots.inputs["From Min"].default_value, dots.inputs["From Max"].default_value = 0.0, 0.26
        dots.inputs["To Min"].default_value, dots.inputs["To Max"].default_value = 1.0, 0.0
        nt.links.new(v.outputs["Distance"], dots.inputs["Value"])
        m = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")
        m.inputs["Scale"].default_value, m.inputs["Detail"].default_value = 18.0, 2.0
        nt.links.new(mp.outputs["Vector"], m.inputs["Vector"])
        mm = node(nt, "ShaderNodeMapRange")
        mm.inputs["From Min"].default_value, mm.inputs["From Max"].default_value = 0.42, 0.55
        nt.links.new(m.outputs["Fac"], mm.inputs["Value"])
        prod = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        nt.links.new(dots.outputs["Result"], prod.inputs[0])
        nt.links.new(mm.outputs["Result"], prod.inputs[1])
        k = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        k.inputs[1].default_value = strength
        nt.links.new(prod.outputs["Value"], k.inputs[0])
        return k.outputs["Value"]

    layers = [vein_layer(0.9, 3.0, 0.014, 0.44, 0.9, "DIAGONAL"),      # a few fine veins
              vein_layer(2.1, 4.5, 0.018, 0.55, 0.45, "DIAGONAL"),
              scratch_layer(0.14), speckle_layer(0.7)]
    both = layers[0]
    for extra in layers[1:]:                                           # add all light marks, clamped to 0..1
        add = node(nt, "ShaderNodeMath", operation="ADD", use_clamp=True)
        nt.links.new(both, add.inputs[0])
        nt.links.new(extra, add.inputs[1])
        both = add.outputs["Value"]

    # base tone: very dark, slightly mottled
    tone = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")
    tone.inputs["Scale"].default_value, tone.inputs["Detail"].default_value = 3.0, 6
    nt.links.new(mp.outputs["Vector"], tone.inputs["Vector"])
    ramp = node(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.005, 0.005, 0.006, 1)
    ramp.color_ramp.elements[1].color = (0.020, 0.020, 0.023, 1)
    nt.links.new(tone.outputs["Fac"], ramp.inputs["Fac"])
    mix = node(nt, "ShaderNodeMix", data_type="RGBA")
    mix.inputs["B"].default_value = (0.80, 0.80, 0.83, 1)
    nt.links.new(both, mix.inputs["Factor"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["A"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    rough = node(nt, "ShaderNodeMapRange")      # veins are a bit rougher than the polished stone
    rough.inputs["To Min"].default_value, rough.inputs["To Max"].default_value = 0.55, 0.68
    nt.links.new(both, rough.inputs["Value"])
    nt.links.new(rough.outputs["Result"], bsdf.inputs["Roughness"])

    grain = node(nt, "ShaderNodeTexNoise", noise_dimensions="3D")   # fine stone grain as a tiny bump
    grain.inputs["Scale"].default_value, grain.inputs["Detail"].default_value = 220.0, 3
    nt.links.new(mp.outputs["Vector"], grain.inputs["Vector"])
    bump = node(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value, bump.inputs["Distance"].default_value = 0.07, 0.02
    nt.links.new(grain.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def gold_material(name, color, metallic, rough):
    """Simple gold paint/metal material."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Emission Color"].default_value = color        # a little self-light keeps shadowed digits readable
    b.inputs["Emission Strength"].default_value = 0.07
    return mat


def restyle(mat, style):
    """Gives a gold material the look of GOLD[style] ("dark" or "bright") in place, so every object using it follows."""
    color, metallic, rough = GOLD[style]
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Emission Color"].default_value = color


# --------------------------------------------------------------------------- glTF export

def to_gltf(v):
    """Blender (Z up) vector to glTF (Y up) coordinates."""
    return [round(v.x, 6), round(v.z, 6), round(-v.y, 6)]


def hull_data(spec):
    """The sharp (unbeveled) polyhedron in glTF axes at the .glb scale (0.5): verts, and faces as vertex index lists
    wound counter-clockwise seen from outside (the Z-up to Y-up change is a pure rotation, so winding survives)."""
    verts = [Vector(v) for v in spec["verts"]]
    faces = []
    for f in spec["faces"]:
        ids = list(f["verts"])
        p = [verts[i] for i in ids]
        if (p[1] - p[0]).cross(p[2] - p[0]).dot(sum(p, Vector())) < 0:     # normal points inward: flip the order
            ids.reverse()
        faces.append(ids)
    return {"verts": [to_gltf(v * 0.5) for v in verts], "faces": faces}


def write_faces_json(path, spec, die, mirror):
    """Maps every face's outward normal (glTF axes) to its number; `up` is where the digit's top points. A face whose
    number differs from the value it reads as (d10's 0 = 10) also has `value`, and one that prints something else than its number
    (d10t's "30") also has `text`. `physics` (when the die has one) is the collider shape a web viewer should use. `hull` is the sharp polyhedron.
    A vertex die (d4) lists its corners instead: `normal` is the corner that points up, `front` the edge direction
    that faces the camera (pose "edge")."""
    vertex = spec.get("read") == "vertex"
    faces = []
    if vertex:
        for corner, number in corner_numbers(spec).items():
            front, up = vertex_frame(spec, corner, "edge")
            faces.append({"number": number, "normal": to_gltf(up), "front": to_gltf(front)})
    else:
        for face in spec["faces"]:
            _, normal, up = face_frame(spec["verts"], face)
            entry = {"number": face["number"], "normal": to_gltf(normal), "up": to_gltf(up)}
            for key in ("value", "text"):
                if key in face:
                    entry[key] = face[key]
            faces.append(entry)
    faces.sort(key=lambda f: f["number"])
    data = {"die": die, "read": "vertex" if vertex else "face", "axes": "gltf Y-up", "mirror": mirror, "faces": faces,
            "hull": hull_data(spec)}
    if spec.get("physics"):
        data["physics"] = spec["physics"]
    Path(path).write_text(json.dumps(data, indent=1) + "\n")


def bake_image(obj, name, size, bake_type, extra=None):
    """Bakes `bake_type` of all of obj's materials into one new image through its active UV map."""
    img = bpy.data.images.new(name, size, size, alpha=False)
    for mat in obj.data.materials:
        nt = mat.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.nodes.active = tex           # the bake writes into the active image node
    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.device = "CPU"
    bpy.context.scene.cycles.samples = 16
    bpy.ops.object.bake(type=bake_type, margin=8, use_clear=True, **(extra or {}))
    return img


def unwrap_stone(obj, is_stone):
    """Smart-UV-unwraps only the stone faces (so they get the whole texture); digit faces are parked outside 0..1 and bake nothing."""
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(mesh)
    bpy.ops.mesh.select_all(action="DESELECT")
    bm.faces.ensure_lookup_table()
    for f, st in zip(bm.faces, is_stone):
        if st:
            f.select_set(True)
    bmesh.update_edit_mesh(mesh)
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    uv = mesh.uv_layers.active.data
    for poly, st in zip(mesh.polygons, is_stone):
        if not st:
            for li in poly.loop_indices:
                uv[li].uv = (3.0, 3.0)


def stamp_glb(path):
    """Writes the copyright and licence into the .glb's `asset` block (asset.copyright, asset.extras). Only the JSON chunk is
    rewritten (compact, padded with spaces to 4 bytes, lengths updated); every byte after it, the binary chunk, is copied unchanged."""
    data = Path(path).read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", data, 0)          # 12-byte header: "glTF", 2, total length
    size, kind = struct.unpack_from("<I4s", data, 12)                 # first chunk: length, type
    if magic != b"glTF" or version != 2 or kind != b"JSON":
        sys.exit(f"{path} is not a glTF 2 binary")
    doc = json.loads(data[20:20 + size].decode("utf-8"))
    extras = {"licence": LICENCE}
    if REPO_URL:
        extras["source"] = REPO_URL
    else:
        print("warning: REPO_URL is empty, asset.extras has no source")
    packed = {"KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization"} & set(doc.get("extensionsUsed", []))
    floats = all(doc["accessors"][pr["attributes"]["POSITION"]]["componentType"] == 5126 for m in doc["meshes"] for pr in m["primitives"])
    if packed or not floats:        # compressed or quantized positions would round the tiny mark away
        sys.exit(f"{path}: the export is compressed or quantized ({sorted(packed) or 'integer positions'}), the mark is not exact")
    doc["asset"].update(copyright=COPYRIGHT, extras=extras)
    text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % 4)
    rest = data[20 + size:]                                           # the BIN chunk, untouched
    head = struct.pack("<4sII", b"glTF", 2, 20 + len(text) + len(rest)) + struct.pack("<I4s", len(text), b"JSON")
    Path(path).write_bytes(head + text + rest)


def face_planes(spec, scale=1.0):
    """The face planes of the sharp polyhedron as numpy arrays (unit normals, outward; plane distances from the middle), the
    distances multiplied by `scale`."""
    planes = []
    for f in spec["faces"]:
        pts = [Vector(spec["verts"][i]) for i in f["verts"]]
        c = sum(pts, Vector()) / len(pts)
        n = (pts[1] - pts[0]).cross(pts[2] - pts[0]).normalized()
        n = n if n.dot(c) > 0 else -n
        planes.append((tuple(n), n.dot(c) * scale))
    return np.array([n for n, _ in planes]), np.array([d for _, d in planes])


def cap_only(obj):
    """Keeps only the top cap of a gold fill (the polygons at its highest z). Its side walls lie exactly on the gold wall of the cut
    and its bottom under the fill, so they can never be seen; dropping them from the export saves about three quarters of a fill."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    top = max(v.co.z for v in bm.verts)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not all(abs(v.co.z - top) < 1e-6 for v in f.verts)], context="FACES")
    bm.to_mesh(obj.data)
    bm.free()


def drop_floors(mesh, spec):
    """Deletes the floors of the number cuts from a die-space body mesh: the polygons lying on a plane ENGRAVE below a die face plane.
    The gold fill sits above them, so they can never be seen. Returns how many polygons were dropped."""
    wanted, dist = face_planes(spec)
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    on = np.abs(co.reshape(-1, 3) @ wanted.T - (dist - ENGRAVE)) < 1e-4      # (vertex, plane): on the floor plane below it
    vert_of = np.empty(len(mesh.loops), np.int32)
    start = np.empty(len(mesh.polygons), np.int32)
    mesh.loops.foreach_get("vertex_index", vert_of)
    mesh.polygons.foreach_get("loop_start", start)
    hit = np.nonzero(np.logical_and.reduceat(on[vert_of], start, axis=0).any(axis=1))[0]
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in hit], context="FACES")
    bm.to_mesh(mesh)
    bm.free()
    return len(hit)


def thin_stats(faces):
    """(share of triangles that are long and thin, worst ratio) of bmesh triangles; ratio = longest edge squared / area, thin above 50."""
    ratios = []
    for f in faces:
        a, b, c = (v.co for v in f.verts)
        area = (b - a).cross(c - a).length / 2
        ratios.append(max((b - a).length_squared, (c - b).length_squared, (a - c).length_squared) / area if area > 1e-18 else 1e9)
    return (sum(r > 50 for r in ratios) / len(ratios) if ratios else 0.0), max(ratios, default=0.0)


def fix_slivers(bm, tris):
    """Flips away the needle triangles (longest edge squared over area above 5000) that edge flipping cannot fix: three points on one
    line, where the 180 degree corner makes the flip look degenerate. The needle's long edge is shared with a second triangle; the
    two are replaced by the two triangles that use the middle point instead. Returns (the triangles, how many were fixed)."""
    keep, fixed = set(tris), 0
    for _ in range(3):
        bad = [f for f in keep if f.is_valid and thin_stats([f])[1] > 5000]
        done = 0
        for f in bad:
            if not f.is_valid:
                continue
            vs = list(f.verts)
            k = max(range(3), key=lambda i: (vs[i].co - vs[(i + 1) % 3].co).length_squared)        # the longest edge k -> k + 1
            p, q, m = vs[k], vs[(k + 1) % 3], vs[(k + 2) % 3]
            e = bm.edges.get((p, q))
            if e is None or len(e.link_faces) != 2:
                continue
            g = next(x for x in e.link_faces if x is not f)
            if len(g.verts) != 3 or g not in keep:
                continue
            x = next(v for v in g.verts if v is not p and v is not q)
            g.normal_update()
            material, smooth = f.material_index, f.smooth
            ok = all(((b.co - a.co).cross(c.co - a.co)).dot(g.normal) > 0 for a, b, c in ((m, p, x), (m, x, q)))
            if not ok:
                continue
            bmesh.ops.delete(bm, geom=[f, g], context="FACES_ONLY")
            bm.edges.remove(e)
            keep -= {f, g}
            for tri in ((m, p, x), (m, x, q)):
                new = bm.faces.new(tri)
                new.material_index, new.smooth = material, smooth
                keep.add(new)
            done += 1
        fixed += done
        if not done:
            break
    bm.faces.index_update()
    return sorted((f for f in keep if f.is_valid), key=lambda f: f.index), fixed


def tidy_flat(mesh, spec):
    """Re-triangulates the flat regions of a die-space mesh with well-shaped triangles: the stone polygons lying on a die face plane
    and the gold tops of the digits (the plane FILL_GAP below). Any n-gon or quad is triangulated with the beauty method, then edges
    are flipped (beautify fill) until the triangles are as evenly spaced as the existing points allow. Only edges inside a region are
    flipped, so the outlines of the digits, the frames' corners, the materials and every wall stay as they are, and no vertex is
    added or removed. (Merging the polygons first would only remove points; flipping from any start reaches the same result.)
    Points closer than 1e-7 are merged first, and needle triangles made of three points on a line are fixed (fix_slivers).
    Returns (triangles, thin share before, worst before, thin share after, worst after, needles fixed)."""
    wanted, dist = face_planes(spec)
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    pts = co.reshape(-1, 3)
    vert_of, start = np.empty(len(mesh.loops), np.int32), np.empty(len(mesh.polygons), np.int32)
    mesh.loops.foreach_get("vertex_index", vert_of)
    mesh.polygons.foreach_get("loop_start", start)
    flat = np.zeros(len(mesh.polygons), bool)
    for offset in (0.0, -FILL_GAP):                                     # the stone around the numbers, the tops of the digits
        on = np.abs(pts @ wanted.T - (dist + offset)) < 1e-5
        flat |= np.logical_and.reduceat(on[vert_of], start, axis=0).any(axis=1)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    faces = [bm.faces[i] for i in np.nonzero(flat)[0]]
    bmesh.ops.remove_doubles(bm, verts=list({v for f in faces for v in f.verts}), dist=1e-7)
    faces = [f for f in faces if f.is_valid]
    new = bmesh.ops.triangulate(bm, faces=faces, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
    bm.faces.index_update()
    tris = sorted({f for f in faces + new if f.is_valid and len(f.verts) == 3}, key=lambda f: f.index)     # the same order every run
    before = thin_stats(tris)
    tris, fixed = fix_slivers(bm, tris)
    inside = set(tris)
    edges = list({e for f in tris for e in f.edges if len(e.link_faces) == 2 and all(lf in inside for lf in e.link_faces)})
    if edges:
        bmesh.ops.beautify_fill(bm, faces=tris, edges=edges)
    bm.faces.index_update()
    tris, more = fix_slivers(bm, [f for f in tris if f.is_valid])
    fixed += more
    after = thin_stats(tris)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(tris), before[0], before[1], after[0], after[1], fixed


def flat_shade(mesh, spec, scale=0.5):
    """Makes the stone polygons that lie on a die face plane shade perfectly flat, while the bevels stay smooth. Why: after the
    cuts and the decimation the flat faces hold long thin triangles that share corners with the rounded bevel, and smooth normals
    (an average over the triangles round a corner) then lean those triangles toward the bevel, which shows as light streaks.
    Steps: (1) find the polygons whose corners all lie on one face plane (`scale` = the die's size change since the unit-radius
    plane data); (2) mark the edges between such a group and the rest sharp, so a smooth normal never mixes the two; (3) give every
    corner of a flat polygon the plane's normal as a custom normal. Returns (polygons made flat, max lean in degrees before,
    max lean after), the lean being the angle between a flat polygon's shading normal and its plane normal."""
    wanted, dist = face_planes(spec, scale)
    nv, nl, npoly, ne = len(mesh.vertices), len(mesh.loops), len(mesh.polygons), len(mesh.edges)
    co = np.empty(nv * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    vert_of, edge_of = np.empty(nl, np.int32), np.empty(nl, np.int32)
    mesh.loops.foreach_get("vertex_index", vert_of)
    mesh.loops.foreach_get("edge_index", edge_of)
    start, total = np.empty(npoly, np.int32), np.empty(npoly, np.int32)
    mesh.polygons.foreach_get("loop_start", start)
    mesh.polygons.foreach_get("loop_total", total)
    on = np.abs(co.reshape(-1, 3) @ wanted.T - dist) < FLAT_TOL * scale      # (vertex, plane): the vertex lies on the plane
    flat = np.logical_and.reduceat(on[vert_of], start, axis=0)               # (polygon, plane): all its corners do
    is_flat, plane = flat.any(axis=1), flat.argmax(axis=1)
    owner = np.repeat(np.arange(npoly), total)                               # polygon of every loop
    mine = is_flat[owner]                                                    # loops of flat polygons
    want = wanted[plane[owner]]                                              # the normal each loop should get

    def corner_normals():
        cn = np.empty(nl * 3, np.float32)
        mesh.corner_normals.foreach_get("vector", cn)
        return cn.reshape(-1, 3).astype(np.float64)

    def lean(cn):
        cos = np.clip((cn * want).sum(axis=1)[mine], -1.0, 1.0)
        return float(np.degrees(np.arccos(cos)).max()) if mine.any() else 0.0

    before = lean(corner_normals())
    if mine.any():
        group = np.where(is_flat, plane, -1)[owner]                          # -1: not flat; else which plane
        low, high = np.full(ne, 1 << 30), np.full(ne, -(1 << 30))
        np.minimum.at(low, edge_of, group)
        np.maximum.at(high, edge_of, group)
        sharp = np.empty(ne, np.bool_)
        mesh.edges.foreach_get("use_edge_sharp", sharp)
        mesh.edges.foreach_set("use_edge_sharp", sharp | (low != high))      # an edge between two different groups
        mesh.update()
        cn = corner_normals()
        cn[mine] = want[mine]
        mesh.normals_split_custom_set(cn.tolist())
    return int(is_flat.sum()), before, lean(corner_normals())


def export_glb(args, spec, body, inserts, mark=None):
    """Joins a copy of the die (body + gold digits), bakes only the stone into textures and writes a .glb with two materials.
    A `mark` (see cut_mark) is protected from the decimation and checked afterwards."""
    def dup(o):
        c = o.copy()
        c.data = o.data.copy()
        link(c)
        return c
    objs = [dup(body)] + [dup(o) for o in inserts]
    if args.drop_hidden:            # parts that can never be seen: the fills' walls and bottoms, the cuts' floors under the fills
        for o in objs[1:]:
            cap_only(o)
        print(f"hidden geometry dropped: {drop_floors(objs[0].data, spec)} floor polygons, fill walls and bottoms")
    copies = {}                                      # own material copies: baking must not touch the render ones
    for o in objs:
        for i, m in enumerate(o.data.materials):
            o.data.materials[i] = copies.setdefault(m.name, m.copy())
    die = objs[0]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = die
    bpy.ops.object.join()
    mesh = die.data
    if not args.no_beauty:
        n, thin0, worst0, thin1, worst1, fixed = tidy_flat(mesh, spec)
        print(f"flat regions: {n} triangles, long-thin {thin0:.0%} -> {thin1:.0%}, worst ratio {worst0:.0f} -> {worst1:.0f}, needles fixed {fixed}")
    mesh.calc_loop_triangles()
    tris = len(mesh.loop_triangles)
    max_tris = spec.get("max_tris", args.max_tris)   # the die's own limit, else --max-tris
    print(f"triangles before decimation: {tris} (limit {max_tris}, {'UNDER' if tris <= max_tris else 'OVER'})")
    floor = len(in_mark(mesh, mark, floor=True)) if mark else 0
    if mark and not floor:
        sys.exit("the mark was not cut into the model")
    if tris > max_tris:                              # keep it light for phones
        mod = die.modifiers.new("decimate", "DECIMATE")
        mod.ratio = max_tris / tris
        if mark:        # the tiny cut would be collapsed first: weight 0 = not decimated, 1 = free (everything but the mark's wall)
            keep = die.vertex_groups.new(name="keep")
            keep.add(list(range(len(mesh.vertices))), 1.0, "REPLACE")
            keep.add(in_mark(mesh, mark), 0.0, "REPLACE")
            mod.vertex_group = "keep"
        bake(die)
        die.vertex_groups.clear()
        mesh = die.data
        if mark and len(in_mark(mesh, mark, floor=True)) < 0.95 * floor:
            sys.exit("the decimation damaged the mark")
        mesh.calc_loop_triangles()
        print(f"decimate: ran, {tris} -> {len(mesh.loop_triangles)} triangles (lower digit_res or bevel_segments to stay under the limit)")
        tris = len(mesh.loop_triangles)
    else:
        print("decimate: skipped")
    die.scale = (0.5, 0.5, 0.5)                      # circumradius 0.5 -> about 1 unit across
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mesh = die.data
    stone = [i for i, m in enumerate(mesh.materials) if m.name.startswith("marble")]
    is_stone = [p.material_index in stone for p in mesh.polygons]
    unwrap_stone(die, is_stone)
    color = bake_image(die, "die_color", args.tex, "DIFFUSE", {"pass_filter": {"COLOR"}})
    rough = bake_image(die, "die_rough", args.tex, "ROUGHNESS")
    rough.colorspace_settings.name = "Non-Color"
    # two plain materials for glTF: "body" uses the baked stone images, "numbers" is untextured gold (crisp at any size)
    body_mat = bpy.data.materials.new("body")
    body_mat.use_nodes = True
    nt = body_mat.node_tree
    b = nt.nodes["Principled BSDF"]
    t1 = node(nt, "ShaderNodeTexImage", image=color)
    t2 = node(nt, "ShaderNodeTexImage", image=rough)
    sep = node(nt, "ShaderNodeSeparateColor")
    nt.links.new(t1.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(t2.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], b.inputs["Roughness"])
    b.inputs["Metallic"].default_value = 0.0
    gold_mat = gold_material("numbers", (0.96, 0.68, 0.20, 1), 0.7, 0.35)
    gold_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 0.0
    mesh.materials.clear()
    mesh.materials.append(body_mat)                  # slot 0: stone, slot 1: engraved digits (walls, floor, fill, underline)
    mesh.materials.append(gold_mat)
    for poly, st in zip(mesh.polygons, is_stone):
        poly.material_index = 0 if st else 1
    flats, before, after = flat_shade(die.data, spec)
    print(f"flat faces: {flats} polygons, shading lean max {before:.1f} -> {after:.1f} deg")
    if after > 2.0:
        print("warning: flat faces still shade tilted, expect light streaks")
    out = Path(args.glb)
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    die.select_set(True)
    kw = dict(filepath=str(out), export_format="GLB", use_selection=True, export_yup=True, export_normals=True, export_image_format="JPEG")
    plain = {"export_draco_mesh_compression_enable": False}     # no compression or quantization: the tiny mark must stay exact
    tries = [{"export_jpeg_quality": 88, **plain}, {"export_jpeg_quality": 88}, {}]     # older/newer Blender: drop unknown options
    for extra in tries[:-1]:
        try:
            bpy.ops.export_scene.gltf(**kw, **extra)
            break
        except TypeError:
            pass
    else:
        bpy.ops.export_scene.gltf(**kw, **tries[-1])
    stamp_glb(out)
    write_faces_json(out.with_suffix(".faces.json"), spec, args.die, args.mirror)
    print(f"glb={out} triangles={tris} texture={args.tex} bytes={out.stat().st_size}")
    bpy.data.objects.remove(die)


# --------------------------------------------------------------------------- scene

def orient(root, front, up, tilt):
    """Turns the die (die-space vectors) so `front` looks at the camera (-Y) and `up` points up (+Z), then leans it back
    by `tilt` degrees. A face die passes the face normal and its up direction."""
    right = up.cross(front)
    f = Matrix([right, up, front]).transposed()                     # die frame -> die space
    w = Matrix([(1, 0, 0), (0, 0, 1), (0, -1, 0)]).transposed()    # world: right=X, up=Z, toward camera=-Y
    lean = Matrix.Rotation(math.radians(-tilt), 3, "X")             # lifts the front toward +Z
    root.matrix_world = (lean @ w @ f.transposed()).to_4x4()


def make_camera(lens):
    """Perspective camera on the -Y axis, looking at the origin."""
    cam = bpy.data.cameras.new("cam")
    cam.lens, cam.sensor_width = lens, 36
    obj = link(bpy.data.objects.new("cam", cam))
    obj.location, obj.rotation_euler = (0, -20, 0), (math.pi / 2, 0, 0)
    bpy.context.scene.camera = obj
    return obj


def frame_camera(cam, body, fill):
    """Moves/shifts the camera so the die is centred and fills `fill` of the canvas (always from the camera's starting place)."""
    scene = bpy.context.scene
    cam.location.y, cam.data.shift_x, cam.data.shift_y = -20, 0.0, 0.0
    for _ in range(6):
        bpy.context.view_layer.update()
        pts = [world_to_camera_view(scene, cam, body.matrix_world @ v.co) for v in body.data.vertices]
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
        y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        cam.data.shift_x += (x0 + x1) / 2 - 0.5
        cam.data.shift_y += (y0 + y1) / 2 - 0.5
        cam.location.y *= max(x1 - x0, y1 - y0) / fill


def add_lights():
    """Soft studio light from the upper left, a weak fill and rim, and a dim gradient world for reflections."""
    def area(name, loc, size, energy, color=(1, 1, 1)):
        d = bpy.data.lights.new(name, "AREA")
        d.size, d.energy, d.color = size, energy, color
        o = link(bpy.data.objects.new(name, d))
        o.location = loc
        direction = Vector((0, 0, 0)) - Vector(loc)
        o.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    area("key", (-5.0, -6.0, 6.0), 4.0, 1100, (1.0, 0.97, 0.92))
    area("fill", (6.0, -5.0, 1.0), 6.0, 260, (0.9, 0.94, 1.0))
    area("under", (0.0, -5.0, -4.0), 5.0, 260, (1.0, 0.96, 0.9))      # lights the face below the rolled one
    area("rim", (3.0, 5.0, 5.0), 4.0, 300)
    world = bpy.data.worlds.new("world")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.35, 0.36, 0.40, 1)
    bg.inputs["Strength"].default_value = 0.22


def configure_render(args):
    """Cycles, denoising, transparent PNG."""
    s = bpy.context.scene
    s.render.engine = "CYCLES"
    s.render.resolution_x = s.render.resolution_y = args.res
    s.render.resolution_percentage = 100
    s.render.film_transparent = True
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGBA"
    s.view_settings.view_transform = "Standard"
    s.cycles.samples = args.samples
    s.cycles.use_denoising = True
    s.cycles.denoiser = "OPENIMAGEDENOISE"
    s.cycles.device = "CPU"
    s.cycles.use_adaptive_sampling = True
    s.cycles.max_bounces = 6
    used = "CPU"
    if args.device != "cpu":                # auto / gpu: OPTIX, then CUDA, else quietly the CPU
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                if any(d.type == kind for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = d.type == kind
                    s.cycles.device = "GPU"
                    used = kind
                    break
            except Exception:
                continue
    print(f"device={used}")
    return used


def main():
    args = parse_args()
    spec = dict(DICE[args.die])
    for key, value in (("digit_res", args.digit_res), ("bevel_segments", args.bevel_seg), ("groove_sides", args.groove_sides)):
        if value:
            spec[key] = value               # a command line value beats the die's own and the global default
    if callable(spec["verts"]):             # d100: the shape is worked out on first use
        spec["verts"] = spec["verts"]()
    spec["faces"] = spec["build"]()
    if args.mirror:
        spec["faces"] = spec["build"](mirror=True)
    if args.faces:                          # face data only: no scene, font, render or bake
        Path(args.faces).parent.mkdir(parents=True, exist_ok=True)
        write_faces_json(args.faces, spec, args.die, args.mirror)
        print(f"faces={args.faces}")
        return
    batch = parse_results(args.results, spec) if args.results else []
    if batch and not args.out:
        sys.exit("--results needs --out (with {n} in it)")
    if len(batch) > 1 and "{n}" not in args.out:
        sys.exit("--results with several results needs {n} in --out")
    poses = {r: pose_for(spec, args, r) for r in (batch or [args.result])}     # also checks every result exists
    tilt = args.tilt if args.tilt is not None else spec.get("tilt", 2.0)
    font_path = args.font or next((f for f in FONTS if Path(f).exists()), "")
    if not font_path:
        sys.exit("no font found; pass --font")
    reset_scene()
    font = bpy.data.fonts.load(font_path)
    mats = {k: gold_material(f"gold_{k}", *v) for k, v in GOLD.items()}
    if batch:       # one gold material per number (shared by its cutter, fill and cut walls), restyled before every render
        golds = {n: gold_material(f"gold_{n}", *GOLD["dark"]) for n in {lb["number"] for f in spec["faces"] for lb in face_labels(f, spec)}}
        mat_for = golds.__getitem__
    else:
        shown = args.result if args.out else 0      # glb: all digits one gold
        mat_for = lambda n: mats["bright" if n == shown else "dark"]
    body = build_body(spec)
    body.data.materials.append(marble_material(args.seed))
    inserts, mark = engrave_numbers(body, spec, font, mat_for, not args.no_mark, not args.no_frames)
    root = link(bpy.data.objects.new("die", None))
    for o in [body] + inserts:
        o.parent = root                                  # parent first, then keep the placement as local
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_basis = o.matrix_world.copy() if o is not body else Matrix.Identity(4)
    if args.glb:
        export_glb(args, spec, body, inserts, mark)
    if not args.out:
        return
    cam = make_camera(args.lens)
    configure_render(args)
    add_lights()
    for result, (front, up, label) in poses.items():
        for n, m in (golds.items() if batch else []):
            restyle(m, "bright" if n == result else "dark")     # only this result's digits are bright
        orient(root, front, up, tilt)
        frame_camera(cam, body, args.fill)
        out = Path(args.out.replace("{n}", label))
        out.parent.mkdir(parents=True, exist_ok=True)
        bpy.context.scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print(f"saved={out}")
    if args.blend:
        Path(args.blend).parent.mkdir(parents=True, exist_ok=True)
        bpy.context.preferences.filepaths.save_version = 0      # no .blend1 backup files
        bpy.ops.wm.save_as_mainfile(filepath=args.blend, copy=True)
    print(f"font={font_path} saved={out}")


main()
