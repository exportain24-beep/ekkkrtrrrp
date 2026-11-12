"""Fetch trusted RSS/Atom feeds, cluster identical stories across outlets and
rank them by how "hot" they are right now.

Hotness = how many independent outlets carry the story (weighted by trust)
        + Google-Trends match + freshness + DACH-region bonus.
A story reported by only one outlet is never used (verification rule).
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from .config import HEADERS, sources

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ht": "https://trends.google.com/trending/rss",
}

STOP = set("""
aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes anders auch auf aus bei bin bis bist da damit dann
das dass dazu dein deine dem den der des dich die dies diese dieser dieses dir doch dort du durch ein eine einem einen einer eines er es etwas euch
für gegen gewesen hab habe haben hat hatte hier hin hinter ich ihm ihn ihnen ihr ihre im in ist jede jedem jeden jeder jetzt kann kein keine können
man mehr mein mit muss nach nicht nichts noch nun nur ob oder ohne sehr sein seine sich sie sind so soll sollen über um und uns unser unter vom von
vor war waren warum was weg weil weiter welche wenn wer werden wie wieder will wir wird wo zu zum zur zwischen neue neuen neuer neues heute gestern
mehr mehrere erste ersten zwei drei vier fünf jahr jahre jahren prozent laut sagt sagte soll sollen könnte wurde wurden worden seit beim ab
video live ticker news liveblog newsblog eilmeldung aktuell update deutschland deutsche deutschen deutscher
bundesregierung regierung präsident minister ministerin land länder menschen woche wochen tag tage montag dienstag
mittwoch donnerstag freitag samstag sonntag kritik experten nach unter zwischen
""".split())


@dataclass
class Article:
    source: str
    region: str
    weight: float
    title: str
    summary: str
    link: str
    published: datetime | None
    image: str | None = None
    aggregator: bool = False
    tokens: set = field(default_factory=set)


@dataclass
class Story:
    articles: list[Article]
    score: float = 0.0
    trend_hits: list[str] = field(default_factory=list)

    @property
    def outlets(self) -> list[str]:
        seen, out = set(), []
        for a in self.articles:
            key = a.source.split(" ")[0].lower()
            if key not in seen:
                seen.add(key)
                out.append(a.source)
        return out

    @property
    def lead(self) -> Article:
        return max(self.articles, key=lambda a: (a.weight, len(a.summary)))

    @property
    def newest(self) -> datetime | None:
        ds = [a.published for a in self.articles if a.published]
        return max(ds) if ds else None

    @property
    def regions(self) -> set:
        return {a.region for a in self.articles if not a.aggregator}

    def fingerprint(self) -> str:
        return " ".join(sorted(self.lead.tokens))[:300]


# ---------------------------------------------------------------- parsing
def _text(el) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def clean(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _img_from(item) -> str | None:
    for tag in ("media:content", "media:thumbnail"):
        for m in item.findall(tag, NS):
            url = m.get("url")
            if url and (m.get("medium") in (None, "image") or re.search(r"\.(jpe?g|png|webp)", url, re.I)):
                return url
    for enc in item.findall("enclosure"):
        if (enc.get("type") or "").startswith("image") and enc.get("url"):
            return enc.get("url")
    raw = (_text(item.find("description")) or "") + (_text(item.find("content:encoded", NS)) or "")
    m = re.search(r'<img[^>]+src="([^"]+)"', raw)
    return m.group(1) if m else None


def tokenize(text: str) -> set:
    words = re.findall(r"[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]{2,}", text)
    out = set()
    for w in words:
        lw = w.lower().strip("-")
        if lw in STOP or lw.isdigit() and len(lw) < 4:
            continue
        # light German stemming so "Zölle/Zöllen", "Regierung/Regierungen" match
        for suf in ("ungen", "innen", "ern", "en", "er", "es", "e", "s", "n"):
            if len(lw) > 5 and lw.endswith(suf):
                lw = lw[: -len(suf)]
                break
        out.add(lw)
    return out


def _root(xml_bytes: bytes):
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        # some feeds append junk after the closing tag – cut it off and retry
        txt = xml_bytes.decode("utf-8", "replace")
        for end in ("</rss>", "</feed>", "</rdf:RDF>"):
            i = txt.rfind(end)
            if i > 0:
                return ET.fromstring(txt[: i + len(end)].encode("utf-8"))
        raise


def parse_feed(xml_bytes: bytes, feed: dict) -> list[Article]:
    root = _root(xml_bytes)
    rss1 = "{http://purl.org/rss/1.0/}"
    items = root.findall(".//item") or root.findall(".//atom:entry", NS) or root.findall(f".//{rss1}item")
    if items and items[0].tag.startswith(rss1):   # RSS 1.0 / RDF (e.g. ORF): strip namespace
        for it in items:
            for el in it.iter():
                if el.tag.startswith(rss1):
                    el.tag = el.tag[len(rss1):]
    out = []
    for it in items:
        title = clean(_text(it.find("title")) or _text(it.find("atom:title", NS)))
        summary = clean(
            _text(it.find("description"))
            or _text(it.find("atom:summary", NS))
            or _text(it.find("atom:content", NS))
        )
        link = _text(it.find("link"))
        if not link:
            le = it.find("atom:link", NS)
            link = le.get("href") if le is not None else ""
        pub = _date(
            _text(it.find("pubDate")) or _text(it.find("dc:date", NS))
            or _text(it.find("atom:updated", NS)) or _text(it.find("atom:published", NS))
        )
        if not title or not link:
            continue
        source = feed["name"]
        if feed.get("aggregator") and " - " in title:  # Google News: "Titel - Quelle"
            title, source = title.rsplit(" - ", 1)
        a = Article(
            source=source, region=feed["region"], weight=float(feed.get("weight", 0.7)),
            title=title, summary=summary[:600], link=link.strip(), published=pub,
            image=_img_from(it), aggregator=bool(feed.get("aggregator")),
        )
        a.tokens = tokenize(a.title + " " + a.title + " " + a.summary[:140])
        out.append(a)
    return out


def fetch(url: str, timeout: int = 20) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.content


def fetch_all(verbose: bool = True) -> tuple[list[Article], dict]:
    feeds = sources()["feeds"]
    status: dict = {}

    def one(feed):
        try:
            return feed, parse_feed(fetch(feed["url"]), feed), None
        except Exception as e:  # dead feed → skip, never crash the run
            return feed, [], str(e)[:120]

    arts: list[Article] = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for feed, items, err in ex.map(one, feeds):
            status[feed["name"]] = err or f"ok ({len(items)})"
            arts.extend(items)
    if verbose:
        for k, v in status.items():
            print(f"  feed {k:24s} {v}")
    return arts, status


TREND_VOLUME: dict[str, int] = {}

# owner rule 11 Nov 2026: the most popular AND most controversial / talked-about German news first.
CONTROVERSY = ("streit", "skandal", "rücktritt", "kritik", "vorwurf", "vorwürfe", "eklat", "empörung", "wut", "protest",
               "verbot", "verbietet", "ermittl", "festnahme", "festgenommen", "razzia", "anklage", "urteil", "prozess",
               "affäre", "lüge", "streik", "warnstreik", "krise", "koalition", "misstrauen", "abschiebung", "bürgergeld",
               "rente", "steuer", "preis", "teurer", "inflation", "heizung", "migration", "grenze", "afd", "verfassungsschutz",
               "spionage", "hacker", "anschlag", "terror", "bundeswehr", "wehrpflicht", "kriegs", "putin", "trump")
PROMINENT = ("merz", "klingbeil", "söder", "weidel", "chrupalla", "wagenknecht", "habeck", "baerbock", "pistorius",
             "dobrindt", "reiche", "bas", "scholz", "steinmeier", "trump", "putin", "selenskyj", "musk", "von der leyen",
             "orbán", "macron", "papst", "aiwanger", "lindner", "linnemann", "spahn")


def fetch_trends() -> list[str]:
    url = sources().get("trends_feed")
    if not url:
        return []
    try:
        root = ET.fromstring(fetch(url))
        terms = []
        for i in root.findall(".//item"):
            # owner rule 11 Nov: weight by real search volume ("200.000+") – the biggest searches lead the list
            traffic = clean(_text(i.find("ht:approx_traffic", NS))).replace(".", "").replace(",", "").rstrip("+")
            vol = int(traffic) if traffic.isdigit() else 0
            t = clean(_text(i.find("title")))
            if t:
                terms.append((t, vol))
            for n in i.findall("ht:news_item/ht:news_item_title", NS):
                if clean(_text(n)):
                    terms.append((clean(_text(n)), vol))
        terms.sort(key=lambda x: -x[1])
        TREND_VOLUME.clear()
        TREND_VOLUME.update({t: v for t, v in terms})
        return [t for t, _ in terms]
    except Exception as e:
        print("  trends unavailable:", e)
        return []


# ---------------------------------------------------------------- clustering
def _similar(a: set, b: set) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    ratio = inter / min(len(a), len(b))
    return (inter >= 3 and ratio >= 0.3) or (inter >= 2 and ratio >= 0.55)


def cluster(arts: list[Article]) -> list[Story]:
    stories: list[Story] = []
    for a in sorted(arts, key=lambda x: -x.weight):
        for s in stories:
            # compare with the cluster's first article (no chaining → no topic drift)
            if _similar(a.tokens, s.articles[0].tokens):
                s.articles.append(a)
                break
        else:
            stories.append(Story([a]))
    return stories


def rank(stories: list[Story], trends: list[str], max_age_h: float, blocked: list[str]) -> list[Story]:
    now = datetime.now(timezone.utc)
    trend_tokens = [(t, tokenize(t)) for t in trends]
    ranked = []
    for s in stories:
        text = " ".join(a.title + " " + a.summary for a in s.articles).lower()
        if any(b in text for b in blocked):
            continue
        newest = s.newest
        age_h = (now - newest).total_seconds() / 3600 if newest else 6
        if age_h > max_age_h:
            continue
        real = [a for a in s.articles if not a.aggregator]
        outlet_score = sum({a.source.split(" ")[0]: a.weight for a in real}.values())
        agg = len({a.source for a in s.articles if a.aggregator})
        trend_hits = [t for t, tt in trend_tokens if tt and len(tt & s.lead.tokens) >= 1 and
                      (len(tt) == 1 or len(tt & s.lead.tokens) >= 2)]
        regional = bool(s.regions & {"DE", "AT", "CH", "EU"})
        s.trend_hits = trend_hits[:3]
        import math
        vol = max([TREND_VOLUME.get(t, 0) for t in trend_hits] or [0])
        trend_pts = min(len(trend_hits), 3) * 1.5 + (math.log10(vol) - 3 if vol >= 2000 else 0.0)   # 10K→+1, 100K→+2, 1M→+3
        lead_text = (s.lead.title + " " + s.lead.summary).lower()
        controversy = min(sum(1 for w in CONTROVERSY if w in lead_text), 3) * 0.5
        prominent = min(sum(1 for w in PROMINENT if w in lead_text), 2) * 0.6
        s.score = (
            outlet_score * 2.0
            + min(agg, 4) * 0.6
            + trend_pts                         # Google Trends DE: matches + real search volume
            + max(0.0, 3.0 - age_h / 3)        # freshness
            + (1.0 if regional else 0.0)
        )
        ranked.append(s)
    ranked.sort(key=lambda s: -s.score)
    return ranked


def outlet_count(s: Story) -> int:
    return len({a.source.split(" ")[0].lower() for a in s.articles})


def gather(cfg_ed: dict, verbose: bool = True) -> list[Story]:
    t0 = time.time()
    arts, _ = fetch_all(verbose)
    trends = fetch_trends()
    stories = cluster(arts)
    ranked = rank(stories, trends, cfg_ed["max_story_age_hours"], sources().get("blocked_keywords", []))
    verified = [s for s in ranked if outlet_count(s) >= cfg_ed["min_sources_for_story"]]
    if verbose:
        print(f"  {len(arts)} articles → {len(stories)} stories → {len(verified)} verified "
              f"(≥{cfg_ed['min_sources_for_story']} outlets) in {time.time()-t0:.1f}s; {len(trends)} trend terms")
    return verified


# ---------------------------------------------------------------- (de)serialisation
def story_to_dict(s: Story, idx: int) -> dict:
    return {
        "id": idx, "score": round(s.score, 2), "outlets": s.outlets, "regions": sorted(s.regions),
        "trend": s.trend_hits, "newest": s.newest.isoformat() if s.newest else None,
        "articles": [{
            "source": a.source, "region": a.region, "weight": a.weight, "title": a.title,
            "summary": a.summary, "link": a.link, "image": a.image, "aggregator": a.aggregator,
            "published": a.published.isoformat() if a.published else None,
        } for a in s.articles[:8]],
    }


def story_from_dict(d: dict) -> Story:
    arts = []
    for a in d["articles"]:
        art = Article(a["source"], a["region"], a["weight"], a["title"], a["summary"], a["link"],
                      datetime.fromisoformat(a["published"]) if a.get("published") else None,
                      a.get("image"), a.get("aggregator", False))
        art.tokens = tokenize(art.title + " " + art.summary[:200])
        arts.append(art)
    s = Story(arts, d.get("score", 0), d.get("trend", []))
    return s
