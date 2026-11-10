"""Broadcast-style 9:16 renderer (1080×1920, 30 fps).

Screen layout (safe zones respected: nothing important in the right 140 px
or below y≈1560 where YouTube/Facebook draw their buttons and captions):

  ┌──────────────────────────────┐
  │ [E] EILBLICK      AKTUELL 07:30│  y 110–210  top bar, logo, clock
  │ 1/4 · POLITIK                │  y 260
  │ ┌──────────────────────────┐ │
  │ │  news photo (Ken Burns)  │ │  y 310–930 photo card, changes every ~2.8 s
  │ │ Bild: tagesschau.de      │ │
  │ └──────────────────────────┘ │
  │ ▌BERLIN                      │  y 958 kicker
  │ Headline in white, KEY red   │  y 1030 headline (≤2 lines)
  │ voice-synced caption words   │  y ≤1266 caption
  │ Quelle: tagesschau · ORF     │  y 1398
  │ ▌EILBLICK +++ ticker +++     │  y 1436 ticker (inside side margins, above platform UI)
  └──────────────────────────────┘
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ASSETS, FONTS, settings

W, H = 1080, 1920


def hexc(h: str, a: int = 255) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


C = {k: hexc(v) for k, v in settings()["video"]["colors"].items()}


@lru_cache(maxsize=64)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    files = {
        "black": ["BarlowCondensed-ExtraBold.ttf", "InterDisplay-Black.otf"],
        "xbold": ["BarlowCondensed-Bold.ttf", "InterDisplay-ExtraBold.otf"],
        "bold": ["Inter-Bold.otf", "InterDisplay-Bold.otf"],
        "semi": ["Inter-SemiBold.otf"],
        "med": ["Inter-Medium.otf"],
    }[kind]
    for f in files:
        p = FONTS / f
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_io(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


# ------------------------------------------------------------------ data
@dataclass
class StoryClip:
    start: float
    end: float
    voice_start: float
    words: list                 # [(word, abs_start, abs_end)]
    photos: list                # [Photo]
    kicker: str
    headline: str
    highlight: list
    pillar: str
    sources: list
    index: int
    total: int


@dataclass
class Timeline:
    total: float
    intro_end: float
    end_start: float
    hook_text: str
    hook_highlight: list
    date_text: str
    slot_label: str
    clock: str
    stories: list = field(default_factory=list)
    ticker: list = field(default_factory=list)


# ------------------------------------------------------------------ text helpers
def wrap_words(words: list[str], fnt, max_w: int) -> list[list[str]]:
    lines, cur = [], []
    for w in words:
        test = " ".join(cur + [w])
        if cur and fnt.getlength(test) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def fit_text(text: str, kind: str, max_w: int, max_lines: int, start: int, minimum: int):
    words = text.split()
    size = start
    while size >= minimum:
        f = font(kind, size)
        lines = wrap_words(words, f, max_w)
        if len(lines) <= max_lines and all(f.getlength(" ".join(l)) <= max_w for l in lines):
            return f, lines
        size -= 4
    f = font(kind, minimum)
    return f, wrap_words(words, f, max_w)


def _is_hl(word: str, highlight: list) -> bool:
    w = word.strip(".,:;!?„“\"'()–-").lower()
    for h in highlight:
        for part in h.lower().split():
            if part and (w == part or (len(part) > 4 and w.startswith(part[:-1]))):
                return True
    return any(ch.isdigit() for ch in w)


def text_block(text: str, kind: str, max_w: int, max_lines: int, size: int, minimum: int,
               highlight: list, color=None, hl_color=None, line_gap: float = 1.08,
               shadow: bool = True) -> Image.Image:
    color = color or C["white"]
    hl_color = hl_color or C["red"]
    f, lines = fit_text(text, kind, max_w, max_lines, size, minimum)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_gap)
    img = Image.new("RGBA", (max_w + 20, lh * len(lines) + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    space = f.getlength(" ")
    for i, line in enumerate(lines):
        x = 4
        for w in line:
            col = hl_color if _is_hl(w, highlight) else color
            if shadow:
                d.text((x + 3, i * lh + 4), w, font=f, fill=(0, 0, 0, 150))
            d.text((x, i * lh), w, font=f, fill=col)
            x += f.getlength(w) + space
    return img


# ------------------------------------------------------------------ static layers
@lru_cache(maxsize=1)
def grid_layer() -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 54):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 10))
    for y in range(0, H, 54):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 10))
    # vignette
    v = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(v)
    for i in range(40):
        a = int(255 * (i / 40) ** 2)
        vd.rectangle([i * 12, i * 20, W - i * 12, H - i * 20], outline=255 - a)
    v = v.filter(ImageFilter.GaussianBlur(60))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dark.putalpha(v.point(lambda p: int(p * 0.55)))
    img.alpha_composite(dark)
    # bottom gradient for text legibility
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(1000, H):
        a = int(235 * min(1, (y - 1000) / 260))
        gd.line([(0, y), (W, y)], fill=(12, 12, 14, a))
    img.alpha_composite(grad)
    return img


@lru_cache(maxsize=4)
def logo_mark(height: int) -> Image.Image | None:
    """The channel's E-shutter mark (background already removed)."""
    for name in ("logo_mark.png", "logo.png"):
        p = ASSETS / name
        if p.exists():
            lg = Image.open(p).convert("RGBA")
            bb = lg.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
            lg = lg.crop(bb) if bb else lg
            r = height / lg.height
            return lg.resize((max(1, int(lg.width * r)), height), Image.LANCZOS)
    return None


@lru_cache(maxsize=4)
def logo_image(height: int = 78) -> Image.Image:
    """Mark + EIL|BLICK wordmark, used in the top bar."""
    mark = logo_mark(height)
    f = font("black", int(height * 0.72))
    tw = int(f.getlength("EILBLICK")) + 10
    mw = mark.width if mark else height
    img = Image.new("RGBA", (mw + 16 + tw, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if mark:
        img.alpha_composite(mark, (0, 0))
    else:
        d.rounded_rectangle([0, 0, height, height], radius=12, fill=C["red"])
    asc, desc = f.getmetrics()
    y = (height - (asc + desc)) // 2 + 2
    d.text((mw + 16 + 2, y + 2), "EILBLICK", font=f, fill=(0, 0, 0, 160))
    d.text((mw + 16, y), "EIL", font=f, fill=C["white"])
    d.text((mw + 16 + f.getlength("EIL"), y), "BLICK", font=f, fill=C["red"])
    return img


def cover(img: Image.Image, w: int, h: int, zoom: float = 1.0, fx: float = 0.5, fy: float = 0.42) -> Image.Image:
    iw, ih = img.size
    scale = max(w / iw, h / ih) * zoom
    cw, ch = w / scale, h / scale
    x0 = (iw - cw) * fx
    y0 = (ih - ch) * fy
    return img.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


def follow_cue(fr: Image.Image, t: float, total: float, y: int = 196):
    """Subtle subscribe cue (growth 8 Nov 2026): small pill under the top bar from 55 % to 95 % of the video."""
    a = min(ease((t - 0.55 * total) / 0.4), 1 - ease((t - 0.95 * total) / 0.3))
    if a <= 0.01:
        return
    d = ImageDraw.Draw(fr)
    f = font("black", 30)
    txt = "+ FOLGEN"
    sub = "12× täglich News"
    f2 = font("semi", 26)
    w = f.getlength(txt) + f2.getlength(sub) + 64
    x = 1020 - w
    d.rounded_rectangle([x, y, x + w, y + 52], radius=26, fill=(214, 26, 32, int(235 * a)))
    d.text((x + 22, y + 9), txt, font=f, fill=(255, 255, 255, int(255 * a)))
    d.text((x + 34 + f.getlength(txt), y + 13), sub, font=f2, fill=(255, 235, 235, int(255 * a)))


class PhotoCache:
    def __init__(self):
        self.full = {}
        self.blur = {}

    def get(self, photo) -> Image.Image:
        k = str(photo.path)
        if k not in self.full:
            im = Image.open(photo.path).convert("RGB")
            if im.width > 2000:
                im = im.resize((2000, int(im.height * 2000 / im.width)), Image.LANCZOS)
            self.full[k] = im
        return self.full[k]

    def blurred(self, photo) -> Image.Image:
        k = str(photo.path)
        if k not in self.blur:
            bg = cover(self.get(photo), W // 4, H // 4).filter(ImageFilter.GaussianBlur(10))
            bg = bg.resize((W + 80, H + 140), Image.BILINEAR)
            dark = Image.new("RGB", bg.size, (12, 12, 14))
            self.blur[k] = Image.blend(bg, dark, 0.58)
        return self.blur[k]


# ------------------------------------------------------------------ renderer
class Renderer:
    CARD = (60, 310, 1020, 930)    # photo card box

    def __init__(self, tl: Timeline):
        self.tl = tl
        self.pc = PhotoCache()
        self.fps = settings()["video"]["fps"]
        self.caption_cache = {}
        self.headline_cache = {}
        self.ticker_strip = self._ticker()
        self.logo = logo_image(78)
        self.last = None
        self._validate_photos()
        self.mask = Image.new("L", (self.CARD[2] - self.CARD[0], self.CARD[3] - self.CARD[1]), 0)
        ImageDraw.Draw(self.mask).rounded_rectangle([0, 0, *self.mask.size], radius=22, fill=255)

    def _validate_photos(self):
        """Drop any photo that cannot be opened/cropped (a single bad photo must never
        stop the video). EILBLICK_SAFE=1 renders without photos as a last resort."""
        import os
        safe = os.environ.get("EILBLICK_SAFE") == "1"
        x0, y0, x1, y1 = self.CARD
        for st in self.tl.stories:
            good = []
            for ph in ([] if safe else st.photos):
                try:
                    im = self.pc.get(ph)
                    for z in (1.0, 1.15):
                        cover(im, x1 - x0, y1 - y0, z, 0.5, 0.4)
                    self.pc.blurred(ph)
                    good.append(ph)
                except Exception as e:
                    print(f"  photo skipped ({ph.credit}): {e}")
            st.photos = good

    # ---- pieces
    def _ticker(self) -> Image.Image:
        f = font("semi", 34)
        text = "   +++   ".join(self.tl.ticker) + "   +++   "
        text = text * 3
        w = int(f.getlength(text)) + 10
        img = Image.new("RGBA", (w, 62), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((0, 10), text, font=f, fill=C["white"])
        return img

    def top_bar(self, fr: Image.Image, t: float, story: StoryClip | None):
        d = ImageDraw.Draw(fr)
        fr.alpha_composite(self.logo, (60, 112))
        # clock + AKTUELL pill
        f = font("bold", 34)
        pill = "AKTUELL"
        pw = f.getlength(pill) + 36
        x = 1020 - pw - f.getlength(self.tl.clock) - 26
        blink = 0.65 + 0.35 * math.sin(t * 5)
        d.rounded_rectangle([x, 122, x + pw, 180], radius=10, fill=C["red"])
        d.ellipse([x + 14, 143, x + 26, 155], fill=(255, 255, 255, int(255 * blink)))
        d.text((x + 32, 128), pill[0:], font=f, fill=C["white"])
        d.text((x + pw + 18, 128), self.tl.clock, font=f, fill=C["white"])

    def story_label(self, fr, story: StoryClip, a: float):
        d = ImageDraw.Draw(fr)
        f = font("bold", 32)
        txt = f"{story.index}/{story.total}"
        d.text((62, 254), txt, font=f, fill=(255, 255, 255, int(200 * a)))
        x = 62 + f.getlength(txt) + 22
        pw = f.getlength(story.pillar) + 30
        d.rounded_rectangle([x, 250, x + pw, 296], radius=8, outline=(255, 42, 42, int(255 * a)), width=3)
        d.text((x + 15, 254), story.pillar, font=f, fill=(255, 90, 90, int(255 * a)))

    def photo_card(self, fr, story: StoryClip, t: float):
        x0, y0, x1, y1 = self.CARD
        cw, ch = x1 - x0, y1 - y0
        if not story.photos:
            self._graphic_card(fr, story, t)
            return
        per = settings()["video"]["seconds_per_image"]
        dur = story.end - story.start
        n_needed = max(1, math.ceil(dur / per))
        order = [story.photos[i % len(story.photos)] for i in range(n_needed)]
        lt = t - story.start
        idx = min(int(lt / per), len(order) - 1)
        local = (lt - idx * per) / per

        def frame_of(i, loc):
            ph = order[i]
            img = self.pc.get(ph)
            zoom = 1.04 + 0.10 * loc if i % 2 == 0 else 1.14 - 0.10 * loc
            fx = 0.5 + (0.08 * (loc - 0.5) if i % 3 else 0)
            return cover(img, cw, ch, zoom, fx, 0.40), ph

        im, ph = frame_of(idx, local)
        card = Image.new("RGBA", (cw, ch))
        card.paste(im)
        # cross-slide to next photo in the last 0.3 s
        if idx + 1 < len(order) and local * per > per - 0.3:
            k = ease_io((local * per - (per - 0.3)) / 0.3)
            nxt, nph = frame_of(idx + 1, 0)
            off = min(cw - 1, max(0, int(cw * (1 - k))))
            card.paste(nxt.crop((0, 0, cw - off, ch)), (off, 0))
            ImageDraw.Draw(card).rectangle([off - 8, 0, off, ch], fill=C["red"])
            if k > 0.5:
                ph = nph
        # entrance of the card per story
        a = ease((t - story.start) / 0.35)
        shadow = Image.new("RGBA", (cw + 60, ch + 60), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle([30, 40, cw + 30, ch + 40], radius=26, fill=(0, 0, 0, 150))
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        yy = int(y0 + (1 - a) * 40)
        fr.alpha_composite(shadow, (x0 - 30, yy - 30))
        cm = card.copy()
        cm.putalpha(self.mask.point(lambda p: int(p * a)))
        fr.alpha_composite(cm, (x0, yy))
        d = ImageDraw.Draw(fr)
        d.rounded_rectangle([x0, yy, x1, yy + ch], radius=22, outline=(255, 255, 255, int(40 * a)), width=2)
        d.rectangle([x0, yy + 30, x0 + 8, yy + ch - 30], fill=C["red"])
        # credit
        f = font("med", 24)
        cr = f"Bild: {ph.credit}"[:60]
        tw = f.getlength(cr)
        d.rounded_rectangle([x0 + 22, yy + ch - 58, x0 + 46 + tw, yy + ch - 20], radius=8, fill=(0, 0, 0, 160))
        d.text((x0 + 34, yy + ch - 54), cr, font=f, fill=(235, 235, 240, 255))

    def _graphic_card(self, fr, story: StoryClip, t: float):
        x0, y0, x1, y1 = self.CARD
        d = ImageDraw.Draw(fr)
        d.rounded_rectangle([x0, y0, x1, y1], radius=22, fill=C["panel"])
        for i in range(0, x1 - x0, 40):
            d.line([(x0 + i, y0), (x0 + i, y1)], fill=(255, 255, 255, 12))
        pulse = (t * 0.6) % 1
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 - 30
        for k in range(3):
            r = 60 + ((pulse + k / 3) % 1) * 260
            al = int(180 * (1 - ((pulse + k / 3) % 1)))
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 42, 42, al), width=4)
        d.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=C["red"])
        f, lines = fit_text(story.kicker, "black", 860, 1, 130, 60)
        tx = " ".join(lines[0])
        d.text((cx - f.getlength(tx) / 2, y1 - 210), tx, font=f, fill=C["white"])

    def kicker_headline(self, fr, story: StoryClip, t: float):
        lt = t - story.start
        a = ease((lt - 0.15) / 0.4)
        d = ImageDraw.Draw(fr)
        f = font("black", 46)
        kw = f.getlength(story.kicker) + 40
        x = 60 - (1 - a) * 300
        d.rectangle([x, 958, x + kw, 1018], fill=C["red"])
        d.text((x + 20, 960), story.kicker, font=f, fill=C["white"])
        d.text((x + kw + 18, 968), "HEUTE", font=font("bold", 34), fill=(220, 220, 228, int(255 * a)))
        key = story.index
        if key not in self.headline_cache:
            self.headline_cache[key] = text_block(story.headline.upper(), "black", 930, 2, 80, 54, story.highlight)
        hb = self.headline_cache[key]
        ha = ease((lt - 0.3) / 0.45)
        if ha > 0:
            reveal = int(hb.width * ha)
            crop = hb.crop((0, 0, max(1, reveal), hb.height))
            fr.alpha_composite(crop, (56, 1030))

    def caption(self, fr, story: StoryClip, t: float):
        words = story.words
        if not words or t < story.voice_start:
            return
        # chunk into groups of ~4 words, show the active group
        groups, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= 4 or w[0].endswith((".", ",", ":", "?", "!")):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        gi = 0
        for i, g in enumerate(groups):
            if t >= g[0][1] - 0.05:
                gi = i
        g = groups[gi]
        active = sum(1 for w in g if t >= w[1])
        key = (story.index, gi, active)
        if key not in self.caption_cache:
            f = font("bold", 50)
            img = Image.new("RGBA", (960, 136), (0, 0, 0, 0))
            dd = ImageDraw.Draw(img)
            lines = wrap_words([w[0] for w in g], f, 900)
            k = 0
            for li, line in enumerate(lines[:2]):
                x = 0
                for w in line:
                    hl = _is_hl(w, story.highlight)
                    col = C["red"] if hl else (C["white"] if k < active else (150, 150, 160, 255))
                    dd.text((x + 2, li * 64 + 3), w, font=f, fill=(0, 0, 0, 170))
                    dd.text((x, li * 64), w, font=f, fill=col)
                    x += f.getlength(w + " ")
                    k += 1
            self.caption_cache[key] = img
        hb = self.headline_cache.get(story.index)
        cy = min(1266, 1030 + (hb.height if hb else 120) + 4)
        fr.alpha_composite(self.caption_cache[key], (62, cy))

    def source_line(self, fr, story: StoryClip, t: float):
        a = ease((t - story.start - 0.6) / 0.4)
        f = font("med", 26)
        txt = "Quelle: " + " · ".join(story.sources[:3])
        ImageDraw.Draw(fr).text((62, 1398), txt, font=f, fill=(190, 190, 200, int(230 * a)))

    def ticker(self, fr, t: float):
        """News ticker kept fully inside the safe area: 40 px side margins, above the
        platform captions; the label never overlaps the running text."""
        y, h, x0, x1 = 1436, 58, 40, 1040
        d = ImageDraw.Draw(fr)
        d.rounded_rectangle([x0, y, x1, y + h], radius=10, fill=(10, 10, 12, 235))
        f = font("black", 34)
        label = "EILBLICK"
        lw = int(f.getlength(label)) + 40
        run_x0 = x0 + lw + 30
        speed = 95
        period = max(1, self.ticker_strip.width // 3)
        off = int(t * speed) % period
        strip = self.ticker_strip.crop((off, 0, off + (x1 - 12 - run_x0), 62))
        # soft fade at both ends so no letter is hard-cut
        m = Image.new("L", strip.size, 255)
        md = ImageDraw.Draw(m)
        for i in range(40):
            v = int(255 * i / 40)
            md.line([(i, 0), (i, strip.height)], fill=v)
            md.line([(strip.width - 1 - i, 0), (strip.width - 1 - i, strip.height)], fill=v)
        strip.putalpha(Image.composite(strip.getchannel("A"), Image.new("L", strip.size, 0), m))
        fr.alpha_composite(strip, (run_x0, y - 2))
        d.rounded_rectangle([x0, y, x0 + lw, y + h], radius=10, fill=C["red"])
        d.polygon([(x0 + lw - 2, y), (x0 + lw + 22, y + h // 2), (x0 + lw - 2, y + h)], fill=C["red"])
        asc, desc = f.getmetrics()
        d.text((x0 + 20, y + (h - asc - desc) // 2 + 2), label, font=f, fill=C["white"])

    def background(self, fr, photo, t):
        if photo is None:
            fr.paste(C["bg"][:3], (0, 0, W, H))
        else:
            bg = self.pc.blurred(photo)
            dx = int(40 + 30 * math.sin(t * 0.3))
            dy = int(70 + 50 * math.cos(t * 0.25))
            fr.paste(bg.crop((dx, dy, dx + W, dy + H)), (0, 0))
        fr.alpha_composite(grid_layer())

    def wipe(self, fr, t, at):
        """Red diagonal wipe between stories."""
        k = (t - (at - 0.25)) / 0.5
        if not 0 <= k <= 1:
            return
        x = -W * 0.6 + (W * 2.2) * ease_io(k)
        d = ImageDraw.Draw(fr)
        d.polygon([(x - 500, 0), (x + 200, 0), (x - 200, H), (x - 900, H)], fill=C["red"])
        d.polygon([(x + 200, 0), (x + 260, 0), (x - 140, H), (x - 200, H)], fill=C["white"])

    # ---- scenes
    def intro(self, fr, t):
        tl = self.tl
        s0 = tl.stories[0]
        ph = s0.photos[0] if s0.photos else None
        self.background(fr, ph, t)
        if ph:   # large photo for a thumbnail-worthy first frame
            img = cover(self.pc.get(ph), W, 1180, 1.06 + 0.04 * t, 0.5, 0.4)
            hero = img.convert("RGBA")
            g = Image.new("L", (W, 1180), 255)
            gd = ImageDraw.Draw(g)
            for y in range(700, 1180):
                gd.line([(0, y), (W, y)], fill=int(255 * (1 - (y - 700) / 480)))
            hero.putalpha(g)
            fr.alpha_composite(hero, (0, 230))
            fr.alpha_composite(grid_layer())
        self.top_bar(fr, t, None)
        d = ImageDraw.Draw(fr)
        f = font("black", 44)
        label = (tl.slot_label or "DIE SCHLAGZEILEN").upper()
        lw = f.getlength(label) + 44
        d.rectangle([60, 980, 60 + lw, 1044], fill=C["red"])
        d.text((82, 986), label, font=f, fill=C["white"])
        d.text((60, 1058), tl.date_text.upper(), font=font("bold", 36), fill=(225, 225, 232, 255))
        hook = self.headline_cache.get("hook")
        if hook is None:
            hook = self.headline_cache["hook"] = text_block(tl.hook_text.upper(), "black", 950, 2, 128, 70,
                                                            tl.hook_highlight)
        fr.alpha_composite(hook, (54, 1110))
        self.ticker(fr, t)

    def outro(self, fr, t):
        lt = t - self.tl.end_start
        fr.paste(C["bg"][:3], (0, 0, W, H))
        fr.alpha_composite(grid_layer())
        a = ease(lt / 0.45)
        mk = logo_mark(300)
        sc = 0.7 + 0.3 * a
        if mk is not None:
            lgs = mk.resize((int(mk.width * sc), int(mk.height * sc)), Image.LANCZOS)
            lgs.putalpha(lgs.getchannel("A").point(lambda p: int(p * a)))
            fr.alpha_composite(lgs, ((W - lgs.width) // 2, 560 + (300 - lgs.height) // 2))
        d = ImageDraw.Draw(fr)
        fw = font("black", 120)
        wa = ease((lt - 0.12) / 0.4)
        wx = (W - fw.getlength("EILBLICK")) / 2
        d.text((wx, 880), "EIL", font=fw, fill=(255, 255, 255, int(255 * wa)))
        d.text((wx + fw.getlength("EIL"), 880), "BLICK", font=fw, fill=(255, 42, 42, int(255 * wa)))
        f = font("bold", 44)
        sl = settings()["channel"]["slogan"]
        d.text(((W - f.getlength(sl)) / 2, 1030), sl, font=f, fill=(235, 235, 240, int(255 * ease((lt - 0.2) / 0.4))))
        bar = int(520 * ease((lt - 0.1) / 0.5))
        d.rectangle([(W - bar) // 2, 1105, (W + bar) // 2, 1111], fill=C["red"])
        f2 = font("semi", 36)
        site = "eilblick.de"
        d.text(((W - f2.getlength(site)) / 2, 1135), site, font=f2, fill=(180, 180, 190, int(255 * ease((lt - 0.35) / 0.4))))

    def frame(self, t: float) -> Image.Image:
        try:
            img = self._frame(t)
            self.last = img
            return img
        except Exception as e:
            # never crash: drop the photos of the current story and draw the graphic card instead
            print(f"  frame {t:.2f}s fallback: {type(e).__name__}: {e}")
            for st in self.tl.stories:
                if st.start <= t < st.end:
                    st.photos = []
            try:
                img = self._frame(t)
            except Exception as e2:
                print(f"  frame {t:.2f}s second fallback: {e2}")
                img = self.last or Image.new("RGB", (W, H), C["bg"][:3])
            self.last = img
            return img

    def _frame(self, t: float) -> Image.Image:
        fr = Image.new("RGBA", (W, H), C["bg"])
        tl = self.tl
        if t < tl.intro_end:
            self.intro(fr, t)
        else:
            story = next((s for s in tl.stories if s.start <= t < s.end), tl.stories[-1])
            per = settings()["video"]["seconds_per_image"]
            ph = story.photos[int((t - story.start) / per) % len(story.photos)] if story.photos else None
            self.background(fr, ph, t)
            self.top_bar(fr, t, story)
            self.story_label(fr, story, ease((t - story.start) / 0.3))
            self.photo_card(fr, story, t)
            self.kicker_headline(fr, story, t)
            self.caption(fr, story, t)
            self.source_line(fr, story, t)
            self.ticker(fr, t)
        for s in tl.stories:
            self.wipe(fr, t, s.start)
        # seamless loop: the hook frame fades back in during the last 0.35 s
        if t > tl.total - 0.35 and t >= tl.intro_end:
            hook_fr = Image.new("RGBA", (W, H), C["bg"])
            self.intro(hook_fr, 0.0)
            fr = Image.blend(fr, hook_fr, ease((t - (tl.total - 0.35)) / 0.35))
        return fr.convert("RGB")


def render_thumbnail(tl: Timeline, out: Path) -> Path:
    """Click-worthy 9:16 thumbnail: sharpest, largest photo of the top story, boosted
    contrast, huge 2–3 line hook (keyword in signal red), logo + date. Text sits in the
    centre-upper safe zone so no platform button covers it."""
    from PIL import ImageEnhance
    r = Renderer(tl)
    fr = Image.new("RGBA", (W, H), C["bg"])
    photos = [p for s in tl.stories[:1] for p in s.photos] or [p for s in tl.stories for p in s.photos]
    if photos:
        best = max(photos, key=lambda p: p.w * p.h)
        img = r.pc.get(best)
        img = ImageEnhance.Contrast(img).enhance(1.18)
        img = ImageEnhance.Color(img).enhance(1.15)
        img = ImageEnhance.Sharpness(img).enhance(1.3)
        fr.paste(cover(img, W, H, 1.0, 0.5, 0.35), (0, 0))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H):
        if y < 300:
            a = int(170 * (1 - y / 300))
        elif y > 820:
            a = int(225 * min(1, (y - 820) / 380))
        else:
            a = 0
        sd.line([(0, y), (W, y)], fill=(8, 8, 10, a))
    fr.alpha_composite(shade)
    fr.alpha_composite(logo_image(96), (60, 110))
    d = ImageDraw.Draw(fr)
    f = font("black", 52)
    badge = "SCHLAGZEILEN"
    bw = f.getlength(badge) + 56
    d.rounded_rectangle([60, 900, 60 + bw, 980], radius=12, fill=C["red"])
    d.text((88, 908), badge, font=f, fill=C["white"])
    hook = text_block(tl.hook_text.upper(), "black", 960, 3, 168, 92, tl.hook_highlight, line_gap=1.02)
    fr.alpha_composite(hook, (50, 1000))
    d.text((62, 1000 + hook.height + 10), tl.date_text.upper(), font=font("bold", 40), fill=(235, 235, 240, 255))
    d.rectangle([0, 0, W - 1, H - 1], outline=C["red"], width=10)
    fr.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    return out


def render_video(tl: Timeline, audio_wav: Path, out: Path, preview_dir: Path | None = None) -> Path:
    vc = settings()["video"]
    r = Renderer(tl)
    fps = vc["fps"]
    n = int(round(tl.total * fps))
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
        "-r", str(fps), "-i", "-", "-i", str(audio_wav),
        "-c:v", "libx264", "-preset", vc["preset"], "-crf", str(vc["crf"]), "-pix_fmt", "yuv420p",
        "-profile:v", "high", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        "-metadata", "title=Eilblick", "-metadata", "language=deu",
        str(out),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    preview_at = {0, int(n * 0.2), int(n * 0.45), int(n * 0.7), n - 10}
    for i in range(n):
        img = r.frame(i / fps)
        if preview_dir is not None and i in preview_at:
            img.save(preview_dir / f"preview_{i:04d}.jpg", quality=88)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out


# ====================================================================== FOKUS (single story)
@dataclass
class Beat:
    start: float
    end: float
    words: list          # [(word, abs_start, abs_end)]
    big: str = ""
    label: str = ""


@dataclass
class SingleTimeline:
    total: float
    hook_end: float
    hook_screen: str
    kicker: str
    highlight: list
    photos: list
    sources: list
    beats: list = field(default_factory=list)      # hook + data beats + loop line, in order
    loop_start: float = 0.0


class SingleRenderer:
    """One story, full-bleed news photo, giant red shock hook at 0:00, a big data overlay per
    beat, voice-synced captions, no intro and no outro – the last frame flows back into frame 0."""

    def __init__(self, tl: SingleTimeline):
        self.tl = tl
        self.pc = PhotoCache()
        self.last = None
        self.cap_cache = {}
        good = []
        import os
        for ph in ([] if os.environ.get("EILBLICK_SAFE") == "1" else tl.photos):
            try:
                cover(self.pc.get(ph), W, H, 1.1, 0.5, 0.4)
                good.append(ph)
            except Exception as e:
                print(f"  photo skipped ({ph.credit}): {e}")
        tl.photos = good
        self.logo = logo_image(70)
        self.hook_img = text_block(tl.hook_screen.upper(), "black", 980, 3, 190, 96, [tl.hook_screen],
                                   color=C["red"], hl_color=C["red"], line_gap=1.0)
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for y in range(H):
            if y < 380:
                a = int(200 * (1 - y / 380))
            elif y > 700:
                a = int(235 * min(1, (y - 700) / 520))
            else:
                a = 40
            sd.line([(0, y), (W, y)], fill=(8, 8, 10, a))
        self.shade = shade

    def photo_at(self, t):
        if not self.tl.photos:
            return None, 0, 0
        per = settings()["video"]["seconds_per_image"]
        i = int(t / per)
        return self.tl.photos[i % len(self.tl.photos)], i, (t - i * per) / per

    def background(self, fr, t):
        ph, i, loc = self.photo_at(t)
        if ph is None:
            fr.paste(C["bg"][:3], (0, 0, W, H))
            fr.alpha_composite(grid_layer())
            return
        n = max(1, len(self.tl.photos))
        cyc = i // n          # growth 11 Nov: a repeated photo returns as a different, tighter crop
        base = 1.06 + min(0.36, 0.18 * cyc)
        zoom = base + 0.08 * loc if i % 2 == 0 else base + 0.08 - 0.08 * loc
        fx = (0.5, 0.32, 0.68)[cyc % 3] + (0.06 * (loc - 0.5) if i % 3 else 0)
        img = cover(self.pc.get(ph), W, H, zoom, fx, 0.36 if cyc % 2 == 0 else 0.30)
        fr.paste(img, (0, 0))
        per = settings()["video"]["seconds_per_image"]
        if loc * per > per - 0.18 and len(self.tl.photos) > 1:      # quick flash cut to next photo
            k = (loc * per - (per - 0.18)) / 0.18
            nxt = self.tl.photos[(i + 1) % len(self.tl.photos)]
            fr.paste(Image.blend(img, cover(self.pc.get(nxt), W, H, 1.06, 0.5, 0.38), ease_io(k)), (0, 0))
        fr.alpha_composite(self.shade)
        d = ImageDraw.Draw(fr)
        f = font("med", 24)
        cr = f"Bild: {ph.credit}"[:60]
        d.rounded_rectangle([40, 1506, 64 + f.getlength(cr), 1542], radius=8, fill=(0, 0, 0, 150))
        d.text((52, 1510), cr, font=f, fill=(235, 235, 240, 255))

    def top(self, fr):
        fr.alpha_composite(self.logo, (50, 110))
        d = ImageDraw.Draw(fr)
        f = font("black", 36)
        x = 50 + self.logo.width + 26
        d.rounded_rectangle([x, 118, x + f.getlength("FOKUS") + 36, 174], radius=10, fill=C["red"])
        d.text((x + 18, 122), "FOKUS", font=f, fill=C["white"])
        f2 = font("bold", 34)
        d.text((x + f.getlength("FOKUS") + 56, 128), self.tl.kicker.upper(), font=f2, fill=C["white"])

    def hook(self, fr, t, alpha=1.0):
        k = ease(t / 0.22)
        sc = 1.12 - 0.12 * k if t > 0 else 1.0       # frame 0 = final layout (thumbnail-ready)
        img = self.hook_img
        if sc != 1.0:
            img = img.resize((int(img.width * sc), int(img.height * sc)), Image.LANCZOS)
        if alpha < 1:
            img = img.copy()
            img.putalpha(img.getchannel("A").point(lambda p: int(p * alpha)))
        # white "flash" plate behind the red words for maximum contrast
        plate = Image.new("RGBA", (img.width + 40, img.height + 10), (0, 0, 0, 0))
        ImageDraw.Draw(plate).rounded_rectangle([0, 0, plate.width, plate.height], radius=18,
                                                fill=(255, 255, 255, int(235 * alpha)))
        y = 760 - img.height // 2
        fr.alpha_composite(plate, ((W - plate.width) // 2, y - 6))
        fr.alpha_composite(img, ((W - img.width) // 2 + 8, y))

    def data_card(self, fr, b: Beat, t):
        if not b.big:
            return
        a = ease((t - b.start) / 0.3)
        f = None
        for size in (210, 180, 150, 124, 100):
            f = font("black", size)
            if f.getlength(b.big) <= 960:
                break
        y = 690 + int((1 - a) * 60)
        d = ImageDraw.Draw(fr)
        tw = f.getlength(b.big)
        x = (W - tw) / 2
        d.text((x + 6, y + 8), b.big, font=f, fill=(0, 0, 0, int(170 * a)))
        d.text((x, y), b.big, font=f, fill=C["red"][:3] + (int(255 * a),))
        if b.label:
            fl, lines = fit_text(b.label.upper(), "xbold", 940, 2, 62, 40)
            yy = y + f.getmetrics()[0] + f.getmetrics()[1] + 4
            for ln in lines:
                txt = " ".join(ln)
                lw = fl.getlength(txt)
                d.rounded_rectangle([(W - lw) / 2 - 18, yy - 4, (W + lw) / 2 + 18, yy + fl.size + 18], radius=10,
                                    fill=(10, 10, 12, int(200 * a)))
                d.text(((W - lw) / 2, yy), txt, font=fl, fill=(255, 255, 255, int(255 * a)))
                yy += fl.size + 26

    def caption(self, fr, b: Beat, t):
        words = b.words
        if not words or t < words[0][1] - 0.05:
            return
        groups, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= 4 or w[0].endswith((".", ",", ":", "?", "!")):
                groups.append(cur)
                cur = []
        if cur:
            groups.append(cur)
        gi = max([i for i, g in enumerate(groups) if t >= g[0][1] - 0.05] or [0])
        g = groups[gi]
        active = sum(1 for w in g if t >= w[1])
        key = (id(b), gi, active)
        if key not in self.cap_cache:
            f = font("black", 64)
            img = Image.new("RGBA", (1000, 170), (0, 0, 0, 0))
            dd = ImageDraw.Draw(img)
            lines = wrap_words([w[0] for w in g], f, 960)
            k = 0
            for li, line in enumerate(lines[:2]):
                lw = f.getlength(" ".join(line))
                x = (1000 - lw) / 2
                for w in line:
                    hl = _is_hl(w, self.tl.highlight)
                    col = C["red"] if hl and k < active else (C["white"] if k < active else (175, 175, 185, 255))
                    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 4)):
                        dd.text((x + dx, li * 80 + dy), w, font=f, fill=(0, 0, 0, 230))
                    dd.text((x, li * 80), w, font=f, fill=col)
                    x += f.getlength(w + " ")
                    k += 1
            self.cap_cache[key] = img
        fr.alpha_composite(self.cap_cache[key], (40, 1290))

    def sources(self, fr):
        f = font("med", 26)
        ImageDraw.Draw(fr).text((52, 1468), "Quelle: " + " · ".join(self.tl.sources[:3]), font=f,
                                fill=(200, 200, 210, 230))

    def _frame(self, t):
        fr = Image.new("RGBA", (W, H), C["bg"])
        tl = self.tl
        self.background(fr, t)
        self.top(fr)
        beat = next((b for b in tl.beats if b.start <= t < b.end), tl.beats[-1])
        if t < tl.hook_end:
            self.hook(fr, t)
        else:
            self.data_card(fr, beat, t)
        self.caption(fr, beat, t)
        self.sources(fr)
        # seamless loop: the hook words fade back in during the last 0.35 s
        if t > tl.total - 0.35:
            self.hook(fr, 1.0, alpha=ease((t - (tl.total - 0.35)) / 0.35))
        return fr.convert("RGB")

    def frame(self, t):
        try:
            img = self._frame(t)
        except Exception as e:
            print(f"  frame {t:.2f}s fallback: {e}")
            self.tl.photos = []
            try:
                img = self._frame(t)
            except Exception:
                img = self.last or Image.new("RGB", (W, H), C["bg"][:3])
        self.last = img
        return img


def render_single(tl: SingleTimeline, audio_wav: Path, out: Path, preview_dir: Path | None = None,
                  thumb: Path | None = None) -> Path:
    vc = settings()["video"]
    r = SingleRenderer(tl)
    fps = vc["fps"]
    n = int(round(tl.total * fps))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-i", str(audio_wav), "-c:v", "libx264", "-preset", vc["preset"], "-crf", str(vc["crf"]),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac",
           "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", "-metadata", "title=Eilblick Fokus",
           "-metadata", "language=deu", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    preview_at = {0, int(n * 0.15), int(n * 0.4), int(n * 0.65), n - 5}
    for i in range(n):
        img = r.frame(i / fps)
        if i == 0 and thumb is not None:
            img.save(thumb, "JPEG", quality=90, optimize=True)
        if preview_dir is not None and i in preview_at:
            img.save(preview_dir / f"preview_{i:04d}.jpg", quality=88)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
