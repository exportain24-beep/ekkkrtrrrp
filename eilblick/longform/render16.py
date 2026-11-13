"""16:9 documentary renderer – 1920×1080, 25 fps, PIL frames piped into ffmpeg.

Screen:
  ┌────────────────────────────────────────────────────────────┐
  │ ▌EILBLICK FOKUS                     KAPITEL 3 · DER STATUS │  persistent branding + chapter
  │                                                            │
  │        photo (Ken Burns / framed / split) or graphic       │  visual change every 4–6 s
  │ ▌LOWER THIRD                                               │
  │ Headline                                     Bild: credit  │
  │ ▬▬▬▬▬▬ ▬▬▬▬▬▬ ▬▬▬░░░ ░░░░░░ ░░░░░░ ░░░░░░                  │  chapter progress bar (6 acts)
  └────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from ..render import C, cover, ease, font

W, H = 1920, 1080
FPS = 25
FADE = 0.45
RED, WHITE, GREY, BG, PANEL = C["red"], C["white"], C["grey"], C["bg"], C["panel"]


# ------------------------------------------------------------------ data
@dataclass
class Piece:
    start: float
    dur: float
    vis: dict
    idx: int                      # running piece number (layout / motion variety)
    act: int                      # -1 cold open / title, 0..5 acts, 6 end


@dataclass
class Doc:
    total: float
    pieces: list[Piece]
    acts: list[tuple[float, float, str]]          # (start, end, title) for the 6 acts
    photos: dict                                  # id -> (PIL.Image, credit)
    title_card: dict
    words: list = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def de_num(x: float, decimals: int = 0) -> str:
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def wrap(text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if fnt.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(text: str, kind: str, max_w: int, max_lines: int, start: int, minimum: int):
    size = start
    while size > minimum:
        f = font(kind, size)
        ls = wrap(text, f, max_w)
        if len(ls) <= max_lines:
            return f, ls
        size -= 4
    f = font(kind, minimum)
    return f, wrap(text, f, max_w)[:max_lines]


def hl_line(d: ImageDraw.ImageDraw, xy, line: str, fnt, highlight, fill=WHITE, alpha=255):
    x, y = xy
    hs = {h.lower().strip(".,:;!?") for h in highlight or []}
    for w in line.split(" "):
        col = RED if w.lower().strip(".,:;!?„“\"") in hs else fill
        d.text((x, y), w, font=fnt, fill=col[:3] + (alpha,))
        x += fnt.getlength(w + " ")


def stagger(t: float, i: int, step: float = 0.12, dur: float = 0.5) -> float:
    return ease(max(0.0, min(1.0, (t - i * step) / dur)))


@lru_cache(maxsize=1)
def backdrop() -> Image.Image:
    im = Image.new("RGB", (W, H), BG[:3])
    d = ImageDraw.Draw(im, "RGBA")
    for x in range(0, W, 80):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 9))
    for y in range(0, H, 80):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 9))
    # vignette
    v = Image.new("L", (W, H), 0)
    dv = ImageDraw.Draw(v)
    for i in range(24):
        dv.rectangle([i * 18, i * 10, W - i * 18, H - i * 10], fill=int(i * 4.5))
    v = v.filter(ImageFilter.GaussianBlur(60))
    dark = Image.new("RGB", (W, H), (6, 6, 8))
    return Image.composite(im, dark, v)


_BLUR: dict = {}
_GRAD: dict = {}


def blurred(pid: str, img: Image.Image) -> Image.Image:
    if pid not in _BLUR:
        b = cover(img, W // 4, H // 4).filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BILINEAR)
        _BLUR[pid] = Image.blend(b, Image.new("RGB", (W, H), (10, 10, 12)), 0.55)
    return _BLUR[pid]


def gradient(kind: str) -> Image.Image:
    if kind not in _GRAD:
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        px = ImageDraw.Draw(g)
        if kind == "bottom":
            for y in range(H // 2, H):
                a = int(225 * ((y - H / 2) / (H / 2)) ** 1.4)
                px.line([(0, y), (W, y)], fill=(8, 8, 10, a))
            for y in range(0, 150):
                px.line([(0, y), (W, y)], fill=(8, 8, 10, int(150 * (1 - y / 150))))
        _GRAD[kind] = g
    return _GRAD[kind]


def kenburns(img: Image.Image, t: float, dur: float, idx: int, w=W, h=H) -> Image.Image:
    p = t / max(dur, 0.1)
    z0, z1 = (1.04, 1.16) if idx % 2 == 0 else (1.16, 1.04)
    z = z0 + (z1 - z0) * p
    dirs = [(0.35, 0.65), (0.65, 0.35), (0.5, 0.5), (0.4, 0.55)]
    fx0, fx1 = dirs[idx % 4]
    fx = fx0 + (fx1 - fx0) * p
    return cover(img, w, h, zoom=z, fx=fx, fy=0.4)


# ------------------------------------------------------------------ visual pieces
def draw_photo(p: Piece, t: float, doc: Doc) -> tuple[Image.Image, str]:
    v = p.vis
    ids = v["photos"]
    pid = ids[v.get("_k", 0) % len(ids)]
    img, credit = doc.photos[pid]
    layout = v.get("layout") or ["full", "framed", "slide", "split" if len(ids) > 1 else "full", "full", "slide"][p.idx % 6]
    if layout == "framed":
        fr = blurred(pid, img).copy()
        card = kenburns(img, t, p.dur, p.idx, 1240, 698)
        x, y = 90, 150
        d = ImageDraw.Draw(fr, "RGBA")
        d.rectangle([x + 14, y + 14, x + 1254, y + 712], fill=(0, 0, 0, 120))
        fr.paste(card, (x, y))
        d.rectangle([x, y, x + 9, y + 698], fill=RED)
        if v.get("headline"):
            f, ls = fit(v["headline"], "xbold", 470, 6, 58, 34)
            yy = y + 20
            for i, l in enumerate(ls):
                a = stagger(t, i)
                hl_line(d, (1385 + int(30 * (1 - a)), yy), l, f, v.get("highlight"), alpha=int(255 * a))
                yy += int(f.size * 1.15)
        return fr, credit
    if layout == "slide":
        # photo card glides in from the right over the blurred photo, slight parallax drift
        fr = blurred(pid, img).copy()
        a = ease(min(1, t / 0.7))
        cw, chh = 1100, 620
        card = kenburns(img, t, p.dur, p.idx + 1, cw, chh)
        x = int(W - 70 - cw + (1 - a) * 700 - 18 * (t / max(p.dur, 0.1)))
        y = 170
        d = ImageDraw.Draw(fr, "RGBA")
        d.rectangle([x - 14, y + 18, x + cw - 14, y + chh + 18], fill=(0, 0, 0, 130))
        fr.paste(card, (x, y))
        d.rectangle([x, y + chh - 9, x + int(cw * a), y + chh], fill=RED)
        if v.get("headline"):
            f, ls = fit(v["headline"], "xbold", 560, 5, 56, 32)
            yy = y + 40
            for i, l in enumerate(ls):
                b = stagger(t, i + 1)
                hl_line(d, (90 - int(40 * (1 - b)), yy), l, f, v.get("highlight"), alpha=int(255 * b))
                yy += int(f.size * 1.15)
        return fr, credit
    if layout == "split":
        pid2 = ids[(v.get("_k", 0) + 1) % len(ids)]
        img2, credit2 = doc.photos[pid2]
        fr = Image.new("RGB", (W, H), BG[:3])
        fr.paste(kenburns(img, t, p.dur, p.idx, 954, H), (0, 0))
        fr.paste(kenburns(img2, t, p.dur, p.idx + 1, 954, H), (966, 0))
        ImageDraw.Draw(fr).rectangle([954, 0, 965, H], fill=RED)
        fr = fr.convert("RGBA")
        fr.alpha_composite(gradient("bottom"))
        fr = fr.convert("RGB")
        _headline(fr, v, t)
        return fr, credit if credit == credit2 else f"{credit} | {credit2}"
    fr = kenburns(img, t, p.dur, p.idx)
    if t < 0.6 and p.idx % 3 == 0:          # punch-in: quick zoom settle on entry
        z = 1 + 0.12 * (1 - ease(t / 0.6))
        fr = cover(fr, W, H, zoom=z, fx=0.5, fy=0.5)
    fr = fr.convert("RGBA")
    fr.alpha_composite(gradient("bottom"))
    fr = fr.convert("RGB")
    _headline(fr, v, t)
    return fr, credit


def _headline(fr: Image.Image, v: dict, t: float) -> None:
    d = ImageDraw.Draw(fr, "RGBA")
    y_base = 960
    if v.get("headline"):
        f, ls = fit(v["headline"], "xbold", 1300, 2, 66, 44)
        y = y_base - len(ls) * int(f.size * 1.12)
        for i, l in enumerate(ls):
            a = stagger(t, i)
            hl_line(d, (90, y + int(24 * (1 - a))), l, f, v.get("highlight"), alpha=int(255 * a))
            y += int(f.size * 1.12)
        y_base = 960 - len(ls) * int(f.size * 1.12) - 20
    lt = v.get("lower_third")
    if lt and t < 6.5:
        a = ease(min(1, t / 0.5)) * (1 - ease(max(0, (t - 6.0) / 0.5)))
        fn, fr_ = font("xbold", 40), font("med", 28)
        w = int(max(fn.getlength(lt.get("name", "")), fr_.getlength(lt.get("role", ""))) + 60)
        x = 90 - int((1 - a) * (w + 100))
        y = y_base - 120
        d.rectangle([x, y, x + 10, y + 104], fill=RED[:3] + (int(255 * a),))
        d.rectangle([x + 10, y, x + 10 + w, y + 58], fill=(255, 255, 255, int(240 * a)))
        d.text((x + 34, y + 7), lt.get("name", "").upper(), font=fn, fill=(18, 18, 18, int(255 * a)))
        d.rectangle([x + 10, y + 58, x + 10 + w, y + 104], fill=(18, 18, 20, int(225 * a)))
        d.text((x + 34, y + 64), lt.get("role", ""), font=fr_, fill=GREY[:3] + (int(255 * a),))


def _title(d, text: str, t: float, y=120, x=110, size=56):
    a = stagger(t, 0)
    d.rectangle([x, y + 8, x + 10, y + size + 4], fill=RED)
    d.text((x + 34 - int(20 * (1 - a)), y), text.upper(), font=font("xbold", size), fill=WHITE[:3] + (int(255 * a),))


def _source(d, text: str, t: float):
    if text:
        d.text((110, 960), f"Quelle: {text}", font=font("med", 28), fill=GREY[:3] + (int(255 * stagger(t, 3)),))


def draw_bars(p: Piece, t: float, doc: Doc) -> Image.Image:
    v = p.vis
    fr = backdrop().copy()
    d = ImageDraw.Draw(fr, "RGBA")
    _title(d, v.get("title", ""), t)
    items = v["items"]
    mx = max(abs(float(x[1])) for x in items) or 1
    n = len(items)
    dec = v.get("decimals", 1 if any(float(x[1]) % 1 for x in items) else 0)
    unit = v.get("unit", "")
    top, bottom = 250, 900
    row = (bottom - top) / n
    bh = min(78, row * 0.62)
    lf = font("semi", 34 if n <= 5 else 28)
    vf = font("xbold", 46 if n <= 5 else 36)
    hi = v.get("highlight_last", True)
    for i, (lab, val) in enumerate(items):
        y = top + i * row + (row - bh) / 2
        g = stagger(t, i, 0.18, 0.9)
        d.text((110, y + bh / 2), str(lab), font=lf, fill=WHITE, anchor="lm")
        x0 = 520
        L = (1450 - x0) * abs(float(val)) / mx * g
        col = RED if (hi and i == n - 1) or v.get("highlight") == lab else (110, 110, 118)
        d.rectangle([x0, y, x0 + max(4, L), y + bh], fill=col)
        d.text((x0 + L + 22, y + bh / 2), f"{de_num(float(val) * g, dec)}{unit}", font=vf,
               fill=WHITE[:3] + (int(255 * min(1, g * 1.5)),), anchor="lm")
    _source(d, v.get("source", ""), t)
    return fr


def draw_counter(p: Piece, t: float, doc: Doc) -> Image.Image:
    v = p.vis
    fr = backdrop().copy()
    d = ImageDraw.Draw(fr, "RGBA")
    g = ease(min(1, t / 1.8))
    val = float(v["value"]) * g
    txt = f"{v.get('prefix', '')}{de_num(val, v.get('decimals', 0))}{v.get('suffix', '')}"
    f, _ = fit(txt, "black", 1650, 1, 230, 110)
    d.text((W / 2, 470), txt, font=f, fill=RED, anchor="mm")
    lab = v.get("label", "")
    if lab:
        fl, ls = fit(lab, "bold", 1400, 2, 54, 38)
        y = 640
        for i, l in enumerate(ls):
            a = stagger(t, i + 3)
            d.text((W / 2, y + int(20 * (1 - a))), l, font=fl, fill=WHITE[:3] + (int(255 * a),), anchor="mm")
            y += int(fl.size * 1.2)
    _source(d, v.get("source", ""), t)
    return fr


def draw_timeline(p: Piece, t: float, doc: Doc) -> Image.Image:
    v = p.vis
    fr = backdrop().copy()
    d = ImageDraw.Draw(fr, "RGBA")
    _title(d, v.get("title", ""), t)
    ev = v["events"]
    n = len(ev)
    x0, x1, y = (300, 1620, 560) if n <= 3 else (230, 1690, 560)
    step = max(0.6, min(1.4, (p.dur - 1.5) / n))
    prog = ease(min(1, t / (step * n)))
    d.line([(x0, y), (x0 + (x1 - x0) * prog, y)], fill=(90, 90, 98), width=6)
    yf, lf = font("black", 62), font("semi", 30)
    colw = (x1 - x0) / max(1, n - 1) if n > 1 else 600
    for i, (yr, lab) in enumerate(ev):
        x = x0 + (x1 - x0) * (i / (n - 1) if n > 1 else 0.5)
        a = ease(max(0, min(1, (t - i * step) / 0.5)))
        if a <= 0:
            continue
        last = i == n - 1
        r = 16 + 6 * a
        d.ellipse([x - r, y - r, x + r, y + r], fill=(RED if last else WHITE)[:3] + (int(255 * a),))
        d.text((x, y - 70 - int(20 * (1 - a))), str(yr), font=yf, fill=(RED if last else WHITE)[:3] + (int(255 * a),), anchor="mm")
        ls = wrap(str(lab), lf, int(min(colw * 0.92, 380)))[:4]
        yy = y + 60
        for l in ls:
            hw = lf.getlength(l) / 2
            tx = min(max(x, 70 + hw), W - 70 - hw)
            d.text((tx, yy), l, font=lf, fill=GREY[:3] + (int(255 * a),), anchor="mt")
            yy += 40
    return fr


def draw_quote(p: Piece, t: float, doc: Doc) -> tuple[Image.Image, str]:
    v = p.vis
    credit = ""
    if v.get("photo") in doc.photos:
        img, credit = doc.photos[v["photo"]]
        fr = blurred(v["photo"], img).copy()
        card = kenburns(img, t, p.dur, p.idx, 620, 780)
        fr.paste(card, (90, 150))
        d = ImageDraw.Draw(fr, "RGBA")
        d.rectangle([90, 150, 99, 930], fill=RED)
        x, mw = 800, 1020
    else:
        fr = backdrop().copy()
        d = ImageDraw.Draw(fr, "RGBA")
        x, mw = 200, 1500
    d.text((x - 10, 120), "„", font=font("black", 260), fill=RED)
    f, ls = fit(v["text"], "bold", mw, 6, 62, 38)
    y = 360
    for i, l in enumerate(ls):
        a = stagger(t, i, 0.25, 0.6)
        d.text((x, y + int(16 * (1 - a))), l, font=f, fill=WHITE[:3] + (int(255 * a),))
        y += int(f.size * 1.25)
    a = stagger(t, len(ls) + 1, 0.25, 0.6)
    d.text((x, y + 30), "— " + v.get("who", ""), font=font("semi", 34), fill=GREY[:3] + (int(255 * a),))
    return fr, credit


def draw_compare(p: Piece, t: float, doc: Doc) -> tuple[Image.Image, str]:
    v = p.vis
    fr = Image.new("RGB", (W, H), BG[:3])
    credits = []
    for k, side in enumerate(("left", "right")):
        s = v[side]
        x = 0 if k == 0 else 966
        if s.get("photo") in doc.photos:
            img, cr = doc.photos[s["photo"]]
            credits.append(cr)
            ph = kenburns(img, t, p.dur, p.idx + k, 954, H)
            ph = Image.blend(ph, Image.new("RGB", ph.size, (10, 10, 12)), 0.55)
            fr.paste(ph, (x, 0))
        d = ImageDraw.Draw(fr, "RGBA")
        a = stagger(t, k * 2, 0.3, 0.6)
        cx = x + 477
        d.text((cx, 420), s.get("label", "").upper(), font=font("xbold", 58), fill=WHITE[:3] + (int(255 * a),), anchor="mm")
        f, _ = fit(str(s.get("value", "")), "black", 860, 1, 170, 80)
        d.text((cx, 580 + int(30 * (1 - a))), str(s.get("value", "")), font=f,
               fill=(RED if k == 1 else WHITE)[:3] + (int(255 * a),), anchor="mm")
        if s.get("note"):
            fn, ls = fit(s["note"], "semi", 760, 2, 34, 26)
            yy = 720
            for l in ls:
                d.text((cx, yy), l, font=fn, fill=GREY[:3] + (int(255 * a),), anchor="mt")
                yy += 44
    d = ImageDraw.Draw(fr, "RGBA")
    d.rectangle([954, 0, 965, H], fill=RED)
    if v.get("title"):
        tf = font("bold", 38)
        tw = tf.getlength(v["title"].upper()) + 60
        d.rectangle([W / 2 - tw / 2, 200, W / 2 + tw / 2, 262], fill=(18, 18, 20, 235))
        d.text((W / 2, 231), v["title"].upper(), font=tf, fill=WHITE, anchor="mm")
    if v.get("source"):
        d.text((110, 960), f"Quelle: {v['source']}", font=font("med", 28), fill=GREY)
    return fr, " | ".join(dict.fromkeys(credits))


def draw_statement(p: Piece, t: float, doc: Doc) -> Image.Image:
    v = p.vis
    fr = backdrop().copy()
    d = ImageDraw.Draw(fr, "RGBA")
    f, ls = fit(v["text"], "black", 1560, 4, 108, 60)
    lh = int(f.size * 1.14)
    y = H / 2 - len(ls) * lh / 2 - 10
    for i, l in enumerate(ls):
        a = stagger(t, i, 0.22, 0.6)
        tw = f.getlength(l)
        hl_line(d, (W / 2 - tw / 2, y + int(26 * (1 - a))), l, f, v.get("highlight"), alpha=int(255 * a))
        y += lh
    d.rectangle([W / 2 - 60, y + 30, W / 2 + 60, y + 38], fill=RED)
    return fr


def draw_card(p: Piece, t: float, doc: Doc) -> Image.Image:
    """Chapter card (KAPITEL n), title card and end card."""
    v = p.vis
    fr = backdrop().copy()
    d = ImageDraw.Draw(fr, "RGBA")
    a = ease(min(1, t / 0.6))
    if v["type"] == "_chapter":
        n = v["n"]
        d.text((W / 2, 400 - int(30 * (1 - a))), f"KAPITEL {n}", font=font("xbold", 46),
               fill=RED[:3] + (int(255 * a),), anchor="mm")
        f, ls = fit(v["title"], "black", 1500, 2, 120, 72)
        y = 470
        for i, l in enumerate(ls):
            b = stagger(t, i + 1, 0.15, 0.6)
            d.text((W / 2, y + int(30 * (1 - b))), l.upper(), font=f, fill=WHITE[:3] + (int(255 * b),), anchor="mt")
            y += int(f.size * 1.08)
        L = 700 * ease(min(1, t / 1.2))
        d.rectangle([W / 2 - L / 2, y + 40, W / 2 + L / 2, y + 48], fill=RED)
    elif v["type"] == "_title":
        tc = doc.title_card
        d.rectangle([W / 2 - 230, 300, W / 2 + 230, 372], fill=RED[:3] + (int(255 * a),))
        d.text((W / 2, 336), "EILBLICK FOKUS", font=font("black", 50), fill=WHITE[:3] + (int(255 * a),), anchor="mm")
        d.text((W / 2, 432), tc.get("kicker", "HINTERGRUND").upper(), font=font("bold", 36),
               fill=GREY[:3] + (int(255 * a),), anchor="mm")
        f, ls = fit(tc["title"], "black", 1640, 3, 112, 64)
        y = 500
        for i, l in enumerate(ls):
            b = stagger(t, i + 2, 0.15, 0.6)
            d.text((W / 2, y + int(30 * (1 - b))), l, font=f, fill=WHITE[:3] + (int(255 * b),), anchor="mt")
            y += int(f.size * 1.1)
    else:   # _end
        d.rectangle([W / 2 - 230, 360, W / 2 + 230, 432], fill=RED[:3] + (int(255 * a),))
        d.text((W / 2, 396), "EILBLICK FOKUS", font=font("black", 50), fill=WHITE[:3] + (int(255 * a),), anchor="mm")
        d.text((W / 2, 520), "Alle Quellen stehen in der Videobeschreibung.", font=font("bold", 46),
               fill=WHITE[:3] + (int(255 * stagger(t, 2)),), anchor="mm")
        d.text((W / 2, 600), "eilblick.de", font=font("xbold", 54), fill=RED[:3] + (int(255 * stagger(t, 3)),), anchor="mm")
    return fr


DRAW = {"photo": draw_photo, "bars": draw_bars, "counter": draw_counter, "timeline": draw_timeline,
        "quote": draw_quote, "compare": draw_compare, "statement": draw_statement,
        "_chapter": draw_card, "_title": draw_card, "_end": draw_card}


def piece_frame(p: Piece, t: float, doc: Doc) -> tuple[Image.Image, str]:
    r = DRAW[p.vis["type"]](p, t, doc)
    return r if isinstance(r, tuple) else (r, "")


# ------------------------------------------------------------------ overlays
def overlays(fr: Image.Image, t: float, doc: Doc, p: Piece, credit: str) -> None:
    d = ImageDraw.Draw(fr, "RGBA")
    card = p.vis["type"] in ("_title", "_end")
    if not card:
        # branding
        f = font("black", 30)
        w1 = f.getlength("EILBLICK") + 32
        d.rectangle([60, 44, 60 + w1, 92], fill=RED)
        d.text((76, 68), "EILBLICK", font=f, fill=WHITE, anchor="lm")
        d.rectangle([60 + w1, 44, 60 + w1 + f.getlength("FOKUS") + 32, 92], fill=(18, 18, 20, 220))
        d.text((76 + w1, 68), "FOKUS", font=f, fill=WHITE, anchor="lm")
        # chapter label
        if 0 <= p.act < 6 and p.vis["type"] != "_chapter":
            lab = f"KAPITEL {p.act + 1} · {doc.acts[p.act][2].upper()}"
            fl = font("bold", 26)
            tw = fl.getlength(lab)
            d.rectangle([W - 60 - tw - 32, 48, W - 60, 88], fill=(18, 18, 20, 200))
            d.text((W - 76, 68), lab, font=fl, fill=WHITE, anchor="rm")
    # chapter progress bar
    if doc.acts and not card:
        x0, x1, y, gap = 60, W - 60, 1046, 10
        seg = (x1 - x0 - gap * 5) / 6
        for i, (s, e, _) in enumerate(doc.acts):
            xs = x0 + i * (seg + gap)
            d.rectangle([xs, y, xs + seg, y + 6], fill=(255, 255, 255, 60))
            fill = 1 if t >= e else max(0.0, (t - s) / (e - s)) if t > s else 0
            if fill > 0:
                d.rectangle([xs, y, xs + seg * fill, y + 6], fill=RED)
    if credit:
        fc = font("med", 22)
        txt = credit if credit.lower().startswith(("bild", "foto")) else f"Bild: {credit}"
        txt = txt[:110]
        tw = fc.getlength(txt)
        d.rectangle([W - 60 - tw - 20, 1002, W - 60, 1032], fill=(0, 0, 0, 150))
        d.text((W - 70, 1017), txt, font=fc, fill=(220, 220, 225), anchor="rm")


# ------------------------------------------------------------------ main loop
def frame_at(t: float, doc: Doc, cur: int) -> tuple[Image.Image, int]:
    ps = doc.pieces
    while cur + 1 < len(ps) and t >= ps[cur + 1].start:
        cur += 1
    p = ps[cur]
    fr, credit = piece_frame(p, t - p.start, doc)
    # cross-fade into the next piece
    if cur + 1 < len(ps):
        nxt = ps[cur + 1]
        lead = nxt.start - t
        if 0 < lead < FADE:
            nf, ncred = piece_frame(nxt, 0.0, doc)
            k = ease(1 - lead / FADE)
            fr = Image.blend(fr, nf, k)
            if k > 0.5:
                credit, p = ncred, nxt
    overlays(fr, t, doc, p, credit)
    return fr, cur


def render(doc: Doc, wav: Path, out: Path, preview_dir: Path | None = None, crf: int = 21,
           preview_every: float = 12.0) -> Path:
    n = int(doc.total * FPS)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-g", str(FPS * 2), "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           "-movflags", "+faststart", "-shortest", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cur, nextp = 0, 1.0
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        t = i / FPS
        fr, cur = frame_at(t, doc, cur)
        proc.stdin.write(fr.tobytes())
        if preview_dir and t >= nextp:
            fr.save(preview_dir / f"f_{int(t):04d}.jpg", quality=82)
            nextp += preview_every
        if i % (FPS * 30) == 0:
            print(f"  render {t / 60:.1f}/{doc.total / 60:.1f} min", flush=True)
    proc.stdin.close()
    if proc.wait():
        raise RuntimeError("ffmpeg failed")
    return out


# ------------------------------------------------------------------ thumbnail 1280×720
def thumbnail(doc: Doc, th: dict, out: Path) -> Path:
    TW, TH = 1280, 720
    img, _ = doc.photos[th["photo"]]
    fr = cover(img, TW, TH, zoom=1.08, fx=th.get("fx", 0.62), fy=0.4).convert("RGBA")
    g = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(g)
    for x in range(TW):
        a = int(235 * max(0, 1 - x / (TW * 0.78)) ** 1.1)
        gd.line([(x, 0), (x, TH)], fill=(10, 10, 12, a))
    fr.alpha_composite(g)
    d = ImageDraw.Draw(fr, "RGBA")
    d.rectangle([48, 44, 340, 100], fill=RED)
    d.text((64, 72), "EILBLICK FOKUS", font=font("black", 34), fill=WHITE, anchor="lm")
    words = th["words"].upper()
    f, ls = fit(words, "black", 760, 3, 150, 90)
    lh = int(f.size * 1.0)
    room = 720 - 130 - (90 if th.get("sub") else 30)
    while len(ls) * lh > room and f.size > 80:
        f = font("black", f.size - 8)
        ls = wrap(words, f, 760)
        lh = int(f.size * 1.0)
    y = 125 + max(0, (room - len(ls) * lh) // 2)
    hs = [h.upper() for h in th.get("highlight", [])]
    for l in ls:
        x = 52
        for w in l.split():
            col = RED if w.strip(".,!?") in hs else WHITE
            d.text((x + 4, y + 5), w, font=f, fill=(0, 0, 0, 160))
            d.text((x, y), w, font=f, fill=col)
            x += f.getlength(w + " ")
        y += lh
    if th.get("sub"):
        fs = font("bold", 40)
        tw = fs.getlength(th["sub"]) + 36
        d.rectangle([52, y + 18, 52 + tw, y + 78], fill=(255, 255, 255, 235))
        d.text((70, y + 48), th["sub"], font=fs, fill=(18, 18, 18), anchor="lm")
    fr.convert("RGB").save(out, "JPEG", quality=90)
    return out
