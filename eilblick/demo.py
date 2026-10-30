"""Offline demo inputs (layout test only — never uploaded)."""
from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter

from .config import TMP
from .feeds import Article, Story
from .images import Photo

PLAN = {
    "stories": [
        {"candidate_id": 0, "pillar": "POLITIK", "region": "DE", "kicker": "BERLIN",
         "headline": "Bundestag beschließt Rentenpaket", "highlight": ["Rentenpaket"],
         "voice": "Der Bundestag hat am Donnerstag das neue Rentenpaket beschlossen. Das Rentenniveau soll bis 2031 bei achtundvierzig Prozent stabil bleiben.",
         "subline": "Rentenniveau bleibt bis 2031 bei 48 Prozent", "entities": ["Bundestag"]},
        {"candidate_id": 1, "pillar": "WIRTSCHAFT", "region": "DE", "kicker": "FRANKFURT",
         "headline": "DAX springt auf Rekordhoch", "highlight": ["Rekordhoch"],
         "voice": "Der DAX hat in Frankfurt ein neues Rekordhoch erreicht. Händler verweisen auf starke Quartalszahlen der Autobauer und sinkende Energiepreise.",
         "subline": "Starke Quartalszahlen treiben den Leitindex", "entities": ["DAX"]},
        {"candidate_id": 2, "pillar": "POLITIK", "region": "AT", "kicker": "WIEN",
         "headline": "Österreich senkt Stromsteuer", "highlight": ["Stromsteuer"],
         "voice": "Österreichs Regierung senkt ab Januar die Stromsteuer. Haushalte in Wien und den Bundesländern sollen dadurch spürbar entlastet werden.",
         "subline": "Entlastung für Haushalte ab Januar", "entities": ["Wien"]},
        {"candidate_id": 3, "pillar": "WELT", "region": "EU", "kicker": "BRÜSSEL",
         "headline": "EU einigt sich auf neue Zölle", "highlight": ["Zölle"],
         "voice": "Die EU-Kommission in Brüssel hat sich mit den Mitgliedsstaaten auf neue Zölle geeinigt. Betroffen sind vor allem Importe von Stahl und Aluminium.",
         "subline": "Betroffen: Stahl und Aluminium", "entities": ["EU-Kommission"]},
    ],
    "hook_text": "Rentenpaket beschlossen",
    "youtube_title": "Rentenpaket beschlossen: Was sich jetzt für Millionen ändert 🚨",
}

PALETTES = [((40, 60, 110), (200, 160, 90)), ((20, 80, 70), (220, 220, 230)),
            ((110, 40, 40), (240, 200, 120)), ((50, 50, 60), (90, 140, 220))]


def _fake_photo(path, seed, label):
    rnd = random.Random(seed)
    a, b = PALETTES[seed % 4]
    img = Image.new("RGB", (1600, 1067), a)
    d = ImageDraw.Draw(img)
    for y in range(1067):
        k = y / 1067
        d.line([(0, y), (1600, y)], fill=tuple(int(a[i] * (1 - k) + b[i] * k) for i in range(3)))
    for _ in range(14):
        x, y, r = rnd.randint(0, 1600), rnd.randint(300, 1067), rnd.randint(60, 260)
        d.rectangle([x, y - r * 2, x + r, 1067], fill=tuple(max(0, c - 50) for c in a))
    img = img.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(img)
    d.text((60, 60), f"DEMO-FOTO {label}", fill=(255, 255, 255))
    img.save(path, quality=90)
    return Photo(path, ["tagesschau.de", "spiegel.de", "orf.at", "dw.com"][seed % 4], 1600, 1067)


def demo_inputs():
    stories, photos = [], []
    srcs = [["tagesschau", "ZDFheute", "SPIEGEL"], ["Handelsblatt", "FAZ"], ["ORF", "DER STANDARD"],
            ["Deutsche Welle", "ZEIT ONLINE", "NZZ"]]
    for i, s in enumerate(PLAN["stories"]):
        arts = [Article(o, s["region"], 1.0, s["headline"], s["voice"], "https://example.org", None) for o in srcs[i]]
        stories.append(Story(arts))
        folder = TMP / f"story_{i+1}"
        folder.mkdir(parents=True, exist_ok=True)
        n = 3 if i != 2 else 0          # story 3 tests the "no photo" graphic card
        photos.append([_fake_photo(folder / f"img_{k}.jpg", i * 3 + k, f"{i+1}.{k+1}") for k in range(n)])
    import copy
    return copy.deepcopy(PLAN), stories, photos
