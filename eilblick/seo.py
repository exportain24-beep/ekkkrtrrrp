"""Triple-layer SEO metadata (voice ASR · on-screen OCR · metadata), German only."""
from __future__ import annotations

import re

from .config import settings

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def _hashtag(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-zÄÖÜäöüß]", "", s)
    return "#" + s if s else ""


def youtube_meta(plan: dict, credits: list[str], sources: list[str]) -> tuple[str, str, list[str]]:
    ch = settings()["channel"]
    seo = settings()["seo"]
    title = plan["youtube_title"].strip()
    first_voice = " ".join(" ".join(s["voice"] for s in plan["stories"]).split()[:25])
    tags_extra = [h.strip() for h in plan.get("hashtags", []) if h.strip()]
    hashtags = seo["base_hashtags_youtube"] + [_hashtag(h.lstrip("#")).lower() for h in tags_extra][:2]
    lines = [
        first_voice + " …",
        "",
        plan.get("description_lead", ""),
        "",
        "Die Schlagzeilen:",
        *[f"{NUM[i]} {s['headline']} – {s['subline']}" for i, s in enumerate(plan["stories"])],
        "",
        f"🚨 EILBLICK – {ch['slogan']}",
        "Täglich die wichtigsten Nachrichten aus Deutschland, Österreich, der Schweiz und der Welt in unter 60 Sekunden.",
        "",
        f"🌐 Alle Hintergründe & Quellen auf unserer Webseite: {ch['website']}",
        f"👉 Folge uns auf Facebook: {ch['facebook_url']}",
        "",
        "Quellen: " + ", ".join(sources[:10]),
        "Bildnachweise: " + ", ".join(sorted(set(credits)))[:400],
        "Hinweis: Die Sprecherstimme ist KI-generiert. Jede Meldung basiert auf Berichten von mindestens zwei etablierten Medien.",
        "",
        " ".join(dict.fromkeys(hashtags))[:200],
    ]
    desc = "\n".join(lines)
    tags, total = [], 0
    for t in list(plan.get("tags", [])) + seo["base_tags"]:
        t = t.strip().replace("#", "")
        if not t or t.lower() in (x.lower() for x in tags):
            continue
        if total + len(t) + 2 > 480:
            break
        tags.append(t)
        total += len(t) + 2
    return title, desc, tags


def facebook_caption(plan: dict) -> str:
    ch = settings()["channel"]
    seo = settings()["seo"]
    extra = [_hashtag(h.lstrip("#")) for h in plan.get("hashtags", [])][:2]
    tags = seo["base_hashtags_facebook"] + [t for t in extra if t] + ["#ReelsDE"]
    lines = [
        "🚨 " + plan.get("facebook_caption_line1", plan["youtube_title"]),
        plan.get("facebook_question", ""),
        "",
        *[f"{NUM[i]} {s['headline']}" for i, s in enumerate(plan["stories"])],
        "",
        f"Eilblick – {ch['slogan']} Mehr auf {ch['website'].replace('https://', '')}",
        "",
        " ".join(list(dict.fromkeys(tags))[:6]),
    ]
    return "\n".join(lines)
