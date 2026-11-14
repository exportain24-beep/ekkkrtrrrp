"""Triple-layer SEO metadata (voice ASR · on-screen OCR · metadata), German only."""
from __future__ import annotations

import re

from .config import keywords, settings

NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]


def _hashtag(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-zÄÖÜäöüß]", "", s)
    return "#" + s if s else ""


def _body_lines(plan: dict, date_text: str) -> list[str]:
    pre = f"Nachrichten heute – {date_text}. " if date_text else ""
    if plan.get("format") == "single":
        return [pre + "Im Fokus: " + plan.get("headline", "")] + \
            [f"▶️ {b.get('big', '')} – {b.get('label', '')}" for b in plan.get("beats", [])]
    return [pre + "Die Schlagzeilen:"] + \
        [f"{NUM[i]} {s['headline']} – {s['subline']}" for i, s in enumerate(plan["stories"])]


def _plan_text(plan: dict) -> str:
    parts = [plan.get(k, "") for k in ("youtube_title", "hook_text", "hook_voice", "headline", "description_lead")]
    parts += [" ".join(map(str, plan.get(k, []))) for k in ("tags", "entities")]
    for s in plan.get("stories", []):
        parts += [s.get("headline", ""), s.get("voice", ""), " ".join(s.get("entities", []))]
    for b in plan.get("beats", []):
        parts += [str(b.get("voice", "")), str(b.get("big", "")), str(b.get("label", ""))]
    return " ".join(parts).lower()


def search_keywords(plan: dict, limit: int = 8) -> list[str]:
    """Owner keyword list: cluster keywords whose triggers occur in the plan (most specific cluster first)."""
    kw = keywords()
    text = _plan_text(plan)
    out: list[str] = []
    for name, c in (kw.get("clusters") or {}).items():
        hits = sum(1 for t in c.get("triggers", []) if t.lower() in text)
        if hits:
            specific = [w for w in c.get("keywords", [])
                        if any(tok in text for tok in re.findall(r"[a-zäöüß0-9]{3,}", w.lower()))]
            out.append((hits, name, list(c.get("generic", [])) + specific))
    out.sort(key=lambda x: -x[0])
    res: list[str] = []
    for _, _, words in out:
        n = 0
        for w in words:
            if n >= 5:                     # max 5 per cluster → several topics get covered
                break
            if w.lower() not in (r.lower() for r in res):
                res.append(w)
                n += 1
            if len(res) >= limit:
                return res
    return res


def _themes(found: list[str], n: int = 3) -> list[str]:
    """Readable topic line: no near-duplicates ("fall fabian" vs "fall fabian aktuell")."""
    out: list[str] = []
    for w in found:
        lw = w.lower()
        if any(o.lower() in lw or lw in o.lower() for o in out):
            continue
        out.append(w)
        if len(out) >= n:
            break
    return [w.title() if w.islower() else w for w in out]


def youtube_meta(plan: dict, credits: list[str], sources: list[str], date_text: str = "") -> tuple[str, str, list[str]]:
    ch = settings()["channel"]
    seo = settings()["seo"]
    title = plan["youtube_title"].strip()
    first_voice = " ".join(" ".join(s["voice"] for s in plan["stories"]).split()[:25])
    tags_extra = [h.strip() for h in plan.get("hashtags", []) if h.strip()]
    hashtags = seo["base_hashtags_youtube"] + [_hashtag(h.lstrip("#")).lower() for h in tags_extra][:2]
    found = search_keywords(plan)
    lines = [
        first_voice + " …",
        "",
        plan.get("description_lead", ""),
        *(["Themen: " + " · ".join(_themes(found))] if found else []),
        "",
        *_body_lines(plan, date_text),
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
    date_tag = []
    if date_text and "," in date_text:
        dm = date_text.split(",", 1)[1].strip()          # "31. Oktober 2026"
        date_tag = [f"Nachrichten {dm}", f"News {dm.rsplit(' ', 1)[0]}"]
    evergreen = list((keywords().get("evergreen") or []))[:4]
    for t in list(plan.get("tags", [])) + found + date_tag + evergreen + seo["base_tags"]:
        t = t.strip().replace("#", "")
        if not t or t.lower() in (x.lower() for x in tags):
            continue
        if total + len(t) + 2 > 480:
            break
        tags.append(t)
        total += len(t) + 2
    return title, desc, tags


def facebook_caption(plan: dict) -> str:
    """Facebook caption – NEVER contains a website or any link (owner rule)."""
    ch = settings()["channel"]
    seo = settings()["seo"]
    extra = [_hashtag(h.lstrip("#")) for h in plan.get("hashtags", [])][:2]
    tags = seo["base_hashtags_facebook"] + [t for t in extra if t] + ["#ReelsDE"]
    lines = [
        "🚨 " + plan.get("facebook_caption_line1", plan["youtube_title"]),
        plan.get("facebook_question", ""),
        "",
        *([f"{NUM[i]} {s['headline']}" for i, s in enumerate(plan["stories"])] if plan.get("format") != "single"
          else [f"▶️ {b.get('big', '')} – {b.get('label', '')}" for b in plan.get("beats", [])]),
        "",
        f"Eilblick – {ch['slogan']}",   # owner rule: never a website/link in the Facebook caption
        "",
        " ".join(list(dict.fromkeys(tags))[:6]),
    ]
    return strip_links("\n".join(lines))


_LINK = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(de|com|net|org|at|ch|io)\b)", re.I)


def strip_links(text: str) -> str:
    out = []
    for line in text.splitlines():
        line = _LINK.sub("", line)
        line = re.sub(r"[–-]?\s*(mehr|alles|infos?|details)\s+(auf|unter|bei)\s*[:.]?\s*$", "", line, flags=re.I)
        out.append(re.sub(r"\s{2,}", " ", line).strip())
    return "\n".join(out)



def tiktok_caption(plan: dict) -> str:
    """TikTok: hook line + question + 4–6 hashtags, German, no links."""
    tags = ["#nachrichten", "#deutschland", "#news", "#eilblick"] + \
        [_hashtag(h.lstrip("#")).lower() for h in plan.get("hashtags", [])][:2]
    lines = ["🚨 " + plan.get("facebook_caption_line1", plan["youtube_title"]),
             plan.get("facebook_question", ""), "", " ".join(dict.fromkeys(t for t in tags if t))]
    return strip_links("\n".join(lines))[:2100]


def x_caption(plan: dict) -> str:
    """X/Twitter: ≤ 280 chars, headline + 2–3 hashtags."""
    tags = ["#Eilblick", "#Nachrichten"] + [_hashtag(h.lstrip("#")) for h in plan.get("hashtags", [])][:1]
    head = "🚨 " + plan["youtube_title"].strip()
    tail = "\n\n" + " ".join(t for t in tags if t)
    return (head[: 280 - len(tail)] + tail)[:280]
