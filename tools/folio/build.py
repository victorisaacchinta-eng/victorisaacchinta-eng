#!/usr/bin/env python3
"""
Image generator for the github.com/victorisaacchinta-eng profile README.

A Swiss poster in white, signal red and black, with the pictures drawn in
ASCII: a microchip and four emblems are raymarched from signed distance
fields, shaded, and turned into characters frame by frame, so they spin.
Fonts (Jersey 10, Silkscreen, Pixelify Sans, Commit Mono, all OFL-1.1) are subset and embedded,
so GitHub shows the SVGs exactly as built.

    pip install numpy fonttools brotli pyfiglet
    python3 tools/folio/build.py
Output goes to assets/folio/.
"""
import math
import os
import urllib.request
import base64
import random

import numpy as np
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "assets", "folio")
FONT_DIR = os.path.join(HERE, "fonts")
LIGHT_DIR = (-0.45, 1.0, 0.75)


# Raymarcher: signed distance fields, soft shadows, ambient occlusion
def nrm(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def rot(ax, ay, az):
    ax, ay, az = map(math.radians, (ax, ay, az))
    Rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    Ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    Rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def local(p, c, R=None):
    q = p - np.asarray(c, float)
    return q @ R if R is not None else q


def sd_sphere(q, r):
    return np.linalg.norm(q, axis=-1) - r


def sd_box(q, b, rr=0.0):
    d = np.abs(q) - (np.asarray(b, float) - rr)
    return np.linalg.norm(np.maximum(d, 0), axis=-1) + np.minimum(d.max(-1), 0) - rr


def sd_torus(q, R, r):
    a = np.sqrt(q[..., 0] ** 2 + q[..., 2] ** 2) - R
    return np.sqrt(a ** 2 + q[..., 1] ** 2) - r


def sd_cyl(q, r, h, rr=0.0):
    d0 = np.sqrt(q[..., 0] ** 2 + q[..., 2] ** 2) - (r - rr)
    d1 = np.abs(q[..., 1]) - (h - rr)
    return np.minimum(np.maximum(d0, d1), 0) + np.sqrt(np.maximum(d0, 0) ** 2 + np.maximum(d1, 0) ** 2) - rr


def sd_octa(q, s):
    return (np.abs(q).sum(-1) - s) * 0.57735027


def sd_cone(q, h, r1, r2):
    qx = np.sqrt(q[..., 0] ** 2 + q[..., 2] ** 2)
    qy = q[..., 1]
    k1 = np.array([r2, h])
    k2 = np.array([r2 - r1, 2 * h])
    cax = qx - np.minimum(qx, np.where(qy < 0, r1, r2))
    cay = np.abs(qy) - h
    dk = (k1[0] - qx) * k2[0] + (k1[1] - qy) * k2[1]
    tt = np.clip(dk / (k2 @ k2), 0, 1)
    cbx = qx - k1[0] + k2[0] * tt
    cby = qy - k1[1] + k2[1] * tt
    s = np.where((cbx < 0) & (cay < 0), -1.0, 1.0)
    return s * np.sqrt(np.minimum(cax ** 2 + cay ** 2, cbx ** 2 + cby ** 2))


class Cam:
    def __init__(self, pos, tgt, fov, W, H):
        self.pos = np.asarray(pos, float)
        f = nrm(np.asarray(tgt, float) - self.pos)
        r = nrm(np.cross(f, [0, 1, 0]))
        u = np.cross(r, f)
        self.f, self.r, self.u = f, r, u
        self.k = math.tan(math.radians(fov) / 2)
        self.W, self.H = W, H
        self.aspect = W / H

    def rays(self):
        xs = ((np.arange(self.W) + 0.5) / self.W * 2 - 1) * self.aspect
        ys = -((np.arange(self.H) + 0.5) / self.H * 2 - 1)
        X, Y = np.meshgrid(xs, ys)
        return nrm(self.f + (X[..., None] * self.k) * self.r + (Y[..., None] * self.k) * self.u)

    def project(self, P):
        v = np.asarray(P, float) - self.pos
        z = v @ self.f
        X = (v @ self.r) / (z * self.k) / self.aspect
        Y = (v @ self.u) / (z * self.k)
        return ((X + 1) / 2 * self.W, (1 - Y) / 2 * self.H)


def march(scene, ro, rd, steps=140, tmax=40.0):
    t = np.zeros(rd.shape[:-1])
    hit = np.zeros(rd.shape[:-1], bool)
    alive = np.ones(rd.shape[:-1], bool)
    for _ in range(steps):
        idx = np.nonzero(alive)
        if not idx[0].size:
            break
        p = ro[idx] + rd[idx] * t[idx][..., None]
        d = scene(p)
        h = d < 8e-4
        far = t[idx] > tmax
        hit[tuple(i[h] for i in idx)] = True
        t[idx] = t[idx] + np.where(h, 0, d * 0.92)
        dead = h | far
        alive[tuple(i[dead] for i in idx)] = False
    return t, hit


def normal(scene, p, e=1e-3):
    ex, ey, ez = np.array([e, 0, 0]), np.array([0, e, 0]), np.array([0, 0, e])
    return nrm(np.stack([scene(p + ex) - scene(p - ex),
                         scene(p + ey) - scene(p - ey),
                         scene(p + ez) - scene(p - ez)], -1))


def soft_shadow(scene, ro, ld, k=10.0, steps=72):
    res = np.ones(ro.shape[:-1])
    t = np.full(ro.shape[:-1], 0.03)
    for _ in range(steps):
        h = scene(ro + ld * t[..., None])
        res = np.minimum(res, k * h / t)
        t = t + np.clip(h, 0.015, 0.25)
    return np.clip(res, 0, 1)


def ambient_occ(scene, p, n):
    occ, sca = 0.0, 1.0
    for i in range(5):
        hr = 0.03 + 0.12 * i
        occ = occ + (hr - scene(p + n * hr)) * sca
        sca *= 0.85
    return np.clip(1 - 1.6 * occ, 0, 1)


def sd_capsule(p, a, b, r):
    a, b = np.asarray(a, float), np.asarray(b, float)
    pa, ba = p - a, b - a
    h = np.clip((pa @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(pa - h[..., None] * ba, axis=-1) - r


def sd_ellipsoid(q, r):
    r = np.asarray(r, float)
    k0 = np.linalg.norm(q / r, axis=-1)
    k1 = np.linalg.norm(q / (r * r), axis=-1)
    return k0 * (k0 - 1) / np.maximum(k1, 1e-9)


def to_world(c, R, v):
    return np.asarray(c, float) + np.asarray(v, float) @ R.T


def xy_ring(q):
    """Swap y and z so torus / cylinder helpers lie in the xy plane (facing the camera)."""
    return q[..., [0, 2, 1]]


# Fonts are subset to the characters each image uses and embedded as base64
# woff2, so the SVGs need nothing from the network when GitHub shows them.
import base64
import io
import random
from fontTools import subset as ftsubset

FONTSOURCE = "https://cdn.jsdelivr.net/fontsource/fonts/"
FONT_FILES = {
    "Commit400": "commit-mono@5.3.0/latin-400-normal.woff2",
    "Commit700": "commit-mono@5.3.0/latin-700-normal.woff2",
    "Jersey": "jersey-10@5.3.0/latin-400-normal.woff2",
    "Silk700": "silkscreen@5.3.0/latin-700-normal.woff2",
    "Silk400": "silkscreen@5.3.0/latin-400-normal.woff2",
    "Pixel400": "pixelify-sans@5.3.0/latin-400-normal.woff2",
    "Pixel500": "pixelify-sans@5.3.0/latin-500-normal.woff2",
}


def measure(font, size, text):
    f = TTFont(font_path(font))
    cmap, hmtx, upem = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    return sum(hmtx[cmap.get(ord(ch), cmap[32])][0] for ch in text) * size / upem


def wrap(font, size, text, width):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if cur and measure(font, size, trial) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return lines + [cur]


def font_path(key):
    os.makedirs(FONT_DIR, exist_ok=True)
    p = os.path.join(FONT_DIR, key + ".woff2")
    if not os.path.exists(p):
        urllib.request.urlretrieve(FONTSOURCE + FONT_FILES[key], p)
    return p


def embed(key, text):
    opts = ftsubset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga"]
    f = TTFont(font_path(key))
    s = ftsubset.Subsetter(opts)
    s.populate(text=text + " ")
    s.subset(f)
    buf = io.BytesIO()
    f.flavor = "woff2"
    f.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f'@font-face{{font-family:{key};src:url(data:font/woff2;base64,{b64}) format("woff2")}}'


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self, W, H, bg, title, desc):
        self.W, self.H, self.bg, self.title, self.desc = W, H, bg, title, desc
        self.body, self.css, self.used = [], [], {}

    def text(self, font, s, size, x, y, fill, anchor="start", ls=0, cls="", extra=""):
        self.used[font] = self.used.get(font, "") + s
        c = f' class="{cls}"' if cls else ""
        self.body.append(f'<text{c} x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" '
                         f'text-anchor="{anchor}" letter-spacing="{ls}" xml:space="preserve"{extra}>{esc(s)}</text>')

    def block(self, font, rows, size, lh, x, y, fill, cls=""):
        """A block of preformatted rows (ASCII art) as one text element."""
        self.used[font] = self.used.get(font, "") + "".join(rows)
        c = f' class="{cls}"' if cls else ""
        spans = "".join(f'<tspan x="{x:.1f}" dy="{0 if i == 0 else lh}">{esc(r)}</tspan>' for i, r in enumerate(rows))
        self.body.append(f'<text{c} y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" xml:space="preserve">{spans}</text>')

    def add(self, s):
        self.body.append(s)

    def svg(self):
        fonts = "".join(embed(k, v) for k, v in self.used.items())
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W} {self.H}" width="{self.W}" height="{self.H}" '
                f'role="img" aria-labelledby="t d"><title id="t">{esc(self.title)}</title><desc id="d">{esc(self.desc)}</desc>'
                f'<style>{fonts}{" ".join(self.css)}</style><rect width="{self.W}" height="{self.H}" fill="{self.bg}"/>'
                + "".join(self.body) + "</svg>")


def frames_css(prefix, n, period):
    """n stacked frames shown one at a time, forever; frame 0 shows when motion is off."""
    css = [f"@keyframes {prefix}k{{0%{{opacity:1}}{100 / n:.4f}%{{opacity:0}}100%{{opacity:0}}}}",
           f".{prefix}{{opacity:0;animation:{prefix}k {period}s step-end infinite}}"]
    for k in range(n):
        css.append(f".{prefix}{k}{{animation-delay:{k * period / n - period:.4f}s}}")
    css.append(f"@media (prefers-reduced-motion:reduce){{.{prefix}{{animation:none}}.{prefix}0{{opacity:1}}}}")
    return " ".join(css)


def window_css(name, start, end, period, first=False):
    """Visible only between start and end (seconds) of a repeating period."""
    a, b = 100 * start / period, 100 * end / period
    kf = (f"@keyframes {name}{{0%{{opacity:{1 if first else 0}}}{a:.3f}%{{opacity:1}}{b:.3f}%{{opacity:0}}100%{{opacity:0}}}}"
          if not first else f"@keyframes {name}{{0%{{opacity:1}}{b:.3f}%{{opacity:0}}100%{{opacity:0}}}}")
    return kf + f".{name}{{opacity:{1 if first else 0};animation:{name} {period}s step-end infinite}}"


# ASCII rendering
RAMP = " .,:;-=+*#%@"


def to_ascii(L, mask, cols, rows, ramp=RAMP, gamma=1.0):
    """Average a high-res tone map into a character grid. L in 0..1, 1 = densest."""
    H, W = L.shape
    ys = np.linspace(0, H, rows + 1).astype(int)
    xs = np.linspace(0, W, cols + 1).astype(int)
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            m = mask[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            if m.mean() < 0.35:
                line.append(" ")
                continue
            v = L[ys[r]:ys[r + 1], xs[c]:xs[c + 1]][m].mean() ** gamma
            line.append(ramp[1 + int(np.clip(v, 0, 0.999) * (len(ramp) - 1))] if v > 0.02 else ramp[1])
        out.append("".join(line).rstrip())
    return out


def shade(scene, cam, glow=None, light=LIGHT_DIR, k=(0.06, 0.62, 0.22, 0.35)):
    ld = nrm(np.asarray(light, float))
    rd = cam.rays()
    ro = np.broadcast_to(cam.pos, rd.shape).copy()
    t, hit = march(scene, ro, rd)
    L = np.zeros(hit.shape)
    idx = np.nonzero(hit)
    p = ro[idx] + rd[idx] * t[idx][..., None]
    n = normal(scene, p)
    v = -rd[idx]
    dif = np.clip((n * ld).sum(-1), 0, 1)
    ao = ambient_occ(scene, p, n)
    refl = 2 * (n * ld).sum(-1, keepdims=True) * n - ld
    spec = np.clip((refl * v).sum(-1), 0, 1) ** 20
    L[idx] = np.clip(k[0] + k[1] * dif * ao + k[2] * ao + k[3] * spec, 0, 1)
    if glow is not None:
        em = glow(p) < 4e-3
        L[tuple(i[em] for i in idx)] = 1.0
    return L, hit


def roty(p, deg, c=(0, 0, 0)):
    a = math.radians(deg)
    q = p - np.asarray(c, float)
    x = q[..., 0] * math.cos(a) + q[..., 2] * math.sin(a)
    z = -q[..., 0] * math.sin(a) + q[..., 2] * math.cos(a)
    return np.stack([x, q[..., 1], z], -1) + np.asarray(c, float)




def swap_yz(q):
    """Point cylinders and rings along z (towards the camera) instead of y."""
    return q[..., [0, 2, 1]]


def to_ascii_max(T, cols, rows, ramp=RAMP, gamma=1.0):
    """Like to_ascii, but each cell takes its brightest pixel, so thin lines survive."""
    H, W = T.shape
    ys = np.linspace(0, H, rows + 1).astype(int)
    xs = np.linspace(0, W, cols + 1).astype(int)
    out = []
    for r in range(rows):
        line = []
        for c in range(cols):
            v = T[ys[r]:ys[r + 1], xs[c]:xs[c + 1]].max() ** gamma
            line.append(" " if v < 0.06 else ramp[1 + int(np.clip(v, 0, 0.999) * (len(ramp) - 1))])
        out.append("".join(line).rstrip())
    return out


def glass(scene, cam):
    """Edges and highlights only, the way glass reads in the dark."""
    ld = nrm(np.array([-0.5, 0.8, 0.6]))
    rd = cam.rays()
    ro = np.broadcast_to(cam.pos, rd.shape).copy()
    t, hit = march(scene, ro, rd)
    T = np.zeros(hit.shape)
    idx = np.nonzero(hit)
    p = ro[idx] + rd[idx] * t[idx][..., None]
    n = normal(scene, p)
    v = -rd[idx]
    rim = np.clip(1 - np.abs((n * v).sum(-1)), 0, 1) ** 1.6
    refl = 2 * (n * ld).sum(-1, keepdims=True) * n - ld
    spec = np.clip((refl * v).sum(-1), 0, 1) ** 14
    dif = np.clip((n * ld).sum(-1), 0, 1)
    T[idx] = np.clip(0.06 + 0.45 * rim + 0.5 * spec + 0.1 * dif, 0, 1)
    # edges: where the surface normal jumps (prism corners, panel edges) or the silhouette ends
    N = np.zeros(hit.shape + (3,))
    N[idx] = n
    dn = np.zeros(hit.shape)
    for ax in (0, 1):
        d = np.linalg.norm(N - np.roll(N, 1, axis=ax), axis=-1)
        dn = np.maximum(dn, np.maximum(d, np.roll(d, -1, axis=ax)))
    T = np.maximum(T, np.clip(dn * 1.2, 0, 1) * (dn > 0.25))
    return T


def plexus_tone(W, H, ang, seed=11):
    """A node network on a sphere: points joined to their nearest neighbours, nearer ones brighter."""
    n = 110
    k = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * k / n)
    th = math.pi * (1 + 5 ** 0.5) * k
    rnd = np.random.default_rng(seed)
    r = 1 + rnd.normal(0, 0.03, n)
    P = np.stack([np.sin(phi) * np.cos(th), np.cos(phi), np.sin(phi) * np.sin(th)], -1) * r[:, None]
    d = np.linalg.norm(P[:, None] - P[None], axis=-1)
    edges = {tuple(sorted((i, j))) for i in range(n) for j in np.argsort(d[i])[1:4]}
    a, tl = math.radians(ang), math.radians(18)
    Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(tl), -math.sin(tl)], [0, math.sin(tl), math.cos(tl)]])
    Q = P @ Ry.T @ Rx.T
    f = 3.4
    sx = W / 2 + Q[:, 0] / (f - Q[:, 2]) * W * 1.45
    sy = H / 2 - Q[:, 1] / (f - Q[:, 2]) * W * 1.45
    depth = (Q[:, 2] + 1) / 2
    T = np.zeros((H, W))
    for i, j in edges:
        m = 40
        u = np.linspace(0, 1, m)
        xs = (sx[i] + (sx[j] - sx[i]) * u).astype(int)
        ys = (sy[i] + (sy[j] - sy[i]) * u).astype(int)
        b = 0.18 + 0.45 * (depth[i] + (depth[j] - depth[i]) * u)
        ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
        np.maximum.at(T, (ys[ok], xs[ok]), b[ok])
    yy, xx = np.mgrid[0:H, 0:W]
    for i in range(n):
        rad = 1.5 + 2.5 * depth[i]
        m = (xx - sx[i]) ** 2 + (yy - sy[i]) ** 2 < rad ** 2
        T[m] = np.maximum(T[m], 0.55 + 0.45 * depth[i])
    return T


def sd_fan(p, spread):
    """Glass panels hinged on one vertical axis, fanned open."""
    d = np.full(p.shape[:-1], 9.0)
    m = 12
    for i in range(m):
        a = spread + 2 * math.pi * i / m
        q = roty(p, -math.degrees(a) - 90.0)  # the fan opens towards the camera
        d = np.minimum(d, sd_box(q - np.array([0.52, 1.0, 0]), (0.5, 0.75, 0.012), 0.004))
    return d


def sd_vault(p, ang):
    """A vault mechanism facing the camera: two rings of teeth turning opposite ways around a chip."""
    q = p - np.array([0, 1.0, 0])
    x, y, z = q[..., 0], q[..., 1], q[..., 2]
    r = np.sqrt(x ** 2 + y ** 2)
    t = np.arctan2(y, x)
    ring = lambda R, w, h: np.maximum(np.abs(r - R) - w, np.abs(z) - h)
    d = np.minimum(ring(1.0, 0.07, 0.12), ring(0.62, 0.04, 0.08))

    def teeth(R, count, off, ln, w, h):
        a = (t + off) % (2 * math.pi / count) - math.pi / count
        lx, ly = r * np.cos(a) - R, r * np.sin(a)
        return np.maximum(np.maximum(np.abs(lx) - ln, np.abs(ly) - w), np.abs(z) - h)

    d = np.minimum(d, teeth(0.84, 28, math.radians(ang), 0.09, 0.035, 0.09))
    d = np.minimum(d, teeth(0.46, 16, -math.radians(ang * 1.6), 0.08, 0.04, 0.07))
    d = np.minimum(d, sd_box(q - np.array([0, 0, 0.02]), (0.2, 0.2, 0.06), 0.02))
    return d


def sd_monolith(p):
    """A tall hexagonal glass prism."""
    q = np.abs(p - np.array([0, 1.15, 0]))
    k = np.array([-0.8660254, 0.5])
    xz = np.stack([q[..., 0], q[..., 2]], -1)
    dot = np.minimum(xz @ k, 0)
    xz = xz - 2 * dot[..., None] * k
    r = 0.34
    dx = np.linalg.norm(xz - np.stack([np.clip(xz[..., 0], -r * 0.57735, r * 0.57735), np.full(xz.shape[:-1], r)], -1), axis=-1) * np.sign(xz[..., 1] - r)
    dy = q[..., 1] - 1.15
    return np.minimum(np.maximum(dx, dy), 0) + np.hypot(np.maximum(dx, 0), np.maximum(dy, 0))


def object_frames(kind, cols, rows, n, cw, ch):
    W = cols * 3
    H = int(round(rows * 3 * ch / cw))
    out = []
    for k in range(n):
        ph = k / n
        if kind == "plexus":
            T = plexus_tone(W, H, 360 * ph)
        elif kind == "fan":
            cam = Cam((0.0, 2.7, 5.6), (0, 0.95, 0), 24, W, H)
            T = glass(lambda p, s=2 * math.pi * ph / 12: sd_fan(p, s), cam)
        elif kind == "vault":
            cam = Cam((1.2, 1.6, 4.6), (0, 1.0, 0), 30, W, H)
            T = glass(lambda p, a=360 * ph / 4: sd_vault(p, a), cam)
            T = np.where(T > 0, np.clip(T + 0.15, 0, 1), 0)
        else:
            cam = Cam((0.0, 1.6, 6.4), (0, 1.15, 0), 26, W, H)
            T = glass(lambda p, a=120 * ph: sd_monolith(roty(p, a)), cam)
        out.append(to_ascii_max(T, cols, rows, gamma=1.0))
    return out


def scramble(text, progress, rnd):
    pool = "!<>-_/[]{}=+*^?#%$&01"
    keep = int(len(text) * progress)
    return "".join(ch if (i < keep or ch == " ") else rnd.choice(pool) for i, ch in enumerate(text))


# Content
NAME = ("Victor", "Isaac")
ROLE = "Engineer, product builder, founder."
DECKS = [  # what the decoding line cycles through
    "building agents that read, check and act",
    "building gesture and voice interfaces",
    "building 3D for the browser",
    "building products from zero to one",
]
FACTS = [("Founder", "Rotciv Inc."), ("Product", "Founder's Office, Interseqt"),
         ("Record", "3x national-level hackathon wins"), ("Based", "Hyderabad, India")]
WORK_TITLE = "What I work on"
WORK = [
    dict(obj="plexus", title="Agents", body="Autonomous systems, multimodal intelligence and agentic workflows."),
    dict(obj="fan", title="Interfaces", body="Spatial computing, gesture-driven systems and human-machine interaction."),
    dict(obj="vault", title="Security", body="Security engineering, ethical hacking and resilient AI systems."),
    dict(obj="monolith", title="Product", body="Product strategy, Founder's Office execution and ideas built into reality."),
]
MARQUEE = "SAPERE AUDE  +  PHIL 4:13  +  "

# Colours, taken from the dithered phosphor posters on Victor's Pinterest board
BLACK, LIME, FOREST, MINT, WHITE = "#050505", "#C6F350", "#296246", "#B3CEC7", "#F2F4EF"


def gif_data(path):
    return "data:image/gif;base64," + base64.b64encode(open(path, "rb").read()).decode()


def build_masthead():
    W, H = 1600, 1000
    sv = Svg(W, H, BLACK, "Victor Isaac",
             "Victor Isaac. Engineer, product builder, founder, Hyderabad, India. Founder of Rotciv Inc., Founder's "
             "Office at Interseqt, 3x national-level hackathon wins. A dithered globe turns on the right, starting over India.")
    M = 84
    globe = os.path.join(OUT, "globe.gif")
    gs = 660
    sv.add(f'<image href="{gif_data(globe)}" x="{W - gs - 30}" y="{(H - gs) / 2 - 40}" width="{gs}" height="{gs}" '
           f'style="image-rendering:pixelated"/>')
    sv.text("Commit400", "lat 17.38 N  lon 78.48 E", 18, W - 30 - gs / 2, (H + gs) / 2 - 10, FOREST, "middle")

    prompt = "~/victorisaacchinta-eng $ whoami"
    sv.text("Commit400", prompt, 22, M, 84, MINT)
    sv.add(f'<rect class="cur" x="{M + len(prompt) * 22 * 0.6 + 8:.1f}" y="66" width="12" height="22" fill="{LIME}"/>')
    sv.css.append("@keyframes blink{50%{opacity:0}}.cur{animation:blink 1.1s step-end infinite}"
                  "@media (prefers-reduced-motion:reduce){.cur{animation:none}}")

    ns = min(300, 700 / max(measure("Jersey", 1, w) for w in NAME))
    sv.text("Jersey", NAME[0], ns, M - 8, 100 + ns * 0.72, LIME)
    sv.text("Jersey", NAME[1], ns, M - 8, 100 + ns * 0.72 + ns * 0.72, LIME)
    sv.text("Pixel500", ROLE, 40, M, 594, WHITE)

    rnd = random.Random(7)
    slot, steps, dt = 3.5, 8, 0.06
    period = slot * len(DECKS)
    sv.text("Commit700", ">", 26, M, 646, LIME)
    for d, line in enumerate(DECKS):
        t0 = d * slot
        if d == 0:  # the first line is already there on frame one, so a frozen render reads cleanly
            sv.text("Commit400", line, 26, M + 30, 646, MINT, cls="dkst")
            sv.css.append(window_css("dkst", 0, slot, period, first=True))
            continue
        for s in range(steps):
            name = f"dk{d}s{s}"
            a = t0 + s * dt
            sv.text("Commit400", scramble(line, s / steps, rnd), 26, M + 30, 646, MINT, cls=name)
            sv.css.append(window_css(name, a, a + dt, period))
        name = f"dk{d}h"
        sv.text("Commit400", line, 26, M + 30, 646, MINT, cls=name)
        sv.css.append(window_css(name, t0 + steps * dt, t0 + slot, period))
    sv.css.append("@media (prefers-reduced-motion:reduce){[class^=dk]{animation:none!important;opacity:0!important}.dkst{opacity:1!important}}")

    gx, gy, gw = M, 770, 420
    vs = min(30, (gw - 16) / max(measure("Pixel500", 1, v) for _, v in FACTS))
    for i, (lab, val) in enumerate(FACTS):
        x = gx + (i % 2) * (gw + 30)
        y = gy + (i // 2) * 108
        sv.text("Silk700", lab.upper(), 16, x, y, LIME, ls=1)
        sv.text("Pixel500", val, vs, x, y + 40, WHITE)
    return sv.svg()


def build_marquee():
    import pyfiglet
    W, H = 1600, 150
    sv = Svg(W, H, LIME, "Sapere aude", "A scrolling banner in ASCII block letters: Sapere aude, Philippians 4:13.")
    rows = [r for r in pyfiglet.figlet_format(MARQUEE, font="ansi_shadow", width=2000).split("\n") if r.strip()]
    n = max(len(r) for r in rows)
    rows = [r.ljust(n) for r in rows]
    size, cw, lh = 17, 17 * 0.6, 18
    width = n * cw
    y0 = (H - lh * len(rows)) / 2 + lh * 0.8
    sv.add('<g class="mq">')
    for rep in range(3):
        sv.block("Commit400", rows, size, lh, rep * width, y0, BLACK)
    sv.add("</g>")
    sv.css.append(f"@keyframes mq{{to{{transform:translateX(-{width:.1f}px)}}}}.mq{{animation:mq 26s linear infinite}}"
                  "@media (prefers-reduced-motion:reduce){.mq{animation:none}}")
    return sv.svg()


def build_work(cache):
    W, H = 1600, 760
    sv = Svg(W, H, BLACK, WORK_TITLE,
             WORK_TITLE + ". " + " ".join(f"{c['title']}: {c['body']}" for c in WORK) +
             " Each area has a moving object drawn in ASCII: a node network sphere, a fan of glass panels, a turning vault mechanism and a glass monolith.")
    M = 84
    sv.text("Silk700", WORK_TITLE.upper(), 64, M - 4, 150, WHITE)
    sv.add(f'<rect x="{M}" y="186" width="120" height="10" fill="{LIME}"/>')
    gap = 48
    cwid = (W - 2 * M - gap * 3) / 4
    size, cw, ch = 8, 8 * 0.6, 8 * 1.0
    cols, rows, n = int(cwid / cw), 40, 24
    for i, c in enumerate(WORK):
        x0 = M + i * (cwid + gap)
        key = "obj-" + c["obj"]
        if key not in cache:
            cache[key] = object_frames(c["obj"], cols, rows, n, cw, ch)
        pre = f"e{i}f"
        for k, rws in enumerate(cache[key]):
            sv.block("Commit700", rws, size, ch, x0, 236, LIME, f"{pre} {pre}{k}")
        sv.css.append(frames_css(pre, n, 4.8 + i * 0.4))
        sv.text("Silk700", c["title"].upper(), 32, x0, 600, LIME)
        lines = wrap("Pixel400", 21, c["body"], cwid)
        assert len(lines) <= 4, c["title"]
        for j, ln in enumerate(lines):
            sv.text("Pixel400", ln, 21, x0, 642 + j * 28, MINT)
    return sv.svg()


def main():
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith(".svg"):
            os.remove(os.path.join(OUT, old))
    cache = {}
    files = {"masthead": build_masthead(), "marquee": build_marquee(), "work": build_work(cache)}
    for name, svg in files.items():
        p = os.path.join(OUT, f"{name}.svg")
        with open(p, "w") as fh:
            fh.write(svg)
        print(f"{os.path.relpath(p, ROOT):30s} {len(svg) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
