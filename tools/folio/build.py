#!/usr/bin/env python3
"""
Folio plate generator for github.com/victorisaacchinta-eng

Every illustration is raymarched from signed distance fields, then
line-engraved into vector SVG. All type is outlined into paths, so the
plates render identically everywhere GitHub shows them.

Edit the CONTENT section, then run:
    pip install numpy fonttools uharfbuzz scikit-image
    python3 tools/folio/build.py
Output goes to assets/folio/ (a light and a dark version of each plate).
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



# ════════════════════════════════════════════════════════════════════
# CONTENT  (edit freely; keep every claim defensible)
# This README is about who you are, not a list of repos, so nothing here
# needs to change when you ship a new project. Pinned repos do that job.
# ════════════════════════════════════════════════════════════════════
MAST = {
    "top_left": "THE FOLIO OF VICTOR ISAAC",
    "top_center": "HYDERABAD, INDIA",
    "top_right": "VOL. II · MMXXVI",
    "kicker": "ENGINEER · PRODUCT BUILDER · FOUNDER",
    "first": "Victor",
    "last": "Isaac",
    # cycles in the masthead, one line at a time
    "decks": [
        "I collect whys before I collect tools.",
        "I build agents that show their work.",
        "I design for the hand, not the screen.",
        "I ship the version that tells the truth.",
    ],
    "facts": [
        ("STUDYING", "B.Tech undergraduate"),
        ("FOUNDER", "Rotciv Inc."),
        ("PRODUCT", "Founder's Office, Interseqt"),
        ("FOCUS", "Agentic AI, security, product"),
    ],
    "seal_ring": "THREE-TIME NATIONAL HACKATHON WINNER · SAPERE AUDE · ",
    "seal_center": "III",
    "seal_under": "WINS",
    "foot_left": "FROM FIRST PRINCIPLES",
    "foot_right": "GITHUB.COM/VICTORISAACCHINTA-ENG",
    "inscription": "SAPERE AUDE",
    "caption": "Pl. I · Sphaera super basim. After the light.",
}

CREDO = [
    dict(emblem="scales", fig="Libra", title="Show the work.",
         body="Agents that cite their sources and stop before they guess."),
    dict(emblem="lens", fig="Lens", title="Look closer.",
         body="The real problem hides under the obvious one. Find it first."),
    dict(emblem="key", fig="Clavis", title="Guard the keys.",
         body="Security is a design decision, not a patch. Guardrails first."),
    dict(emblem="candle", fig="Lux", title="Carry the light.",
         body="Build things worth inheriting. For people, not the demo."),
]

INSTRUMENTS = [
    "Python · TypeScript · JavaScript · Java · SQL",
    "FastAPI · Next.js · React · Tailwind · Git · Linux",
]
STUDY = "In study: DSA, system design, Docker, AWS, DevSecOps."
CONTACT = [
    "victorisaacchinta@gmail.com",
    "in/victor-isaac-chintha",
    "x.com/rotcivcassi",
]
COLOPHON = ("Colophon. Set in Instrument Serif and IBM Plex Mono. Engravings raymarched from "
            "signed distance fields and cut into lines in Python.")

PALETTES = {
    "light": dict(paper="#EEE8DA", ink="#17140F", rubric="#A8361F", muted="#6B6356", rule="#17140F"),
    "dark": dict(paper="#100F0D", ink="#E8E1D1", rubric="#DE5B40", muted="#8E8676", rule="#E8E1D1"),
}

# Motion: a sheen of light passes over each engraving on load, the seal turns,
# and the masthead line cycles. The first frame is always complete, so a frozen
# render (background tab, link preview, reduced motion) still shows everything.
MOTION_CSS = """
@keyframes sweepM{from{transform:translateY(0)}to{transform:translateY(900px)}}
@keyframes sweepC{from{transform:translateY(0)}to{transform:translateY(460px)}}
.sweepM{animation:sweepM 2.8s cubic-bezier(.4,0,.2,1) .2s both}
.sweepC{animation:sweepC 2.2s cubic-bezier(.4,0,.2,1) both}
.d1{animation-delay:.2s}.d2{animation-delay:.5s}.d3{animation-delay:.8s}.d4{animation-delay:1.1s}
@keyframes spin{to{transform:rotate(360deg)}}
.spin{transform-box:view-box;animation:spin 60s linear infinite}
@keyframes cyc{0%{opacity:0;transform:translateY(14px)}5%{opacity:1;transform:none}22%{opacity:1;transform:none}27%{opacity:0;transform:translateY(-10px)}100%{opacity:0}}
.ph{opacity:0;animation:cyc 18s infinite}.ph1{opacity:1}
.ph1{animation-delay:-.9s}.ph2{animation-delay:3.6s}.ph3{animation-delay:8.1s}.ph4{animation-delay:12.6s}
@media (prefers-reduced-motion:reduce){.sweepM,.sweepC,.spin,.ph{animation:none}.ph{opacity:0}.ph1{opacity:1}}
"""


def sheen_defs(pl):
    p = pl.pal["paper"]
    pl.add(f'<defs><linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1">'
           f'<stop offset="0" stop-color="{p}" stop-opacity="0"/>'
           f'<stop offset=".5" stop-color="{p}" stop-opacity=".8"/>'
           f'<stop offset="1" stop-color="{p}" stop-opacity="0"/></linearGradient></defs>')


def sheen(pl, cid, shape, w, cls):
    """A band of paper-coloured light that starts above the shape and passes down through it once."""
    pl.add(f'<clipPath id="{cid}">{shape}</clipPath><g clip-path="url(#{cid})">'
           f'<rect class="{cls}" x="-10" y="-200" width="{w + 20}" height="150" fill="url(#sheen)"/></g>')


# ════════════════════════════════════════════════════════════════════
# TYPE
# ════════════════════════════════════════════════════════════════════
FONT_URLS = {
    "InstrumentSerif-Regular.ttf": "ofl/instrumentserif/InstrumentSerif-Regular.ttf",
    "InstrumentSerif-Italic.ttf": "ofl/instrumentserif/InstrumentSerif-Italic.ttf",
    "IBMPlexMono-Regular.ttf": "ofl/ibmplexmono/IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf": "ofl/ibmplexmono/IBMPlexMono-Medium.ttf",
}


def ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    for name, rel in FONT_URLS.items():
        p = os.path.join(FONT_DIR, name)
        if not os.path.exists(p):
            urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/" + rel, p)


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


# ════════════════════════════════════════════════════════════════════
# SDF RAYMARCHER
# ════════════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════════════
# LINE ENGRAVER
# ════════════════════════════════════════════════════════════════════
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


# ════════════════════════════════════════════════════════════════════
# SCENES
# ════════════════════════════════════════════════════════════════════
LIGHT_DIR = (-0.4, 1.0, 0.7)


def scene_masthead(W, H):
    plinth_c, plinth_b = (0, 0.58, 0), (0.98, 0.58, 0.78)
    sph_c, sph_r = (0, 1.16 + 0.84, 0), 0.84

    def scene(p):
        return np.minimum(sd_box(local(p, plinth_c), plinth_b, 0.015), sd_sphere(local(p, sph_c), sph_r))

    cam = Cam((0.0, 2.9, 8.1), (0, 1.22, 0), 30, W, H)
    # light rays radiating from beyond the upper-left corner
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    sx, sy = -0.18 * W, -0.16 * H
    phi = np.arctan2(yy - sy, xx - sx)
    dist = np.hypot(xx - sx, yy - sy) / math.hypot(W, H)
    rays = (0.5 + 0.5 * np.cos(phi * 30)) ** 2
    fall = np.clip(1.3 - dist, 0, 1)
    sky = np.clip(0.50 + 0.10 * rays * fall + 0.22 * fall, 0, 1)
    L, Hm, mask = render(scene, cam, LIGHT_DIR, sky, floor_tone=0.74)
    # inscription anchor: centre and width of the plinth front face, in plate pixels
    z = plinth_b[2] + plinth_c[2]
    left = cam.project((-plinth_b[0], plinth_c[1], z))
    right = cam.project((plinth_b[0], plinth_c[1], z))
    top = cam.project((0, plinth_c[1] + plinth_b[1], z))
    bot = cam.project((0, plinth_c[1] - plinth_b[1], z))
    face = dict(cx=(left[0] + right[0]) / 2, cy=(top[1] + bot[1]) / 2, w=right[0] - left[0], h=bot[1] - top[1])
    return L, Hm, mask, face


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


def scene_emblem(kind, S):
    scene, glow = EMBLEMS[kind]
    cam = Cam((0.0, 2.3, 6.6), (0, 0.98, 0), 21.5, S, S)
    yy, xx = np.mgrid[0:S, 0:S].astype(float)
    r = np.hypot(xx - S / 2, yy - S / 2) / (S / 2)
    sky = 0.84 - 0.12 * r ** 2.2
    if glow is not None:
        fx, fy = cam.project(FLAME[0])
        sky = np.clip(sky + 0.22 * np.exp(-((xx - fx) ** 2 + (yy - fy) ** 2) / (0.18 * S) ** 2), 0, 1)
    L, Hm, mask = render(scene, cam, LIGHT_DIR, sky, floor_tone=0.70,
                         floor_fade=lambda pg: np.clip(1.6 - np.hypot(pg[:, 0], pg[:, 2]) / 2.6, 0, 1),
                         glow=glow)
    return L, Hm, mask


# ════════════════════════════════════════════════════════════════════
# SVG PLATES
# ════════════════════════════════════════════════════════════════════
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


def frame(pl, inset=1.0, w=2.0):
    c = pl.pal["rule"]
    pl.add(f'<rect x="{inset}" y="{inset}" width="{pl.W - 2 * inset}" height="{pl.H - 2 * inset}" '
           f'fill="none" stroke="{c}" stroke-width="{w}"/>')


def seal(pl, F, cx, cy, mode):
    """A turning seal: ring text on a circle, a numeral at its heart."""
    pal = pl.pal
    ink, rub, mut = pal["ink"], pal["rubric"], pal["muted"]
    pl.add(f'<circle cx="{cx}" cy="{cy}" r="92" fill="{pal["paper"]}"/>')
    pl.add(f'<circle cx="{cx}" cy="{cy}" r="88" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    pl.add(f'<circle cx="{cx}" cy="{cy}" r="83" fill="none" stroke="{ink}" stroke-width="0.6"/>')
    pl.add(f'<circle cx="{cx}" cy="{cy}" r="60" fill="none" stroke="{ink}" stroke-width="0.9"/>')
    pl.add(f'<g class="spin" style="transform-origin:{cx}px {cy}px">')
    pl.text_circle(F["monom"], MAST["seal_ring"], 14.5, cx, cy, 67, ink)
    pl.add("</g>")
    pl.text(F["serif"], MAST["seal_center"], 66, cx, cy + 16, rub, 0.04, "middle")
    pl.text(F["monom"], MAST["seal_under"], 11, cx, cy + 40, mut, 0.3, "middle")


def build_masthead(F, mode, pal, cache):
    W, H = 1600, 920
    pl = Plate(W, H, pal, "Victor Isaac, personal folio",
               "Victor Isaac. Engineer, product builder and founder in Hyderabad. B.Tech undergraduate, "
               "founder of Rotciv Inc., Founder's Office at Interseqt, three-time national hackathon winner. "
               "I collect whys before I collect tools. An engraved sphere rests on a plinth inscribed Sapere Aude.")
    pl.style(MOTION_CSS)
    ink, rub, mut = pal["ink"], pal["rubric"], pal["muted"]
    M = 72
    serif, ital, monom = F["serif"], F["ital"], F["monom"]

    pl.text(monom, MAST["top_left"], 19, M, 52, ink, 0.16)
    pl.text(monom, MAST["top_center"], 19, W / 2, 52, mut, 0.16, "middle")
    pl.text(monom, MAST["top_right"], 19, W - M, 52, ink, 0.16, "end")
    pl.hline(M, W - M, 74, 3.2)
    pl.hline(M, W - M, 82, 1.0)

    # engraved plate, pulled from the press on load
    px, py, pw, ph = 930, 124, 598, 660
    if "mast" not in cache:
        cache["mast"] = scene_masthead(pw, ph)
    L, Hm, mask, face = cache["mast"]
    clip = lambda x, y: np.ones_like(x, bool)
    d = engraving(L, Hm, mask, mode, clip, spacing=6.0, maxw=5.4, disp=9)
    sheen_defs(pl)
    pl.add(f'<g transform="translate({px} {py})"><path fill="{ink}" d="{d}"/>')
    pl.add(silhouette(mask, ink, 1.3))
    insz = serif.fit(MAST["inscription"], 44, face["w"] * 0.62, 0.22)
    tw = serif.width(MAST["inscription"], insz, 0.22)
    pl.add(f'<rect x="{fmt(face["cx"] - tw / 2 - 22)}" y="{fmt(face["cy"] - insz * 0.62)}" '
           f'width="{fmt(tw + 44)}" height="{fmt(insz * 1.24)}" fill="{pal["paper"]}"/>')
    pl.add(f'<rect x="{fmt(face["cx"] - tw / 2 - 16)}" y="{fmt(face["cy"] - insz * 0.62 + 6)}" '
           f'width="{fmt(tw + 32)}" height="{fmt(insz * 1.24 - 12)}" fill="none" stroke="{ink}" stroke-width="1"/>')
    pl.text(serif, MAST["inscription"], insz, face["cx"], face["cy"] + insz * 0.34, ink, 0.22, "middle")
    sheen(pl, "cm", f'<rect width="{pw}" height="{ph}"/>', pw, "sweepM")
    pl.add("</g>")
    pl.add(f'<rect x="{px - 10}" y="{py - 10}" width="{pw + 20}" height="{ph + 20}" fill="none" stroke="{ink}" stroke-width="1.6"/>')
    pl.add(f'<rect x="{px - 4}" y="{py - 4}" width="{pw + 8}" height="{ph + 8}" fill="none" stroke="{ink}" stroke-width="0.8"/>')
    pl.text(ital, MAST["caption"], 23, px + pw / 2 - 60, py + ph + 46, mut, 0, "middle")
    seal(pl, F, px + pw - 52, py + ph - 40, mode)

    # left column
    colw = px - 10 - M - 56
    pl.text(monom, MAST["kicker"], 20, M, 162, rub, 0.18)
    size = min(serif.fit(MAST["first"], 236, colw), ital.fit(MAST["last"] + ".", 236, colw))
    pl.text(serif, MAST["first"], size, M - size * 0.02, 162 + size * 0.86, ink)
    base = 162 + size * 1.64
    w_last = pl.text(ital, MAST["last"], size, M, base, ink)
    pl.text(ital, ".", size, M + w_last, base, rub)

    deck_y = base + 86
    dsz = min(ital.fit(t, 44, colw) for t in MAST["decks"])
    for i, t in enumerate(MAST["decks"], 1):
        pl.text(ital, t, dsz, M, deck_y, ink, cls=f"ph ph{i}")

    fy = deck_y + 56
    pl.hline(M, M + colw, fy, 1.0)
    n = len(MAST["facts"])
    gap = 24
    cw = (colw - gap * (n - 1)) / n
    for i, (lab, val) in enumerate(MAST["facts"]):
        x = M + i * (cw + gap)
        if i:
            pl.rect(x - gap / 2, fy + 18, 0.8, 92, mut)
        pl.text(monom, lab, 16, x, fy + 40, rub, 0.16)
        for j, line in enumerate(serif.wrap(val, 29, cw)[:2]):
            pl.text(serif, line, 29, x, fy + 78 + j * 31, ink)

    pl.hline(M, W - M, H - 62, 1.0)
    pl.text(monom, MAST["foot_left"], 17, M, H - 28, ink, 0.18)
    pl.text(monom, MAST["foot_right"], 17, W - M, H - 28, mut, 0.18, "end")
    return pl.svg()


NUM_WORDS = {3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX"}


def build_credo(F, mode, pal, cache):
    W, H = 1600, 700
    desc = "Credo. " + " ".join(f"{c['title']} {c['body']}" for c in CREDO)
    pl = Plate(W, H, pal, "Credo", desc)
    pl.style(MOTION_CSS)
    sheen_defs(pl)
    ink, rub, mut = pal["ink"], pal["rubric"], pal["muted"]
    serif, ital, mono, monom = F["serif"], F["ital"], F["mono"], F["monom"]
    M = 72
    frame(pl, 1.0, 2.0)
    pl.text(ital, "Credo.", 92, M, 124, ink)
    pl.text(monom, "§ I", 20, W - M, 78, rub, 0.18, "end")
    pl.text(mono, f"{NUM_WORDS[len(CREDO)]} THINGS I BUILD BY", 18, W - M, 112, mut, 0.16, "end")
    pl.hline(M, W - M, 154, 0.9)
    n = len(CREDO)
    gap = 44
    cw = (W - 2 * M - gap * (n - 1)) / n
    R = 120
    numerals = ["I", "II", "III", "IV", "V", "VI"]
    for i, c in enumerate(CREDO):
        x0 = M + i * (cw + gap)
        if i:
            pl.rect(x0 - gap / 2, 178, 0.8, H - 210, mut)
        mcx, mcy = x0 + cw / 2, 168 + 26 + R
        S = 2 * R
        key = "emb-" + c["emblem"]
        if key not in cache:
            cache[key] = scene_emblem(c["emblem"], S)
        L, Hm, mask = cache[key]
        clip = lambda x, y: np.hypot(x - S / 2, y - S / 2) < R - 5
        d = engraving(L, Hm, mask, mode, clip, spacing=4.2, maxw=3.8, disp=6)
        pl.add(f'<g transform="translate({fmt(mcx - R)} {mcy - R})">'
               f'<path fill="{ink}" d="{d}"/>' + silhouette(mask, ink, 1.3))
        sheen(pl, f"c{i}", f'<circle cx="{R}" cy="{R}" r="{R}"/>', S, f"sweepC d{i + 1}")
        pl.add("</g>")
        pl.add(f'<circle cx="{fmt(mcx)}" cy="{mcy}" r="{R}" fill="none" stroke="{ink}" stroke-width="1.5"/>')
        pl.add(f'<circle cx="{fmt(mcx)}" cy="{mcy}" r="{R + 6}" fill="none" stroke="{ink}" stroke-width="0.6"/>')
        cap_y = mcy + R + 42
        pl.text(ital, f"Fig. {numerals[i]} · {c['fig']}", 22, mcx, cap_y, mut, 0, "middle")
        pl.hline(x0, x0 + cw, cap_y + 24, 0.9)
        ts = serif.fit(c["title"], 50, cw)
        pl.text(monom, numerals[i], 16, x0, cap_y + 64, rub, 0.16)
        pl.text(serif, c["title"], ts, x0, cap_y + 112, ink)
        lines = ital.wrap(c["body"], 26, cw)
        assert len(lines) <= 2, f"credo body runs past two lines: {c['title']}"
        for j, line in enumerate(lines):
            pl.text(ital, line, 26, x0, cap_y + 152 + j * 32, ink)
    return pl.svg()


def build_strip(F, pal):
    W, H = 1600, 330
    desc = ("Instruments: " + "; ".join(INSTRUMENTS) + ". " + STUDY +
            " Correspondence: " + ", ".join(CONTACT) + ".")
    pl = Plate(W, H, pal, "Instruments and correspondence", desc)
    ink, rub, mut = pal["ink"], pal["rubric"], pal["muted"]
    serif, ital, mono, monom = F["serif"], F["ital"], F["mono"], F["monom"]
    M = 72
    frame(pl, 1.0, 2.0)
    split = 900
    pl.text(monom, "§ II  INSTRUMENTS", 17, M, 66, rub, 0.16)
    for j, line in enumerate(INSTRUMENTS):
        sz = serif.fit(line, 38, split - M - 60)
        pl.text(serif, line, sz, M, 122 + j * 46, ink)
    pl.text(ital, STUDY, 25, M, 218, mut)
    pl.rect(split, 40, 0.8, 200, mut)
    x2 = split + 48
    pl.text(monom, "§ III  CORRESPONDENCE", 17, x2, 66, rub, 0.16)
    for j, line in enumerate(CONTACT):
        sz = mono.fit(line, 25, W - M - x2)
        pl.text(mono, line, sz, x2, 118 + j * 44, ink)
    pl.hline(M, W - M, 258, 0.9)
    right = "FROM FIRST PRINCIPLES"
    rw = monom.width(right, 15, 0.18)
    csz = ital.fit(COLOPHON, 21, W - 2 * M - rw - 40)
    pl.text(ital, COLOPHON, csz, M, 298, mut)
    pl.text(monom, right, 15, W - M, 297, ink, 0.18, "end")
    return pl.svg()


def main():
    ensure_fonts()
    F = dict(serif=Face("InstrumentSerif-Regular.ttf", "s"), ital=Face("InstrumentSerif-Italic.ttf", "i"),
             mono=Face("IBMPlexMono-Regular.ttf", "m"), monom=Face("IBMPlexMono-Medium.ttf", "n"))
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith(".svg"):
            os.remove(os.path.join(OUT, old))
    cache = {}
    for mode, pal in PALETTES.items():
        files = {"masthead": build_masthead(F, mode, pal, cache),
                 "credo": build_credo(F, mode, pal, cache),
                 "strip": build_strip(F, pal)}
        for name, svg in files.items():
            p = os.path.join(OUT, f"{name}-{mode}.svg")
            with open(p, "w") as fh:
                fh.write(svg)
            print(f"{os.path.relpath(p, ROOT):40s} {len(svg) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
