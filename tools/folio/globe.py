#!/usr/bin/env python3
"""
A turning Earth, ordered-dithered into lime pixels on black, saved as a GIF.

Land comes from Natural Earth (public domain) via the world-atlas package:
    npm pack world-atlas && tar xzf world-atlas-*.tgz
    python3 tools/folio/globe.py package/land-50m.json
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "assets", "folio", "globe.gif")

BLACK, LIME, FOREST = (5, 5, 5), (198, 243, 80), (41, 98, 70)

BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]) / 64.0


def land_mask(path, W=2048, H=1024):
    """Rasterise the TopoJSON land polygons onto an equirectangular grid."""
    topo = json.load(open(path))
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return [((lon + 180) / 360 * W, (90 - lat) / 180 * H) for lon, lat in pts]

    img = Image.new("1", (W, H), 0)
    geoms = topo["objects"]["land"]["geometries"]
    for g in geoms:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        for poly in polys:
            for k, r in enumerate(poly):
                layer = Image.new("1", (W, H), 0)
                ImageDraw.Draw(layer).polygon(ring(r), fill=1)
                img = Image.fromarray(np.asarray(img) ^ np.asarray(layer))
    return np.asarray(img)


def frame(mask, S, rot, tilt=18.0):
    H, W = mask.shape
    yy, xx = np.mgrid[0:S, 0:S].astype(float)
    u = (xx + 0.5) / S * 2 - 1
    v = 1 - (yy + 0.5) / S * 2
    R = 0.86
    r2 = (u ** 2 + v ** 2) / R ** 2
    on = r2 <= 1
    z = np.sqrt(np.clip(1 - r2, 0, 1))
    x, y = u / R, v / R
    t = math.radians(tilt)
    y2 = y * math.cos(t) + z * math.sin(t)
    z2 = -y * math.sin(t) + z * math.cos(t)
    lat = np.degrees(np.arcsin(np.clip(y2, -1, 1)))
    lon = (np.degrees(np.arctan2(x, z2)) + rot) % 360 - 180
    mi = np.clip(((90 - lat) / 180 * H).astype(int), 0, H - 1)
    mj = np.clip(((lon + 180) / 360 * W).astype(int), 0, W - 1)
    land = mask[mi, mj] & on
    light = np.array([-0.4, 0.45, 0.8])
    lam = np.clip(x * light[0] + y * light[1] + z * light[2], 0, 1)
    rim = np.clip(1 - z, 0, 1) ** 2
    tone_land = 0.18 + 0.82 * lam
    tone_sea = 0.04 + 0.16 * lam + 0.35 * rim
    grat = ((np.abs((lat + 90) % 20 - 10) > 9.7) | (np.abs((lon + 180) % 20 - 10) > 9.75)) & ~land & on
    th = BAYER8[(yy.astype(int) % 8), (xx.astype(int) % 8)]
    out = np.zeros((S, S), np.uint8)
    out[on & land & (tone_land > th)] = 1
    out[on & ~land & (tone_sea > th)] = 2
    out[grat & (lam > 0.15) & (th < 0.7)] = 2
    # a thin orbit with one satellite, passing in front of the globe
    ang = math.radians(rot * 2)
    for k in range(720):
        a = 2 * math.pi * k / 720
        ox, oy = 0.98 * math.cos(a), 0.22 * math.sin(a)
        front = math.sin(a) > 0
        px, py = int((ox + 1) / 2 * S), int((1 - (oy * 1.0 - 0.05)) / 2 * S)
        if 0 <= px < S and 0 <= py < S and (front or not on[py, px]) and k % 4 == 0:
            out[py, px] = 2
    sxp = int((0.98 * math.cos(ang) + 1) / 2 * S)
    syp = int((1 - (0.22 * math.sin(ang) - 0.05)) / 2 * S)
    if math.sin(ang) > 0 or not on[min(max(syp, 0), S - 1), min(max(sxp, 0), S - 1)]:
        out[max(syp - 2, 0):syp + 3, max(sxp - 2, 0):sxp + 3] = 1
    return out


def main():
    mask = land_mask(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wa/package/land-50m.json")
    S, n, scale = 200, 36, 2
    pal = list(BLACK) + list(LIME) + list(FOREST) + [0] * (256 * 3 - 9)
    frames = []
    for k in range(n):
        f = Image.fromarray(frame(mask, S, 360.0 * k / n - 78.0), "P")
        f.putpalette(pal)
        frames.append(f.resize((S * scale, S * scale), Image.NEAREST))
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=110, loop=0, optimize=True)
    print(OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
