#!/usr/bin/env python3
"""
Image generator for the github.com/victorisaacchinta-eng profile README.

The look comes from Bidri, the Deccan craft of hammering silver wire into
blackened metal. Every picture is raymarched from signed distance fields and
cut into engraved lines, the inlay is projected onto the surface, and all type
is outlined into paths so GitHub shows the files exactly as built.

Edit the CONTENT section, then run:
    pip install numpy fonttools brotli uharfbuzz scikit-image
    python3 tools/folio/build.py
Output goes to assets/folio/ (a light and a dark version of each image).
Type: Big Shoulders Inline Display and Big Shoulders Display (Patric King),
Schibsted Grotesk (Schibsted). All three are OFL-1.1, fetched from Fontsource.
"""
import math
import os
import urllib.request

import numpy as np
import uharfbuzz as hb
from skimage.measure import find_contours
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "assets", "folio")
FONT_DIR = os.path.join(HERE, "fonts")


# CONTENT. Keep every claim something you can defend in an interview.
# Nothing here names a project, so it doesn't need editing when you ship one.
MAST = {
    "first": "VICTOR",
    "last": "ISAAC",
    "role": "Engineer, product builder, founder.",
    # cycles under the role line, one at a time
    "decks": [
        "I collect whys before I collect tools.",
        "I build agents that show their work.",
        "I design for the hand, not the screen.",
        "I ship the version that tells the truth.",
    ],
    "facts": [
        ("Founder", "Rotciv Inc."),
        ("Product", "Founder's Office, Interseqt"),
        ("Record", "Three national hackathon wins"),
        ("From", "ACE Engineering College"),
    ],
    "seal_ring": "THREE NATIONAL HACKATHON WINS  /  SAPERE AUDE  /  ",
    "seal_center": "III",
    "caption": "After Bidri: silver hammered into blackened metal.",
}

CREDO_TITLE = "What I build by"
CREDO = [
    dict(emblem="scales", title="Show the work.",
         body="Agents that cite their sources and stop before they guess."),
    dict(emblem="lens", title="Look closer.",
         body="The real problem hides under the obvious one. Find it first."),
    dict(emblem="key", title="Guard the keys.",
         body="Security is a design decision, not a patch. Guardrails first."),
    dict(emblem="candle", title="Carry the light.",
         body="Build things worth inheriting. For people, not the demo."),
]

# Colours, each taken from something real.
#   paper   blackened Bidri zinc (dark) / raw zinc before blackening (light)
#   ink     hammered silver inlay
#   accent  the solder-mask blue of the circuit board in my avatar
PALETTES = {
    "dark": dict(paper="#121413", ink="#D9DAD4", muted="#8E938F", accent="#8FA7C2", deck="#B3B7B3",
                 inlay="#E2E3DD", inlay_shade="#8D928E", body="#121413"),
    "light": dict(paper="#E3E4DF", ink="#121413", muted="#535855", accent="#16335D", deck="#3F4441",
                  inlay="#F1F2EE", inlay_shade="#A9ADAA", body="#121413"),
}

# Motion: light passes once over each engraving the way it slides over polished
# silver, the seal turns slowly, and the line under the name cycles. Frame one
# is always complete, so a frozen render still shows everything.
MOTION_CSS = """
@keyframes sweepM{from{transform:translateY(0)}to{transform:translateY(1000px)}}
@keyframes sweepC{from{transform:translateY(0)}to{transform:translateY(460px)}}
.sweepM{animation:sweepM 3s cubic-bezier(.22,1,.36,1) .3s both}
.sweepC{animation:sweepC 2.4s cubic-bezier(.22,1,.36,1) both}
.d1{animation-delay:.3s}.d2{animation-delay:.5s}.d3{animation-delay:.7s}.d4{animation-delay:.9s}
@keyframes spin{to{transform:rotate(360deg)}}
.spin{transform-box:view-box;animation:spin 80s linear infinite}
@keyframes cyc{0%{opacity:0;transform:translateY(12px)}5%{opacity:1;transform:none}22%{opacity:1;transform:none}27%{opacity:0;transform:translateY(-8px)}100%{opacity:0}}
.ph{opacity:0;animation:cyc 18s infinite}.ph1{opacity:1}
.ph1{animation-delay:-.9s}.ph2{animation-delay:3.6s}.ph3{animation-delay:8.1s}.ph4{animation-delay:12.6s}
@media (prefers-reduced-motion:reduce){.sweepM,.sweepC,.spin,.ph{animation:none}.ph{opacity:0}.ph1{opacity:1}}
"""


def sheen_defs(pl, color):
    pl.add(f'<defs><linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{color}" stop-opacity="0"/>'
           f'<stop offset=".5" stop-color="{color}" stop-opacity=".55"/>'
           f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>')


def sheen(pl, cid, shape, w, cls):
    """A band of light that starts above the shape and passes down through it once."""
    pl.add(f'<clipPath id="{cid}">{shape}</clipPath><g clip-path="url(#{cid})">'
           f'<rect class="{cls}" x="-10" y="-200" width="{w + 20}" height="150" fill="url(#sheen)"/></g>')


# Type. Fontsource ships woff2; harfbuzz wants a plain font file, so each one is
# decompressed to .ttf once and cached in tools/folio/fonts/.
FONTSOURCE = "https://cdn.jsdelivr.net/fontsource/fonts/"
FONT_FILES = {
    "inline": "big-shoulders-inline-display@5.3.0/latin-800-normal.woff2",
    "head": "big-shoulders-display@5.3.0/latin-700-normal.woff2",
    "headm": "big-shoulders-display@5.3.0/latin-600-normal.woff2",
    "text": "schibsted-grotesk@5.3.0/latin-400-normal.woff2",
    "textm": "schibsted-grotesk@5.3.0/latin-500-normal.woff2",
    "texti": "schibsted-grotesk@5.3.0/latin-400-italic.woff2",
}


def ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    paths = {}
    for key, rel in FONT_FILES.items():
        ttf = os.path.join(FONT_DIR, key + ".ttf")
        if not os.path.exists(ttf):
            woff2 = ttf[:-4] + ".woff2"
            urllib.request.urlretrieve(FONTSOURCE + rel, woff2)
            f = TTFont(woff2)
            f.flavor = None
            f.save(ttf)
            os.remove(woff2)
        paths[key] = ttf
    return paths


def fmt(v):
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


class Face:
    def __init__(self, name, key):
        self.key = key
        self._glyphs = {}
        path = os.path.join(FONT_DIR, name)
        self.tt = TTFont(path)
        self.gs = self.tt.getGlyphSet()
        self.upem = self.tt["head"].unitsPerEm
        self.order = self.tt.getGlyphOrder()
        self.hbfont = hb.Font(hb.Face(hb.Blob.from_file_path(path)))

    def shape(self, text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hbfont, buf, {"kern": True, "liga": True})
        return [(self.order[i.codepoint], p.x_advance, p.x_offset, p.y_offset)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def width(self, text, size, tracking=0.0):
        g = self.shape(text)
        return sum(a for _, a, _, _ in g) * size / self.upem + tracking * size * max(len(g) - 1, 0)

    def glyph(self, name):
        """Outline of one glyph in font units, y flipped for SVG. Cached; reused via <use>."""
        if name not in self._glyphs:
            pen = SVGPathPen(self.gs, ntos=fmt)
            self.gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
            self._glyphs[name] = (f"{self.key}{self.order.index(name)}", pen.getCommands())
        return self._glyphs[name]

    def place(self, text, size, x, y, tracking=0.0, anchor="start"):
        w = self.width(text, size, tracking)
        if anchor == "middle":
            x -= w / 2
        elif anchor == "end":
            x -= w
        s = size / self.upem
        pen_x = 0.0
        out = []
        for name, adv, xo, yo in self.shape(text):
            out.append((name, x + (pen_x + xo) * s, y - yo * s, s))
            pen_x += adv + tracking * self.upem
        return out, w

    def wrap(self, text, size, maxw, tracking=0.0):
        lines, cur = [], ""
        for word in text.split(" "):
            trial = (cur + " " + word).strip()
            if self.width(trial, size, tracking) <= maxw or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def fit(self, text, size, maxw, tracking=0.0):
        w = self.width(text, size, tracking)
        return size if w <= maxw else size * maxw / w


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


def render(scene, cam, light, sky, floor_tone=0.80, floor_fade=None, glow=None):
    """Returns luminance L (0 dark .. 1 light) and relief map H (0..1) at cam.W x cam.H."""
    ld = nrm(np.asarray(light, float))
    rd = cam.rays()
    ro = np.broadcast_to(cam.pos, rd.shape).copy()
    t, hit = march(scene, ro, rd)

    L = sky.copy()
    Hm = np.zeros(hit.shape)

    # object
    idx = np.nonzero(hit)
    p = ro[idx] + rd[idx] * t[idx][..., None]
    n = normal(scene, p)
    v = -rd[idx]
    dif = np.clip((n * ld).sum(-1), 0, 1)
    sh = soft_shadow(scene, p + n * 2e-3, ld)
    ao = ambient_occ(scene, p, n)
    refl = 2 * (n * ld).sum(-1, keepdims=True) * n - ld
    spec = np.clip((refl * v).sum(-1), 0, 1) ** 28
    bounce = np.clip(-n[..., 1], 0, 1) * 0.10
    lum = 0.07 + 0.70 * dif * sh + 0.12 * ao + 0.22 * spec * sh + bounce
    L[idx] = np.clip(lum, 0, 0.86)
    Hm[idx] = np.clip((n * v).sum(-1), 0, 1)
    if glow is not None:  # emissive surfaces (a flame) read as pure light
        em = glow(p) < 4e-3
        L[tuple(i[em] for i in idx)] = 1.0
        Hm[tuple(i[em] for i in idx)] = 0.0

    # floor plane y = 0
    miss = ~hit & (rd[..., 1] < -1e-4)
    fidx = np.nonzero(miss)
    tg = -ro[fidx][..., 1] / rd[fidx][..., 1]
    pg = ro[fidx] + rd[fidx] * tg[..., None]
    shg = soft_shadow(scene, pg + np.array([0, 2e-3, 0]), ld, k=6.0)
    aog = ambient_occ(scene, pg, np.broadcast_to(np.array([0, 1.0, 0]), pg.shape))
    fl = floor_tone * (0.42 + 0.58 * shg) * (0.55 + 0.45 * aog)
    if floor_fade is not None:
        a = floor_fade(pg)
        fl = fl * a + sky[fidx] * (1 - a)
    L[fidx] = fl
    return L, Hm, hit


# Engraver: turns a tone map into variable-width parallel lines
def bilinear(A, x, y):
    H, W = A.shape
    x = np.clip(x, 0, W - 1.001)
    y = np.clip(y, 0, H - 1.001)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    a = A[y0, x0] * (1 - fx) + A[y0, x0 + 1] * fx
    b = A[y0 + 1, x0] * (1 - fx) + A[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[b] - pts[a]
        rel = pts[a + 1:b] - pts[a]
        ln = math.hypot(*seg) or 1e-9
        d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / ln
        i = int(np.argmax(d))
        if d[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return pts[keep]


def engrave(tone, relief, clip, spacing, angle, maxw, minw=0.35, disp=0.0, step=2.0, gate=None, tol=0.22):
    """Variable-width parallel lines. tone: 0..1 (1 = heaviest line). Returns SVG path data."""
    H, W = tone.shape
    a = math.radians(angle)
    d = np.array([math.cos(a), math.sin(a)])
    n = np.array([-math.sin(a), math.cos(a)])
    c0 = np.array([W / 2, H / 2])
    diag = math.hypot(W, H) / 2 + spacing * 2
    s = np.arange(-diag, diag, step)
    parts = []
    for c in np.arange(-diag, diag, spacing):
        base = c0 + n * c + d * s[:, None]
        P = base.copy()
        if disp:
            for _ in range(4):
                h = bilinear(relief, P[:, 0], P[:, 1])
                P = base - n * (disp * h)[:, None]
        inside = clip(P[:, 0], P[:, 1]) & (P[:, 0] >= 0) & (P[:, 0] < W) & (P[:, 1] >= 0) & (P[:, 1] < H)
        if not inside.any():
            continue
        t = bilinear(tone, P[:, 0], P[:, 1])
        if gate is not None:
            t = gate(t)
        w = np.minimum(maxw * t, spacing * 0.94)
        ok = inside & (w > minw)
        if not ok.any():
            continue
        edges = np.diff(np.concatenate([[0], ok.astype(int), [0]]))
        starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]
        for i0, i1 in zip(starts, ends):
            if i1 - i0 < 2:
                continue
            seg, ww = P[i0:i1], w[i0:i1, None]
            top = rdp(seg - n * ww / 2, tol)
            bot = rdp(seg + n * ww / 2, tol)[::-1]
            poly = np.vstack([top, bot])
            parts.append("M" + fmt(poly[0, 0]) + " " + fmt(poly[0, 1]) + "L" +
                         " ".join(fmt(x) + " " + fmt(y) for x, y in poly[1:]) + "Z")
    return "".join(parts)


TONE = {"light": dict(lo=0.04, gamma=1.1, hatch_from=0.60),
        "dark": dict(lo=0.42, gamma=1.25, hatch_from=0.80)}


def tone_curve(L, mode):
    t = 1 - L if mode == "light" else L
    lo, g = TONE[mode]["lo"], TONE[mode]["gamma"]
    return np.clip((t - lo) / (1 - lo), 0, 1) ** g


def engraving(L, Hm, mask, mode, clip, spacing, maxw, disp, hatch_angle=38):
    """Ground and figure are cut separately so lines never jump across a silhouette:
    the ground gets flat lines, the figure gets lines displaced by its relief."""
    hatch_from = TONE[mode]["hatch_from"]
    tone = tone_curve(L, mode)
    mf = mask.astype(float)
    on = lambda x, y: bilinear(mf, x, y) > 0.5
    ground = engrave(tone, Hm, lambda x, y: clip(x, y) & ~on(x, y), spacing, 0, maxw)
    figure = engrave(tone, Hm, lambda x, y: clip(x, y) & on(x, y), spacing * 0.92, 0, maxw * 0.95,
                     disp=disp, step=1.5, minw=0.22)
    hatch = engrave(tone, Hm, clip, spacing * 1.15, hatch_angle, maxw * 0.6,
                    gate=lambda t: np.clip((t - hatch_from) / (1 - hatch_from), 0, 1) ** 0.9)
    return ground + figure + hatch


def silhouette(mask, color, width):
    """Contour line around the rendered object, the engraver's outline."""
    m = mask.astype(float)
    k = np.array([1, 4, 6, 4, 1], float) / 16
    m = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, m)
    m = np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, m)
    parts = []
    for c in find_contours(m, 0.5):
        if len(c) < 12:
            continue
        xy = c[:, ::-1]
        h = len(xy) // 2  # closed curve: simplify each half so the endpoints differ
        pts = np.vstack([rdp(xy[:h + 1], 0.3), rdp(xy[h:], 0.3)[1:]])
        parts.append("M" + " ".join(fmt(x) + " " + fmt(y) for x, y in pts))
    return (f'<path fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" '
            f'stroke-linecap="round" d="{"".join(parts)}"/>')


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


def emblem_scales(p):
    d = sd_cyl(local(p, (0, 0.05, 0)), 0.5, 0.05, 0.02)
    d = np.minimum(d, sd_cyl(local(p, (0, 0.14, 0)), 0.2, 0.05, 0.02))
    d = np.minimum(d, sd_capsule(p, (0, 0.1, 0), (0, 1.7, 0), 0.05))
    d = np.minimum(d, sd_sphere(local(p, (0, 1.82, 0)), 0.085))
    c, R = (0, 1.64, 0), rot(0, 0, -7)
    d = np.minimum(d, sd_capsule(local(p, c, R), (-0.8, 0, 0), (0.8, 0, 0), 0.034))
    for sx in (-1, 1):
        end = to_world(c, R, (sx * 0.8, 0, 0))
        pan = end - np.array([0, 0.7, 0])
        rim = pan[1] + 0.04
        dish = np.maximum(sd_sphere(local(p, pan + np.array([0, 0.25, 0])), 0.32), p[..., 1] - rim)
        d = np.minimum(d, dish)
        for rx in (-0.22, 0.22):
            d = np.minimum(d, sd_capsule(p, end, pan + np.array([rx, 0.04, 0]), 0.012))
    return d


def emblem_lens(p):
    c, R = (-0.12, 1.32, 0), rot(8, 28, 0)
    q = local(p, c, R)
    rim = sd_torus(xy_ring(q), 0.46, 0.065)
    glass = sd_cyl(xy_ring(q), 0.44, 0.012)
    u = np.array([0.56, -0.83, 0])
    grip = np.minimum(sd_capsule(q, u * 0.5, u * 0.86, 0.06), sd_capsule(q, u * 0.86, u * 1.42, 0.092))
    return np.minimum(np.minimum(rim, glass), grip)


def emblem_key(p):
    c, R = (0.02, 1.0, 0), rot(12, 32, -16)
    q = local(p, c, R) / 1.22  # scaled up; distances corrected below
    return _key(q) * 1.22


def _key(q):
    d = sd_torus(xy_ring(q - np.array([-0.62, 0, 0])), 0.29, 0.075)
    d = np.minimum(d, sd_capsule(q, (-0.34, 0, 0), (0.92, 0, 0), 0.055))
    d = np.minimum(d, sd_capsule(q, (-0.36, 0, 0), (-0.25, 0, 0), 0.088))
    d = np.minimum(d, sd_box(q - np.array([0.62, -0.12, 0]), (0.05, 0.1, 0.04), 0.01))
    d = np.minimum(d, sd_box(q - np.array([0.81, -0.15, 0]), (0.06, 0.13, 0.04), 0.01))
    return d


FLAME = ((0, 1.78, 0), (0.085, 0.21, 0.085))


def emblem_candle_solid(p):
    d = sd_cyl(local(p, (0, 0.04, 0)), 0.62, 0.04, 0.02)
    d = np.minimum(d, sd_cyl(local(p, (0, 0.16, 0)), 0.2, 0.09, 0.03))
    d = np.minimum(d, sd_torus(xy_ring(local(p, (0.7, 0.12, 0))), 0.11, 0.028))
    d = np.minimum(d, sd_cyl(local(p, (0, 0.88, 0)), 0.14, 0.62, 0.025))
    d = np.minimum(d, sd_capsule(p, (0, 1.5, 0), (0.01, 1.6, 0), 0.012))
    return d


def emblem_candle_flame(p):
    return sd_ellipsoid(local(p, FLAME[0]), FLAME[1])


def emblem_candle(p):
    return np.minimum(emblem_candle_solid(p), emblem_candle_flame(p))


EMBLEMS = {
    "scales": (emblem_scales, None),
    "lens": (emblem_lens, None),
    "key": (emblem_key, None),
    "candle": (emblem_candle, emblem_candle_flame),
}


class Plate:
    def __init__(self, W, H, pal, title, desc):
        self.W, self.H, self.pal = W, H, pal
        self.title, self.desc = title, desc
        self.body = []
        self.defs = {}
        self.css = ""

    def style(self, css):
        self.css = css

    def add(self, s):
        self.body.append(s)

    def rect(self, x, y, w, h, fill):
        self.add(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{fill}"/>')

    def hline(self, x0, x1, y, w=1.0, color=None):
        self.rect(x0, y - w / 2, x1 - x0, w, color or self.pal["rule"])

    def text(self, face, txt, size, x, y, color, tracking=0.0, anchor="start", cls=None):
        glyphs, w = face.place(txt, size, x, y, tracking, anchor)
        uses = []
        for name, gx, gy, s in glyphs:
            gid, d = face.glyph(name)
            if not d:
                continue
            self.defs[gid] = d
            uses.append(f'<use href="#{gid}" transform="matrix({s:.5g} 0 0 {s:.5g} {fmt(gx)} {fmt(gy)})"/>')
        c = f' class="{cls}"' if cls else ""
        self.add(f'<g fill="{color}"{c}>' + "".join(uses) + "</g>")
        return w

    def text_circle(self, face, txt, size, cx, cy, r, color):
        """Set a string around a full circle, clockwise from the top, tracked to close the ring."""
        n = len(face.shape(txt))
        tr = (2 * math.pi * r - face.width(txt, size, 0)) / (size * n)
        glyphs, _ = face.place(txt, size, 0, 0, tr)
        uses = []
        for name, gx, gy, s in glyphs:
            gid, d = face.glyph(name)
            adv = face.tt["hmtx"][name][0] * s
            if d:
                self.defs[gid] = d
                deg = math.degrees((gx + adv / 2) / r)
                uses.append(f'<use href="#{gid}" transform="rotate({deg:.2f} {fmt(cx)} {fmt(cy)}) '
                            f'translate({fmt(cx - adv / 2)} {fmt(cy - r)}) scale({s:.5g})"/>')
        self.add(f'<g fill="{color}">' + "".join(uses) + "</g>")

    def svg(self):
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W} {self.H}" '
                f'width="{self.W}" height="{self.H}" role="img" aria-labelledby="t d">'
                f'<title id="t">{esc(self.title)}</title><desc id="d">{esc(self.desc)}</desc>'
                f'<rect width="{self.W}" height="{self.H}" fill="{self.pal["paper"]}"/>')
        if self.css:
            head += "<style>" + " ".join(self.css.split()) + "</style>"
        defs = "<defs>" + "".join(f'<path id="{k}" d="{d}"/>' for k, d in self.defs.items()) + "</defs>"
        return head + defs + "".join(self.body) + "</svg>"



# Scenes
LIGHT_DIR = (-0.45, 1.0, 0.75)
SKY = {"dark": 0.30, "light": 0.97}  # flat ground: no lines in either mode


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


VASE_AXIS_Y = (0.0, 2.9)


def sd_vase(p):
    """A surahi: round belly, long neck, flared mouth, small foot."""
    q = p.copy()
    d = sd_ellipsoid(local(q, (0, 1.08, 0)), (0.9, 0.82, 0.9))
    d = smin(d, sd_cone(local(q, (0, 0.24, 0)), 0.18, 0.34, 0.26), 0.10)
    d = smin(d, sd_cyl(local(q, (0, 0.05, 0)), 0.40, 0.05, 0.02), 0.04)
    d = smin(d, sd_cone(local(q, (0, 2.18, 0)), 0.46, 0.30, 0.12), 0.16)
    d = smin(d, sd_torus(local(q, (0, 2.62, 0)), 0.13, 0.035), 0.03)
    d = smin(d, sd_cone(local(q, (0, 2.76, 0)), 0.12, 0.13, 0.24), 0.05)
    return d


def frac(x):
    return x - np.floor(x)


def inlay_mask(p, n, v):
    """Where silver is inlaid on the surahi: a diamond lattice with a
    four-petal flower in every cell on the belly, plain bands, a chevron
    border at the shoulder and rings on the neck."""
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    th = np.arctan2(z, x)
    N = 16
    u = th / (2 * math.pi) * N
    vv = (y - 1.08) / 0.34
    a, b = frac(u + vv), frac(u - vv)
    da, db = np.minimum(a, 1 - a), np.minimum(b, 1 - b)
    belly = (y > 0.52) & (y < 1.56)
    lattice = belly & (np.minimum(da, db) < 0.045)
    ca, cb = 0.5 - da, 0.5 - db
    petal = ((ca ** 2 / 0.018 + cb ** 2 / 0.0022) < 1) | ((cb ** 2 / 0.018 + ca ** 2 / 0.0022) < 1)
    flower = belly & (petal | (ca ** 2 + cb ** 2 < 0.004))
    band = lambda y0, y1: (y > y0) & (y < y1)
    bands = band(1.60, 1.64) | band(1.74, 1.77) | band(0.44, 0.48) | band(2.02, 2.05) | band(2.36, 2.39) | band(0.08, 0.11)
    tri = np.abs(frac(u * 1.0) - 0.5) * 2
    chevron = band(1.645, 1.735) & (np.abs((y - 1.645) / 0.09 - tri) < 0.24)
    face = (n * v).sum(-1) > 0.22
    return (lattice | flower | bands | chevron) & face


def scene_vase(W, H, mode):
    cam = Cam((0.0, 1.9, 7.9), (0, 1.40, 0), 23.5, W, H)
    ld = nrm(np.asarray(LIGHT_DIR, float))
    rd = cam.rays()
    ro = np.broadcast_to(cam.pos, rd.shape).copy()
    t, hit = march(sd_vase, ro, rd)
    L = np.full(hit.shape, SKY[mode])
    Hm = np.zeros(hit.shape)
    inl = np.zeros(hit.shape, np.int8)  # 0 none, 1 inlay in light, 2 inlay in shade

    idx = np.nonzero(hit)
    p = ro[idx] + rd[idx] * t[idx][..., None]
    n = normal(sd_vase, p)
    v = -rd[idx]
    dif = np.clip((n * ld).sum(-1), 0, 1)
    sh = soft_shadow(sd_vase, p + n * 2e-3, ld)
    refl = 2 * (n * ld).sum(-1, keepdims=True) * n - ld
    spec = np.clip((refl * v).sum(-1), 0, 1)
    rim = np.clip(1 - (n * v).sum(-1), 0, 1) ** 3
    # blackened metal: almost no diffuse, a broad soft sheen and a rim catch
    lum = 0.06 + 0.16 * dif * sh + 0.55 * spec ** 10 * sh + 0.18 * rim
    L[idx] = np.clip(lum, 0, 0.9) if mode == "dark" else np.clip(0.05 + 0.6 * spec ** 10 * sh + 0.1 * rim, 0, 0.9)
    Hm[idx] = np.clip((n * v).sum(-1), 0, 1)
    m = inlay_mask(p, n, v)
    lit = (dif * sh) > 0.32
    inl[tuple(i[m & lit] for i in idx)] = 1
    inl[tuple(i[m & ~lit] for i in idx)] = 2

    # floor: only the cast shadow and a soft pool of light, fading out
    miss = ~hit & (rd[..., 1] < -1e-4)
    fidx = np.nonzero(miss)
    tg = -ro[fidx][..., 1] / rd[fidx][..., 1]
    pg = ro[fidx] + rd[fidx] * tg[..., None]
    shg = soft_shadow(sd_vase, pg + np.array([0, 2e-3, 0]), ld, k=6.0)
    fade = np.clip(1.5 - np.hypot(pg[:, 0] + 0.3, pg[:, 2]) / 1.9, 0, 1)
    if mode == "dark":
        L[fidx] = SKY[mode] + fade * (0.20 * shg + 0.02)
    else:
        L[fidx] = SKY[mode] - fade * 0.55 * (1 - shg)
    return L, Hm, hit, inl


def scene_emblem(kind, S, mode):
    scene, glow = EMBLEMS[kind]
    cam = Cam((0.0, 2.3, 6.6), (0, 0.98, 0), 21.5, S, S)
    sky = np.full((S, S), SKY[mode])
    if glow is not None and mode == "dark":
        yy, xx = np.mgrid[0:S, 0:S].astype(float)
        fx, fy = cam.project(FLAME[0])
        sky = np.clip(sky + 0.45 * np.exp(-((xx - fx) ** 2 + (yy - fy) ** 2) / (0.16 * S) ** 2), 0, 1)
    tone = 0.62 if mode == "dark" else 0.80
    L, Hm, mask = render(scene, cam, LIGHT_DIR, sky, floor_tone=tone,
                         floor_fade=lambda pg: np.clip(1.5 - np.hypot(pg[:, 0], pg[:, 2]) / 2.2, 0, 1),
                         glow=glow)
    if mode == "dark":
        # the floor lights up silver where lit, stays black in shadow
        miss = ~mask
        L[miss] = np.where(L[miss] > SKY[mode] + 0.02, L[miss], SKY[mode])
    return L, Hm, mask


def mask_paths(m):
    """Filled outlines of a boolean mask, as SVG path data (even-odd)."""
    f = m.astype(float)
    k = np.array([1, 2, 1], float) / 4
    f = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, f)
    f = np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, f)
    f = np.pad(f, 1)
    parts = []
    for c in find_contours(f, 0.5):
        if len(c) < 5:
            continue
        xy = c[:, ::-1] - 1
        h = len(xy) // 2  # closed curve: simplify each half so the endpoints differ
        xy = np.vstack([rdp(xy[:h + 1], 0.25), rdp(xy[h:], 0.25)[1:]])
        parts.append("M" + " ".join(fmt(x) + " " + fmt(y) for x, y in xy) + "Z")
    return "".join(parts)


# Images
def seal(pl, F, cx, cy, R=96):
    """A turning ring of text with the number of wins at its heart."""
    pal = pl.pal
    ink, acc, paper = pal["ink"], pal["accent"], pal["paper"]
    pl.add(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{R}" fill="{paper}"/>')
    pl.add(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{R - 5}" fill="none" stroke="{ink}" stroke-width="2.4"/>')
    pl.add(f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{R - 36}" fill="none" stroke="{ink}" stroke-width="1.2"/>')
    pl.add(f'<g class="spin" style="transform-origin:{fmt(cx)}px {fmt(cy)}px">')
    pl.text_circle(F["headm"], MAST["seal_ring"], 17, cx, cy, R - 30, ink)
    pl.add("</g>")
    pl.text(F["head"], MAST["seal_center"], 68, cx, cy + 24, acc, 0.04, "middle")


def build_masthead(F, mode, pal, cache):
    W, H = 1600, 1030
    pl = Plate(W, H, pal, "Victor Isaac",
               "Victor Isaac. Engineer, product builder and founder in Hyderabad. Founder of Rotciv Inc., "
               "Founder's Office at Interseqt, three national hackathon wins, from ACE Engineering College. "
               "An engraved surahi vase with silver inlay in the style of Bidri, and a seal reading "
               "Sapere aude.")
    pl.style(MOTION_CSS)
    ink, mut, acc = pal["ink"], pal["muted"], pal["accent"]
    M = 84

    # the surahi, right side, full height
    px, py, pw, ph = 880, 24, 680, 800
    key = "vase-" + mode
    if key not in cache:
        cache[key] = scene_vase(pw, ph, mode)
    L, Hm, mask, inl = cache[key]
    clip = lambda x, y: np.ones_like(x, bool)
    d = engraving(L, Hm, mask, mode, clip, spacing=5.2, maxw=4.8, disp=8, hatch_angle=32)
    body = mask_paths(mask)
    sheen_defs(pl, pal["inlay"])
    pl.add(f'<g transform="translate({px} {py})">')
    pl.add(f'<path fill="{ink}" d="{d}"/>')
    pl.add(silhouette(mask, ink, 1.4))
    pl.add(f'<path fill="{pal["inlay_shade"]}" d="{mask_paths(inl == 2)}"/>')
    pl.add(f'<path fill="{pal["inlay"]}" d="{mask_paths(inl == 1)}"/>')
    sheen(pl, "cm", f'<path d="{body}"/>', pw, "sweepM")
    pl.add("</g>")
    pl.text(F["texti"], MAST["caption"], 21, W - M, py + ph + 14, mut, 0, "end")
    seal(pl, F, W - M - 96, 150)

    # left column: name, role, cycling line, facts
    colw = px - M - 60
    inline = F["inline"]
    size = min(inline.fit(MAST["first"], 330, colw, 0.01), inline.fit(MAST["last"], 330, colw, 0.01))
    top = 92
    pl.text(inline, MAST["first"], size, M - size * 0.03, top + size * 0.80, ink, 0.01)
    base2 = top + size * 0.80 + size * 0.86
    pl.text(inline, MAST["last"], size, M - size * 0.03, base2, ink, 0.01)

    ry = base2 + 78
    pl.text(F["textm"], MAST["role"], F["textm"].fit(MAST["role"], 40, colw), M, ry, ink)
    dsz = min(F["text"].fit(t, 38, colw) for t in MAST["decks"])
    for i, t in enumerate(MAST["decks"], 1):
        pl.text(F["text"], t, dsz, M, ry + 54, pal["deck"], cls=f"ph ph{i}")

    # facts run the full width along the bottom, one line each
    fy = 918
    n = len(MAST["facts"])
    gap = 40
    cw = (W - 2 * M - gap * (n - 1)) / n
    vs = min(F["headm"].fit(val, 40, cw) for _, val in MAST["facts"])
    for i, (lab, val) in enumerate(MAST["facts"]):
        x = M + i * (cw + gap)
        pl.text(F["textm"], lab, 21, x, fy, acc)
        pl.text(F["headm"], val, vs, x, fy + 46, ink)
    return pl.svg()


def inlay_ring(pl, cx, cy, r, color, count=44, size=5.5):
    """A rim of small inlaid diamonds, like the border of a Bidri plate."""
    parts = []
    for k in range(count):
        a = 2 * math.pi * k / count
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        ux, uy = math.cos(a), math.sin(a)
        tx, ty = -uy, ux
        pts = [(x + ux * size * 1.5, y + uy * size * 1.5), (x + tx * size * 0.75, y + ty * size * 0.75),
               (x - ux * size * 1.5, y - uy * size * 1.5), (x - tx * size * 0.75, y - ty * size * 0.75)]
        parts.append("M" + "L".join(fmt(px) + " " + fmt(py) for px, py in pts) + "Z")
    pl.add(f'<path fill="{color}" d="{"".join(parts)}"/>')


def build_credo(F, mode, pal, cache):
    W, H = 1600, 690
    desc = CREDO_TITLE + ". " + " ".join(f"{c['title']} {c['body']}" for c in CREDO)
    pl = Plate(W, H, pal, CREDO_TITLE, desc)
    pl.style(MOTION_CSS)
    sheen_defs(pl, pal["inlay"])
    ink, mut = pal["ink"], pal["muted"]
    M = 84
    pl.text(F["head"], CREDO_TITLE.upper(), 76, M, 132, ink, 0.01)
    n = len(CREDO)
    gap = 56
    cw = (W - 2 * M - gap * (n - 1)) / n
    R = 112
    for i, c in enumerate(CREDO):
        x0 = M + i * (cw + gap)
        mcx, mcy = x0 + R + 22, 190 + R + 22
        S = 2 * R
        key = f"emb-{c['emblem']}-{mode}"
        if key not in cache:
            cache[key] = scene_emblem(c["emblem"], S, mode)
        L, Hm, mask = cache[key]
        clip = lambda x, y: np.hypot(x - S / 2, y - S / 2) < R - 4
        d = engraving(L, Hm, mask, mode, clip, spacing=4.0, maxw=3.6, disp=6)
        pl.add(f'<g transform="translate({fmt(mcx - R)} {mcy - R})">'
               f'<path fill="{ink}" d="{d}"/>' + silhouette(mask, ink, 1.2))
        sheen(pl, f"c{i}", f'<circle cx="{R}" cy="{R}" r="{R}"/>', S, f"sweepC d{i + 1}")
        pl.add("</g>")
        pl.add(f'<circle cx="{fmt(mcx)}" cy="{mcy}" r="{R + 3}" fill="none" stroke="{ink}" stroke-width="2.2"/>')
        inlay_ring(pl, mcx, mcy, R + 16, pal["inlay"] if mode == "dark" else ink)
        ty = mcy + R + 84
        ts = F["head"].fit(c["title"].upper(), 46, cw)
        pl.text(F["head"], c["title"].upper(), ts, x0, ty, ink, 0.01)
        lines = F["text"].wrap(c["body"], 23, cw)
        assert len(lines) <= 2, f"credo body runs past two lines: {c['title']}"
        for j, line in enumerate(lines):
            pl.text(F["text"], line, 23, x0, ty + 42 + j * 31, mut)
    return pl.svg()


def main():
    paths = ensure_fonts()
    F = {k: Face(os.path.basename(p), k[0] + str(i)) for i, (k, p) in enumerate(paths.items())}
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith(".svg"):
            os.remove(os.path.join(OUT, old))
    cache = {}
    for mode, pal in PALETTES.items():
        files = {"masthead": build_masthead(F, mode, pal, cache),
                 "credo": build_credo(F, mode, pal, cache)}
        for name, svg in files.items():
            p = os.path.join(OUT, f"{name}-{mode}.svg")
            with open(p, "w") as fh:
                fh.write(svg)
            print(f"{os.path.relpath(p, ROOT):40s} {len(svg) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
