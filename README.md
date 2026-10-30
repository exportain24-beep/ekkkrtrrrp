# EILBLICK — Kompakt. Direkt. Auf den Punkt.

Fully automated German news-headline Shorts for **YouTube Shorts + Facebook Reels** (DACH region first).

- 4 Shorts per day at **07:30 · 12:30 · 17:30 · 20:45** (Berlin), 40–50 s each (hard cap 50 s)
- 4 hot headlines per Short, each verified by ≥ 2 trusted outlets, at least 3 from DE / AT / CH / EU
- Real news photos from the outlets' own articles → temporary folder → deleted after upload
- ElevenLabs German news voice, channel signature sound bed with auto-ducking, broadcast graphics
- 100 % Hochdeutsch metadata, triple-layer SEO (voice · on-screen text · title/description/tags)

**Setup guide (Bangla): [docs/SETUP_BN.md](docs/SETUP_BN.md)**

```bash
pip install -r requirements.txt
python -m eilblick demo              # offline layout test, no keys needed
python -m eilblick check-feeds       # live feed + hot-story check
python -m eilblick run --no-upload   # full build of the current slot without uploading
```
