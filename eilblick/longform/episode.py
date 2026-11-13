"""episode.json schema + validator (the research desk writes it, this checks it).

{
  "date": "2026-11-14", "publish_berlin": "18:00",
  "topic": "deutsche-bahn",                 # registry key – no repeat within 60 days
  "title_options": ["…", "…", "…"],         # 3 titles, each ≤ 65 chars
  "youtube_title": "…",                     # one of the three
  "title_card": {"kicker": "HINTERGRUND", "title": "Warum die Bahn nicht pünktlich wird"},
  "thumbnail": {"words": "BAHN AM LIMIT", "highlight": ["LIMIT"], "sub": "Was wirklich schiefläuft", "photo": "p1"},
  "description_intro": "2–3 Sätze",
  "tags": [15–20], "hashtags": ["#…", 3–5],
  "pinned_comment": "polarisierende Frage", "short_hook": "Idee für 30-s-Short",
  "sources": [{"id": "s1", "outlet": "tagesschau.de", "title": "…", "url": "https://…"}],
  "photos":  [{"id": "p1", "url": "https://…jpg" | "page": "https://artikel" | "commons": "Suchbegriff",
               "credit": "Bild: … / Lizenz", "license": "CC BY-SA 4.0", "source_url": "…"}],
  "cold_open": [scene, …],                  # 15–30 s hook before the title card
  "acts": [ {"title": "Der Auslöser", "scenes": [scene, …]}, × 6 ],
}
scene = {"voice": "Sprechertext", "sources": ["s1"], "visual": visual | [visual, …]}
visual types:
  photo     {"type":"photo","photos":["p1","p2"],"headline":"…","lower_third":{"name":"…","role":"…"}}
  bars      {"type":"bars","title":"…","unit":"%","items":[["2015",71.8],["2025",62.5]],"source":"DB"}
  counter   {"type":"counter","value":13.5,"decimals":1,"prefix":"","suffix":" Mrd. €","label":"…","source":"…"}
  timeline  {"type":"timeline","title":"…","events":[["1994","Bahnreform"],["2024","Generalsanierung"]]}
  quote     {"type":"quote","text":"…","who":"Name, Funktion","photo":"p3"}
  compare   {"type":"compare","title":"…","left":{"label":"Deutschland","value":"62 %","photo":"p4"},
                                        "right":{"label":"Schweiz","value":"92 %","photo":"p5"}}
  statement {"type":"statement","text":"…","highlight":["Wort"]}
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from ..config import ROOT

TYPES = {"photo", "bars", "counter", "timeline", "quote", "compare", "statement"}
REGISTRY = ROOT / "state" / "longform" / "topics.json"
WPS = 2.55          # ElevenLabs German at speed ~1.0: ≈ 2.5–2.6 words per second


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def visuals(scene: dict) -> list[dict]:
    v = scene.get("visual") or []
    return v if isinstance(v, list) else [v]


def all_scenes(ep: dict) -> list[dict]:
    out = list(ep.get("cold_open", []))
    for a in ep.get("acts", []):
        out += a.get("scenes", [])
    return out


def word_count(ep: dict) -> int:
    return sum(len(s.get("voice", "").split()) for s in all_scenes(ep))


def registry() -> dict:
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def register(ep: dict, video_id: str | None) -> None:
    reg = registry()
    reg[ep["topic"]] = {"date": ep["date"], "title": ep.get("youtube_title"), "video": video_id}
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def validate(ep: dict) -> tuple[list[str], list[str]]:
    err, warn = [], []
    req = ["date", "topic", "title_options", "youtube_title", "title_card", "thumbnail", "description_intro",
           "tags", "hashtags", "pinned_comment", "short_hook", "sources", "photos", "cold_open", "acts"]
    for k in req:
        if not ep.get(k):
            err.append(f"missing field: {k}")
    if err:
        return err, warn
    # --- titles / SEO
    if len(ep["title_options"]) != 3:
        err.append("title_options must contain exactly 3 titles")
    for t in ep["title_options"] + [ep["youtube_title"]]:
        if len(t) > 65:
            err.append(f"title > 65 chars ({len(t)}): {t}")
    if ep["youtube_title"] not in ep["title_options"]:
        warn.append("youtube_title is not one of title_options")
    if not 15 <= len(ep["tags"]) <= 20:
        err.append(f"tags: need 15–20, got {len(ep['tags'])}")
    if not 3 <= len(ep["hashtags"]) <= 5 or not all(h.startswith("#") for h in ep["hashtags"]):
        err.append("hashtags: need 3–5, each starting with #")
    tw = ep["thumbnail"].get("words", "").split()
    if not 2 <= len(tw) <= 4:
        err.append("thumbnail.words: 2–4 words")
    # --- sources
    src = {s.get("id"): s for s in ep["sources"]}
    outlets = {re.sub(r"^www\.", "", s.get("outlet", "").lower()) for s in ep["sources"]}
    if len(src) < 8:
        err.append(f"sources: need ≥ 8, got {len(src)}")
    if len(outlets) < 5:
        err.append(f"sources: need ≥ 5 different outlets, got {len(outlets)}")
    for s in ep["sources"]:
        if not str(s.get("url", "")).startswith("http"):
            err.append(f"source {s.get('id')} has no URL")
    # --- photos
    ph = {p.get("id"): p for p in ep["photos"]}
    if len(ph) < 12:
        err.append(f"photos: need ≥ 12 different photos, got {len(ph)}")
    for p in ep["photos"]:
        if not (p.get("url") or p.get("page") or p.get("commons")):
            err.append(f"photo {p.get('id')}: needs url, page or commons")
        if not p.get("credit"):
            err.append(f"photo {p.get('id')}: credit missing")
    if ep["thumbnail"].get("photo") not in ph:
        err.append("thumbnail.photo must reference a photo id")
    # --- structure
    if len(ep["acts"]) != 6:
        err.append(f"acts: need exactly 6, got {len(ep['acts'])}")
    wc = word_count(ep)
    if not 900 <= wc <= 1450:
        err.append(f"voice word count {wc}: need 900–1450 (≈ 6–9 min)")
    co = sum(len(s.get("voice", "").split()) for s in ep["cold_open"])
    if not 25 <= co <= 85:
        err.append(f"cold_open: {co} words, need 25–85 (10–30 s hook)")
    used_src, used_ph = set(), set()
    for n, sc in enumerate(all_scenes(ep)):
        v = sc.get("voice", "").strip()
        if not v:
            err.append(f"scene {n}: empty voice")
        for sent in re.split(r"(?<=[.!?])\s+", v):
            if len(sent.split()) > 26:
                warn.append(f"scene {n}: long sentence ({len(sent.split())} words): {sent[:60]}…")
        secs = len(v.split()) / WPS
        vs = visuals(sc)
        if not vs:
            err.append(f"scene {n}: no visual")
        for s in sc.get("sources", []):
            if s not in src:
                err.append(f"scene {n}: unknown source {s}")
            used_src.add(s)
        nph = 0
        for vis in vs:
            t = vis.get("type")
            if t not in TYPES:
                err.append(f"scene {n}: unknown visual type {t}")
                continue
            ids = list(vis.get("photos", [])) + [vis.get("photo")] + \
                [vis.get(k, {}).get("photo") for k in ("left", "right") if isinstance(vis.get(k), dict)]
            for pid in filter(None, ids):
                if pid not in ph:
                    err.append(f"scene {n}: unknown photo {pid}")
                used_ph.add(pid)
            if t == "photo":
                if not vis.get("photos"):
                    err.append(f"scene {n}: photo visual without photos")
                nph += len(vis.get("photos", []))
            if t == "bars" and not (2 <= len(vis.get("items", [])) <= 8):
                err.append(f"scene {n}: bars need 2–8 items")
            if t == "timeline" and not (2 <= len(vis.get("events", [])) <= 6):
                err.append(f"scene {n}: timeline needs 2–6 events")
            if t in ("bars", "counter") and not vis.get("source"):
                err.append(f"scene {n}: {t} needs a source label")
        # visual change every 4–6 s: one piece per ≤ 7 s of voice (photo lists are split automatically)
        pieces = sum(max(1, len(v_.get("photos", []))) if v_.get("type") == "photo" else 1 for v_ in vs)
        if secs / max(1, pieces) > 9:
            warn.append(f"scene {n}: ≈{secs:.0f}s voice but only {pieces} visual(s) – add photos/graphics")
    graphics = sum(1 for sc in all_scenes(ep) for v in visuals(sc) if v.get("type") != "photo")
    if graphics < 6:
        err.append(f"only {graphics} data graphics – need ≥ 6 (bars/counter/timeline/compare/quote)")
    if len(used_src) < 8:
        warn.append(f"only {len(used_src)} sources are cited in scenes")
    unused = set(ph) - used_ph
    if unused:
        warn.append(f"photos not used: {sorted(unused)}")
    # --- repetition
    old = registry().get(ep["topic"])
    if old:
        try:
            if date.fromisoformat(ep["date"]) - date.fromisoformat(old["date"]) < timedelta(days=60):
                err.append(f"topic '{ep['topic']}' already done on {old['date']} (60-day rule)")
        except Exception:
            pass
    return err, warn
