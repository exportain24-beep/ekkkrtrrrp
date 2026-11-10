"""Collect the real news photos for each chosen story into the temporary folder.

Order of preference per story:
  1. the lead image (og:image / twitter:image / JSON-LD) of each outlet's article on that story
  2. the image attached in the RSS item itself
  3. Wikimedia Commons photos of the story's key entity (free licence) as top-up
Every image keeps its credit ("Bild: tagesschau.de") which is burned into the video.
Only images that belong to that exact news story are used — no generic stock.
"""
from __future__ import annotations

import io
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image, ImageOps

from .config import HEADERS, TMP, settings
from .feeds import Story

BAD_URL = re.compile(r"logo|placeholder|default|fallback|sprite|icon|avatar|blank|pixel|share-image-generic|og-image\.png"
                     r"|sendungsbild|screenshot|standbild|livestream|tvbild|videostill", re.I)   # no TV stills (reuse risk)


@dataclass
class Photo:
    path: Path
    credit: str
    w: int
    h: int


def reset_tmp() -> None:
    """Delete everything from the previous video, start clean."""
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)


def cleanup_tmp() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)


def _domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def page_images(url: str) -> list[str]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code >= 400:
            return []
        html = r.text[:600_000]
    except Exception:
        return []
    found = []
    for prop in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        for m in re.finditer(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']'
            rf'|<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{re.escape(prop)}["\']',
            html, re.I,
        ):
            found.append(m.group(1) or m.group(2))
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for obj in data if isinstance(data, list) else [data]:
            if not isinstance(obj, dict):
                continue
            img = obj.get("image")
            if isinstance(img, str):
                found.append(img)
            elif isinstance(img, dict) and img.get("url"):
                found.append(img["url"])
            elif isinstance(img, list):
                for x in img[:2]:
                    found.append(x if isinstance(x, str) else (x or {}).get("url", ""))
    out = []
    for u in found:
        if u:
            u = urljoin(url, u.replace("&amp;", "&"))
            if u not in out:
                out.append(u)
    return out


def commons_images(query: str, n: int = 3) -> list[tuple[str, str]]:
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": n * 2, "prop": "imageinfo",
                "iiprop": "url|extmetadata", "iiurlwidth": 1600,
            },
            headers=HEADERS, timeout=15,
        )
        pages = (r.json().get("query") or {}).get("pages", {})
    except Exception:
        return []
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        ii = (p.get("imageinfo") or [{}])[0]
        url = ii.get("thumburl") or ii.get("url")
        meta = ii.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:40]
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if url and not url.lower().endswith((".svg", ".gif")):
            out.append((url, f"Wikimedia Commons{' / ' + artist if artist else ''}{' · ' + lic if lic else ''}"))
        if len(out) >= n:
            break
    return out


def _dhash(img: Image.Image) -> int:
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def _download(url: str, dest: Path, min_w: int) -> tuple[Image.Image, int] | None:
    if BAD_URL.search(url):
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code >= 400 or len(r.content) < 12_000:
            return None
        img = Image.open(io.BytesIO(r.content))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    if w < min_w or h < min_w * 0.45 or w / h > 3.2 or h / w > 2.2:
        return None
    img.save(dest, "JPEG", quality=92)
    return img, _dhash(img)


def collect(stories: list[Story], plan_stories: list[dict]) -> list[list[Photo]]:
    vcfg = settings()["video"]
    lo, hi = vcfg["images_per_story"]
    single = len(plan_stories) == 1
    if single:   # growth 11 Nov: a 35-s FOKUS needs 5–8 different pictures (no slideshow of 2 photos)
        lo, hi = vcfg.get("images_per_story_single", [5, 8])
    result: list[list[Photo]] = []
    for k, (story, ps) in enumerate(zip(stories, plan_stories)):
        folder = TMP / f"story_{k+1}"
        folder.mkdir(parents=True, exist_ok=True)
        cand: list[tuple[str, str]] = []
        for a in story.articles:
            if a.aggregator:
                continue
            credit = _domain(a.link)
            for u in page_images(a.link)[:3 if single else 2]:
                cand.append((u, credit))
            if a.image:
                cand.append((a.image, credit))
        photos: list[Photo] = []
        hashes: list[int] = []
        used_credit: dict[str, int] = {}
        for url, credit in cand:
            if len(photos) >= hi:
                break
            if used_credit.get(credit, 0) >= (3 if single else 2):   # spread across outlets
                continue
            dest = folder / f"img_{len(photos)+1}.jpg"
            got = _download(url, dest, vcfg["min_image_width"])
            if not got:
                continue
            img, h = got
            if any(bin(h ^ o).count("1") <= 10 for o in hashes):   # near-duplicate photo
                dest.unlink(missing_ok=True)
                continue
            hashes.append(h)
            used_credit[credit] = used_credit.get(credit, 0) + 1
            photos.append(Photo(dest, credit, *img.size))
        if len(photos) < hi:   # fill up with free-licensed photos of the people/places named in the story
            for ent in (ps.get("entities") or [])[:3]:
                for url, credit in commons_images(ent, n=hi - len(photos)):
                    if len(photos) >= hi:
                        break
                    dest = folder / f"img_{len(photos)+1}.jpg"
                    got = _download(url, dest, vcfg["min_image_width"])
                    if got and not any(bin(got[1] ^ o).count("1") <= 10 for o in hashes):
                        hashes.append(got[1])
                        photos.append(Photo(dest, credit, *got[0].size))
                if len(photos) >= lo:
                    break
        print(f"  story {k+1}: {len(photos)} photos  ({', '.join(p.credit for p in photos) or 'none → graphic card'})")
        result.append(photos)
    return result
