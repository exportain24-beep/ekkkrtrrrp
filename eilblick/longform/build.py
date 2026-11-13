"""Build + publish one EILBLICK FOKUS episode.

  python -m eilblick.longform validate longform/2026-11-14
  python -m eilblick.longform run      longform/2026-11-14 [--no-upload] [--offline]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageOps

from .. import tts
from ..audio import SR, write_wav
from ..config import ROOT, TMP, settings
from . import episode as E
from . import render16 as R
from .sound import mix

BERLIN = ZoneInfo("Europe/Berlin")
CHAPTER_CARD, TITLE_CARD, END_CARD = 2.6, 3.6, 5.0
GAP = 0.35


def log(m: str) -> None:
    print(m, flush=True)


# ------------------------------------------------------------------ photos (temporary folder)
def fetch_photos(ep: dict, offline: bool) -> tuple[dict, list[dict]]:
    from ..images import _download, commons_images, page_images
    d = TMP / "longform"
    d.mkdir(parents=True, exist_ok=True)
    out, meta = {}, []
    for k, p in enumerate(ep["photos"]):
        img = None
        if offline:
            img = _placeholder(k)
            used = "offline"
        else:
            cands = []          # (url, credit)
            if p.get("url"):
                cands.append((p["url"], p["credit"]))
            if p.get("page"):
                cands += [(u, p["credit"]) for u in page_images(p["page"])[:2]]
            if p.get("commons"):
                cands += commons_images(p["commons"], 3)
            used = ""
            for u, cr in cands:
                got = _download(u, d / f"{p['id']}.jpg", 900)
                if got:
                    img, used = got[0], u
                    p["credit"] = cr      # outlet credit, or real author + licence from the Commons API
                    break
        if img is None:
            log(f"  ! photo {p['id']} failed – will be replaced")
            continue
        img = ImageOps.exif_transpose(img).convert("RGB")
        if img.width > 2400:
            img = img.resize((2400, int(img.height * 2400 / img.width)), Image.LANCZOS)
        out[p["id"]] = (img, p["credit"])
        meta.append({"id": p["id"], "credit": p["credit"], "license": p.get("license", ""),
                     "source_url": p.get("source_url") or p.get("page") or used, "image_url": used})
    if len(out) < max(6, len(ep["photos"]) // 2):
        raise RuntimeError(f"only {len(out)} of {len(ep['photos'])} photos could be loaded")
    # replace missing ids by working ones (round robin) so no scene breaks
    ok = list(out)
    for k, p in enumerate(ep["photos"]):
        if p["id"] not in out:
            out[p["id"]] = out[ok[k % len(ok)]]
    return out, meta


def _placeholder(k: int) -> Image.Image:
    rng = np.random.default_rng(k)
    a = np.zeros((900, 1600, 3), dtype=np.float32)
    c1, c2 = rng.integers(30, 200, 3), rng.integers(30, 200, 3)
    g = np.linspace(0, 1, 1600)[None, :, None]
    a[:] = c1 * (1 - g) + c2 * g
    a += rng.normal(0, 8, a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for i in range(6):
        x, y = rng.integers(0, 1500), rng.integers(0, 800)
        d.ellipse([x, y, x + 300, y + 300], outline=(255, 255, 255), width=6)
    d.text((60, 60), f"TESTFOTO {k + 1}", fill=(255, 255, 255), font=R.font("black", 110))
    return im


# ------------------------------------------------------------------ timeline
def split_visuals(sc: dict, dur: float) -> list[tuple[float, dict]]:
    """Expand a scene's visuals into pieces of ~4–6 s (photo lists become one piece per photo)."""
    raw = []
    for v in E.visuals(sc):
        if v["type"] == "photo" and len(v["photos"]) > 1:
            for k in range(len(v["photos"])):
                vv = dict(v, _k=k)
                if k:   # headline/lower third only on the first photo of the list
                    vv.pop("lower_third", None)
                raw.append(vv)
        else:
            raw.append(dict(v))
    weights = [1.3 if v["type"] in ("bars", "timeline", "compare", "quote") else 1.0 for v in raw]
    tot = sum(weights)
    pieces = [[dur * w / tot, v] for w, v in zip(weights, raw)]
    # too long single pieces → split photos again (different crop/motion) so the picture changes ≤ 6.5 s
    out = []
    for d, v in pieces:
        if v["type"] == "photo" and d > 6.5:
            n = int(np.ceil(d / 5.5))
            for k in range(n):
                vv = dict(v, _k=v.get("_k", 0) + k)
                if k:
                    vv.pop("lower_third", None)
                    vv["layout"] = ["framed", "full"][k % 2] if not v.get("layout") else v["layout"]
                out.append((d / n, vv))
        else:
            out.append((d, v))
    return out


def build(ep: dict, offline: bool, work: Path) -> tuple[R.Doc, Path, list, list]:
    photos, meta = fetch_photos(ep, offline)
    texts = [s["voice"].strip() for s in E.all_scenes(ep)]
    log(f"  voice: {len(texts)} scenes, {sum(len(t) for t in texts)} characters")
    segs = tts.voice_all(texts, offline=offline)
    speed = settings().get("longform", {}).get("speed", 1.0)
    if abs(speed - 1.0) > 0.01:
        from ..main import speed_up
        segs = [speed_up(s, speed) for s in segs]
    pieces, spans, events, words = [], [], [], []
    acts: list[tuple[float, float, str]] = []
    t, si, idx = 0.0, 0, 0

    def add_scene(sc, act):
        nonlocal t, si, idx
        seg = segs[si]
        si += 1
        dur = seg.duration + GAP
        spans.append((t + 0.1, seg.audio))
        words.extend((w, t + 0.1 + a, t + 0.1 + b) for w, a, b in seg.words)
        for d, v in split_visuals(sc, dur):
            pieces.append(R.Piece(t, d, v, idx, act))
            if v["type"] in ("bars", "counter", "timeline"):
                events.append(("beep", t + 0.2))
            idx += 1
            t += d

    for sc in ep["cold_open"]:
        add_scene(sc, -1)
    title_at = t
    pieces.append(R.Piece(t, TITLE_CARD, {"type": "_title"}, idx, -1))
    events.append(("swoop", t))
    idx += 1
    t += TITLE_CARD
    for a, act in enumerate(ep["acts"]):
        s0 = t
        pieces.append(R.Piece(t, CHAPTER_CARD, {"type": "_chapter", "n": a + 1, "title": act["title"]}, idx, a))
        events.append(("whoosh", t))
        idx += 1
        t += CHAPTER_CARD
        for sc in act["scenes"]:
            add_scene(sc, a)
        acts.append((s0, t, act["title"]))
    pieces.append(R.Piece(t, END_CARD, {"type": "_end"}, idx, 6))
    events.append(("sting", t + 0.2))
    t += END_CARD
    doc = R.Doc(total=t, pieces=pieces, acts=acts, photos=photos, title_card=ep["title_card"], words=words)
    wav = work / "audio.wav"
    write_wav(wav, mix(t, spans, events, title_at))
    return doc, wav, meta, words


# ------------------------------------------------------------------ text outputs
def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def srt(words: list) -> str:
    out, chunk = [], []

    def fmt(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    for w in words:
        chunk.append(w)
        text = " ".join(c[0] for c in chunk)
        if len(text) > 38 or w[0].endswith((".", "?", "!")) or len(chunk) >= 8:
            out.append((chunk[0][1], chunk[-1][2], text))
            chunk = []
    if chunk:
        out.append((chunk[0][1], chunk[-1][2], " ".join(c[0] for c in chunk)))
    return "\n".join(f"{i + 1}\n{fmt(a)} --> {fmt(b)}\n{t}\n" for i, (a, b, t) in enumerate(out))


def description(ep: dict, doc: R.Doc) -> str:
    ch = ["0:00 Einstieg"] + [f"{ts(s)} {title}" for s, _, title in doc.acts]
    src = "\n".join(f"• {s['outlet']}: {s['title']} – {s['url']}" for s in ep["sources"])
    credits = "; ".join(dict.fromkeys(p["credit"] for p in ep["photos"]))
    body = (f"{ep['description_intro'].strip()}\n\n"
            f"KAPITEL\n" + "\n".join(ch) + "\n\n"
            f"QUELLEN\n{src}\n\n"
            f"BILDNACHWEIS\n{credits}\n\n"
            f"EILBLICK FOKUS – jeden Tag ein Hintergrundbericht zu einem Thema, das Deutschland bewegt. "
            f"Neutral, belegt, verständlich.\n"
            f"Mehr Nachrichten: eilblick.de\n\n"
            f"Sprecherstimme KI-generiert (ElevenLabs). Recherche und Fakten aus den oben genannten Quellen.\n\n"
            + " ".join(ep["hashtags"]))
    return body[:4900]


def publish_time(ep: dict) -> datetime:
    hh, mm = map(int, ep.get("publish_berlin", settings().get("longform", {}).get("publish_berlin", "18:00")).split(":"))
    d = datetime.fromisoformat(ep["date"]).date()
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=BERLIN)


# ------------------------------------------------------------------ commands
def cmd_validate(folder: Path) -> int:
    ep = E.load(folder / "episode.json")
    err, warn = E.validate(ep)
    wc = E.word_count(ep)
    print(f"words: {wc} (≈ {wc / E.WPS / 60:.1f} min voice)")
    for w in warn:
        print("WARN ", w)
    for e in err:
        print("ERROR", e)
    print("OK" if not err else f"{len(err)} error(s)")
    return 1 if err else 0


def cmd_run(folder: Path, upload: bool, offline: bool, force: bool) -> int:
    ep = E.load(folder / "episode.json")
    err, warn = E.validate(ep)
    if err and not offline:
        for e in err:
            log("ERROR " + e)
        return 1
    res = folder / "result.md"
    if res.exists() and "YouTube:" in res.read_text() and not force:
        log("already published – use --force")
        return 0
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    work = ROOT / "out" / "longform"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        doc, wav, meta, words = build(ep, offline, work)
        log(f"  duration {doc.total / 60:.2f} min, {len(doc.pieces)} visual pieces "
            f"(Ø {doc.total / len(doc.pieces):.1f} s)")
        mp4 = R.render(doc, wav, work / f"fokus_{ep['date']}.mp4", preview_dir=work / "preview")
        thumb = R.thumbnail(doc, ep["thumbnail"], work / "thumbnail.jpg")
    finally:
        pass
    cap = srt(words)
    (work / "captions.srt").write_text(cap, encoding="utf-8")
    desc = description(ep, doc)
    (work / "description.txt").write_text(desc, encoding="utf-8")
    (folder / "photos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# EILBLICK FOKUS {ep['date']}", "", f"Titel: {ep['youtube_title']}",
             f"Dauer: {doc.total / 60:.2f} min · {len(doc.pieces)} Bildwechsel · Ø {doc.total / len(doc.pieces):.1f} s",
             f"Wörter: {E.word_count(ep)}", ""]
    vid = None
    if upload and not offline:
        from .. import upload_youtube as yt
        when = publish_time(ep)
        if when < datetime.now(timezone.utc) + timedelta(minutes=15):
            when = datetime.now(timezone.utc) + timedelta(minutes=20)
        vid = yt.upload(mp4, ep["youtube_title"], desc, ep["tags"], when, notify=True)
        lines.append(f"YouTube: https://youtu.be/{vid} (geplant {when.astimezone(BERLIN):%d.%m. %H:%M} Berlin)")
        for step, fn in (("thumbnail", lambda: yt.set_thumbnail(vid, thumb)),
                         ("captions", lambda: yt.upload_captions(vid, cap)),
                         ("comment", lambda: yt.comment(vid, ep["pinned_comment"]))):
            try:
                fn()
                lines.append(f"- {step} ✓")
            except Exception as e:
                lines.append(f"- {step} ✗ {str(e)[:160]}")
        try:
            pl_path = ROOT / "state" / "playlists.json"
            store = json.loads(pl_path.read_text()) if pl_path.exists() else {}
            defs = {"FOKUS": settings()["longform"]["playlist"]}
            store = yt.ensure_playlists(defs, store)
            pl_path.write_text(json.dumps(store, indent=1))
            yt.add_to_playlist(store["FOKUS"], vid)
            lines.append("- playlist ✓")
        except Exception as e:
            lines.append(f"- playlist ✗ {str(e)[:160]}")
        E.register(ep, vid)
    lines += ["", "## Titel-Optionen", *[f"- {x}" for x in ep["title_options"]],
              "", "## Kommentar (bitte in YouTube Studio anpinnen)", ep["pinned_comment"],
              "", "## Begleit-Short (Idee)", ep["short_hook"]]
    res.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("\n".join(lines))
    if TMP.exists():
        shutil.rmtree(TMP)     # owner rule: news photos are temporary
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eilblick.longform")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("folder")
    r = sub.add_parser("run")
    r.add_argument("folder")
    r.add_argument("--no-upload", action="store_true")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not folder.is_absolute():
        folder = ROOT / folder
    if a.cmd == "validate":
        return cmd_validate(folder)
    return cmd_run(folder, not a.no_upload, a.offline, a.force)


if __name__ == "__main__":
    sys.exit(main())
