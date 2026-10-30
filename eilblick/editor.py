"""AI news desk: picks the 4 hottest verified stories for the slot (DACH first),
writes the German broadcast script (Nachrichtendeutsch) and all SEO metadata.

The model only rewrites facts that are present in the supplied source texts —
it never adds facts of its own."""
from __future__ import annotations

import json
import re
from datetime import datetime

import requests

from .config import env, settings
from .feeds import Story
from .slots import german_date

API = "https://api.anthropic.com/v1/messages"

SYSTEM = """Du bist Chef vom Dienst der Nachrichtenredaktion „Eilblick“ (eilblick.de), eines seriösen
Kurznachrichten-Formats für Deutschland, Österreich und die Schweiz (DACH). Stil: wie Tagesschau-
oder ZDFheute-Sprecher – sachlich, knapp, autoritativ, 100 % Hochdeutsch (de-DE). Niemals wörtliche
Übersetzungen, kein Englisch-Denglisch außer etablierten Begriffen (z. B. KI, DAX), keine Umgangssprache,
kein Niederländisch, keine Clickbait-Lügen, keine Meinung.

HARTE REGELN
1. Verwende AUSSCHLIESSLICH Fakten aus den gelieferten Quelltexten. Erfinde keine Zahlen, Namen, Orte,
   Zitate oder Uhrzeiten. Wenn ein Detail fehlt, lass es weg.
2. Jede Meldung beantwortet in 1–2 Sätzen: WAS ist passiert, WO, WER (Namen), WANN (z. B. „am Donnerstag“,
   „in der Nacht“ – nur wenn aus der Quelle ableitbar).
3. Jeder Sprechtext beginnt mit dem zentralen Schlagwort (Person, Institution, Ort oder Zahl), damit es in
   den ersten Sekunden fällt.
4. Priorität: Nachrichten aus Deutschland, Österreich, der Schweiz und Europa. Höchstens EINE rein
   internationale Meldung pro Ausgabe – außer es gibt eine weltweit dominierende Eilmeldung.
5. Keine Gewalt-Details, kein Blut, keine Opferbeschreibungen, kein Promi-Klatsch, keine Lokalunfälle,
   keine Gerüchte. Bei Kriegs-/Konfliktthemen nur politisch-sachliche Ebene (Entscheidungen, Gespräche,
   Folgen für Europa).
6. Vermeide Meldungen, die in der Liste „bereits gesendet“ stehen – außer es gibt eine klar neue Entwicklung.
7. Gib NUR gültiges JSON zurück, ohne Markdown."""

SCHEMA_HINT = """Antwortformat (JSON):
{
  "stories": [
    {
      "candidate_id": <int>,
      "pillar": "POLITIK" | "WIRTSCHAFT" | "WELT" | "TECHNOLOGIE",
      "region": "DE" | "AT" | "CH" | "EU" | "INT",
      "kicker": "<Ort oder Bereich in GROSSBUCHSTABEN, max 18 Zeichen, z. B. BERLIN, WIEN, BRÜSSEL, DAX>",
      "headline": "<Schlagzeile, max 38 Zeichen, sehr prägnant>",
      "highlight": ["<1–2 Wörter aus der headline, die rot hervorgehoben werden>"],
      "voice": "<Sprechtext, {wmin}–{wmax} Wörter, Nachrichtendeutsch, Zahlen ausgeschrieben wie gesprochen>",
      "subline": "<Bildschirm-Zeile mit Kernfakt, max 70 Zeichen>",
      "entities": ["<wichtigste Namen/Institutionen/Orte>"]
    }
  ],
  "hook_text": "<Text für das erste Bild (Thumbnail), 3–5 Wörter, Schlagwort der ersten Meldung>",
  "youtube_title": "<55–65 Zeichen: Haupt-Schlagwort + Doppelpunkt + Fakt, max. 1 Emoji, keine Hashtags>",
  "description_lead": "<2 Sätze, enthalten die Schlagwörter aller Meldungen>",
  "tags": ["<12–15 Tags: zuerst konkrete Namen/Institutionen der Meldungen, dann Themen>"],
  "hashtags": ["<2–3 themenbezogene Hashtags ohne Leerzeichen, z. B. #bundestag>"],
  "facebook_caption_line1": "<Breaking-Schlagzeile für Facebook>",
  "facebook_question": "<offene, neutrale Diskussionsfrage auf Deutsch>",
  "comment_question": "<neutrale, aber diskussionsstarke Frage zur wichtigsten Meldung>"
}"""


def _candidates_block(stories: list[Story], now: datetime) -> str:
    lines = []
    for i, s in enumerate(stories):
        age = ""
        if s.newest:
            mins = int((now - s.newest).total_seconds() / 60)
            age = f"{mins//60}h{mins%60:02d}m alt"
        texts = []
        for a in s.articles[:4]:
            if a.aggregator:
                continue
            texts.append(f"    [{a.source}] {a.title} — {a.summary[:380]}")
        lines.append(
            f"#{i} | Quellen: {', '.join(s.outlets[:6])} ({len(s.outlets)}) | Regionen: {','.join(sorted(s.regions))}"
            f" | {age} | Trend: {', '.join(s.trend_hits) or '-'}\n" + "\n".join(texts)
        )
    return "\n\n".join(lines)


def _call(messages: list[dict]) -> str:
    cfg = settings()["editorial"]
    r = requests.post(
        API,
        headers={
            "x-api-key": env("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": cfg["llm_model"],
            "max_tokens": cfg["llm_max_tokens"],
            "system": SYSTEM,
            "messages": messages,
        },
        timeout=180,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:400]}")
    return "".join(b.get("text", "") for b in r.json()["content"])


def _parse(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def validate(plan: dict, n_candidates: int) -> list[str]:
    cfg = settings()["editorial"]
    wmin, wmax = cfg["words_per_story"]
    errs = []
    st = plan.get("stories") or []
    if not (cfg["stories_per_short"] <= len(st) <= cfg["max_stories_per_short"]):
        errs.append(f"Es müssen {cfg['stories_per_short']} Meldungen sein (geliefert: {len(st)}).")
    total = 0
    for k, s in enumerate(st):
        w = len(s.get("voice", "").split())
        total += w
        if not (wmin - 3 <= w <= wmax + 3):
            errs.append(f"Meldung {k+1}: Sprechtext hat {w} Wörter (Soll {wmin}–{wmax}).")
        if len(s.get("headline", "")) > 44:
            errs.append(f"Meldung {k+1}: headline zu lang ({len(s['headline'])} Zeichen).")
        if not isinstance(s.get("candidate_id"), int) or not (0 <= s["candidate_id"] < n_candidates):
            errs.append(f"Meldung {k+1}: ungültige candidate_id.")
    regional = sum(1 for s in st if s.get("region") in ("DE", "AT", "CH", "EU"))
    if regional < min(cfg["min_regional_stories"], len(st)):
        errs.append(f"Nur {regional} DACH/EU-Meldungen – mindestens {cfg['min_regional_stories']} nötig.")
    if total > cfg["max_total_words"] + 4:
        errs.append(f"Gesamt {total} Wörter – maximal {cfg['max_total_words']}, damit das Video unter 50 Sekunden bleibt.")
    if len(plan.get("youtube_title", "")) > 95:
        errs.append("youtube_title zu lang.")
    return errs


def plan_short(stories: list[Story], slot: dict, slot_time: datetime, already: list[str]) -> dict:
    cfg = settings()["editorial"]
    wmin, wmax = cfg["words_per_story"]
    cands = stories[:28]
    prompt = (
        f"Ausgabe: Eilblick {slot['label']} – {german_date(slot_time)}, {slot['time']} Uhr (Berliner Zeit).\n"
        f"Redaktioneller Schwerpunkt dieser Ausgabe: {slot['focus']}\n"
        f"Wähle genau {cfg['stories_per_short']} Meldungen. Reihenfolge: stärkste/heißeste Meldung zuerst.\n"
        f"Mindestens {cfg['min_regional_stories']} davon aus DE/AT/CH/EU.\n\n"
        f"Bereits gesendet (nicht wiederholen):\n- " + ("\n- ".join(already[-40:]) or "–") + "\n\n"
        f"KANDIDATEN (bereits von ≥2 Medien bestätigt, nach Relevanz sortiert):\n\n"
        f"{_candidates_block(cands, slot_time)}\n\n"
        + SCHEMA_HINT.replace("{wmin}", str(wmin)).replace("{wmax}", str(wmax))
    )
    messages = [{"role": "user", "content": prompt}]
    last_err = None
    for attempt in range(3):
        raw = _call(messages)
        try:
            plan = _parse(raw)
        except Exception as e:
            last_err = f"Kein gültiges JSON: {e}"
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": last_err + " Bitte nur gültiges JSON."}]
            continue
        errs = validate(plan, len(cands))
        if not errs:
            plan["_candidates"] = cands
            return plan
        last_err = " ".join(errs)
        print("  editor retry:", last_err)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Korrigiere bitte: " + last_err + " Gib das vollständige JSON erneut aus."}]
    raise RuntimeError(f"Editor failed: {last_err}")
