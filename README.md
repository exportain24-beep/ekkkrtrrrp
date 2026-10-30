# EILBLICK — Kompakt. Direkt. Auf den Punkt.

Fully automated German news-headline Shorts for **YouTube Shorts + Facebook Reels** (DACH region first).

- 4 Shorts per day at **07:00 · 12:00 · 16:30 · 20:45** (Berlin), 40–50 s each (hard cap 50 s)
- 4 hot headlines per Short, each verified by ≥ 2 trusted outlets, at least 3 from DE / AT / CH / EU
- Real news photos from the outlets' own articles → temporary folder → deleted after upload
- ElevenLabs German news voice, channel signature sound bed with auto-ducking, broadcast graphics
- 100 % Hochdeutsch metadata, triple-layer SEO (voice · on-screen text · title/description/tags)

**Setup guide (Bangla): [docs/SETUP_BN.md](docs/SETUP_BN.md)**

```bash
pip install -r requirements.txt
python -m eilblick demo              # offline layout test, no keys needed
python -m eilblick candidates --slot mittag          # 1. hot verified stories → queue/
# 2. Claude (scheduled task) writes queue/<date>_<slot>/plan.json per docs/EDITOR_GUIDE.md
python -m eilblick validate-plan queue/<dir>         # 3. rule check
python -m eilblick run --queue queue/<dir>           # 4. photos, voice, render, upload, SEO
```
