# EILBLICK FOKUS – daily 16:9 documentary (6–9 min)

One investigative report per day on a long-running German problem that people are
talking about. Published on YouTube at **18:00 Berlin** (= 23:00 Dhaka in winter, 22:00 Dhaka in summer). Completely separate from the Shorts system.

## Architecture

```
FOKUS desk (Claude scheduled task, daily ~12:40 Berlin)
  1. pick topic (registry state/longform/topics.json – no repeat within 60 days)
  2. research: ≥ 8 sources from ≥ 5 outlets (web search, official data first)
  3. write longform/<date>/episode.json  (schema in eilblick/longform/episode.py)
  4. python3 -m eilblick.longform validate longform/<date>   → must print OK
  5. git push, dispatch workflow longform.yml (folder=longform/<date>)
  6. read longform/<date>/result.md, check review-fokus branch preview frames

longform.yml (GitHub Actions, own concurrency group "eilblick-longform")
  validate → photos (temp folder, Commons/article images + credits) → ElevenLabs voice
  per scene (same voice + same API key as the Shorts) → timeline → ambient bed + SFX mix
  → 1920×1080 25 fps render → 1280×720 thumbnail → SRT → description with chapters
  → YouTube upload (scheduled 18:00 Berlin) + thumbnail + captions + comment + playlist
  → photos deleted, result.md + photos.json (credits/licences) committed
```

Modules (`eilblick/longform/`):

| file | job |
|---|---|
| `episode.py` | schema, validator, topic registry |
| `build.py` | orchestration + CLI (`validate`, `run --offline/--no-upload/--force`), photos, timeline, SRT, description/chapters, upload |
| `render16.py` | 16:9 renderer: photo layouts (full Ken Burns / framed / split), bars, counter, timeline, quote, compare, statement, chapter/title/end cards, branding, chapter progress bar, credits, lower thirds, thumbnail |
| `sound.py` | documentary ambient bed (synthesised), signature at title card, whoosh/tick/sting, ducking |

## 6-act structure (≈ 1.000–1.350 words, 6½–9 min)

0. **Cold open** (25–85 words): the hardest fact or moment, then the big question.
1. **Der Auslöser** – what happened now, the newest numbers.
2. **Die Wurzeln** – history, the decisions that caused it.
3. **Warum das System scheitert** – current state, the mechanics of the failure.
4. **Was Bürger fordern – was Politik tut** – government action vs. critics (opposition,
   Rechnungshof, associations, passengers). Every side with its own words.
5. **Wie andere Länder es lösen** – Switzerland, Austria, Netherlands, Denmark … with data.
6. **Szenario 2030** – a better and a worse path, honest conclusion, one open question.

## Editorial rules

- Neutral reporter, "voice of the people": describe what people experience and demand,
  never take a party side. Quote government and critics alike.
- Every number in a scene carries a source id. Contradicting figures → say so ("Die Bahn
  hat diese Zahl nicht bestätigt").
- Check who holds an office *today* before naming them (e.g. Verkehrsminister since 29.07.2026:
  Steffen Bilger).
- Sentences ≤ 22 words, Hochdeutsch, no Amtsdeutsch. Numbers as digits with German comma.
- Quotes on screen ≤ 15 words, exact wording, with name + function.
- Visual change every 4–6 s: give photo lists of 2 photos for long scenes; ≥ 6 data graphics.
- Photos: Commons (real author + licence written automatically into photos.json and the
  description) or article lead images with outlet credit. Only photos that fit the topic.
  Never a photo of a minor.
- Title ≤ 65 chars, concrete, a number or a conflict; thumbnail 2–4 big words.
- Pinned comment: a polarising but fair question. (YouTube's API cannot pin – pin in Studio,
  or leave as first comment.)

## Topic pool (rotate categories)

Wohnen/Mieten · Deutsche Bahn · Rente · Energiepreise/Energiewende · Deindustrialisierung ·
Digitalisierung der Verwaltung · Cyberangriffe/Datenlecks · KI & Deepfakes · Social Media und
Jugend · Migration & Integration · Innere Sicherheit · Bürgergeld · Pflege · Gesundheitssystem ·
Bundeswehr · Schulen/Lehrermangel · Brücken/Infrastruktur · Bürokratie · Steuern · Inflation.

## Cost per episode

ElevenLabs ≈ 7.000–9.000 characters/day. YouTube upload ≈ 1.650 API units. Render ≈ 15–25 min on
a GitHub runner.
