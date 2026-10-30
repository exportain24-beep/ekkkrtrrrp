"""Eilblick orchestrator.

  python -m eilblick run                # auto: detect current Berlin slot, build, upload
  python -m eilblick run --slot mittag  # force a slot
  python -m eilblick run --no-upload    # build only (video lands in out/)
  python -m eilblick demo               # offline test render, no API keys needed
  python -m eilblick check-feeds        # which news feeds answer right now
  python -m eilblick check-tokens       # verify YouTube / Facebook / ElevenLabs / Anthropic keys
  python -m eilblick post-comments      # post due first comments on published videos
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import audio as A
from . import images, state, tts
from .config import ROOT, TMP, settings
from .render import StoryClip, Timeline, render_video
from .slots import current_slot, german_date, now_berlin, slot_by_id

OUT = ROOT / "out"


def log(msg: str) -> None:
    print(msg, flush=True)


def summary(md: str) -> None:
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(md + "\n")


# ------------------------------------------------------------------ helpers
def speed_up(seg: tts.Segment, factor: float) -> tts.Segment:
    src = TMP / "speed_in.f32"
    src.write_bytes(seg.audio.astype(np.float32).tobytes())
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(tts.SR), "-ac", "1", "-i", str(src),
         "-filter:a", f"atempo={factor:.4f}", "-f", "f32le", "-ar", str(tts.SR), "-ac", "1", "-"],
        check=True, capture_output=True).stdout
    words = [(w, s / factor, e / factor) for w, s, e in seg.words]
    return tts.Segment(seg.text, np.frombuffer(raw, dtype=np.float32).copy(), words)


def build_timeline(plan, slot, slot_time, intro_seg, segs, photos, stories) -> tuple[Timeline, list, list]:
    t = 0.5
    voice_spans = [(t, intro_seg.audio)]
    sfx = [("swoop", 0.0)]
    t += intro_seg.duration + 0.3
    intro_end = t
    clips = []
    per = settings()["video"]["seconds_per_image"]
    n = len(segs)
    for i, (seg, ps, ph, st) in enumerate(zip(segs, plan["stories"], photos, stories)):
        start = t
        vstart = start + 0.35
        end = vstart + seg.duration + 0.3
        voice_spans.append((vstart, seg.audio))
        sfx.append(("whoosh", max(0, start - 0.25)))
        k = 1
        while ph and start + k * per < end - 0.4:
            sfx.append(("beep", start + k * per - 0.15))
            k += 1
        clips.append(StoryClip(
            start=start, end=end, voice_start=vstart,
            words=[(w, vstart + s, vstart + e) for w, s, e in seg.words],
            photos=ph, kicker=ps["kicker"].upper()[:20], headline=ps["headline"],
            highlight=ps.get("highlight", []), pillar=ps.get("pillar", "NACHRICHTEN"),
            sources=st.outlets, index=i + 1, total=n,
        ))
        t = end
    end_start = t
    sfx.append(("whoosh", end_start - 0.25))
    sfx.append(("sting", end_start + 0.05))
    total = end_start + 1.4
    first = plan["stories"][0]
    tl = Timeline(
        total=total, intro_end=intro_end, end_start=end_start,
        hook_text=plan.get("hook_text") or first["headline"],
        hook_highlight=first.get("highlight", []),
        date_text=german_date(slot_time), slot_label=slot["label"], clock=slot["time"],
        stories=clips, ticker=[s["headline"] for s in plan["stories"]] + [settings()["channel"]["slogan"]],
    )
    return tl, voice_spans, sfx


def make_video(plan, slot, slot_time, stories, photos, offline_voice=False) -> tuple[Path, Timeline]:
    cfg = settings()
    intro_text = f"Eilblick. Die Schlagzeilen {slot['label']}."
    texts = [intro_text] + [s["voice"] for s in plan["stories"]]
    log("• Voice-over (ElevenLabs)…" if not offline_voice else "• Voice-over (offline stand-in)…")
    segs = tts.voice_all(texts, offline=offline_voice)
    intro_seg, segs = segs[0], segs[1:]
    hard = cfg["editorial"]["hard_max_seconds"]
    for _ in range(3):
        tl, spans, sfx = build_timeline(plan, slot, slot_time, intro_seg, segs, photos, stories)
        if tl.total <= hard:
            break
        voice_total = intro_seg.duration + sum(s.duration for s in segs)
        factor = voice_total / max(1.0, voice_total - (tl.total - hard) - 0.3)
        if factor <= 1.15:
            log(f"  {tl.total:.1f}s > {hard}s → tightening voice ×{factor:.3f}")
            intro_seg = speed_up(intro_seg, factor)
            segs = [speed_up(s, factor) for s in segs]
        else:
            log(f"  {tl.total:.1f}s > {hard}s → dropping last headline")
            plan["stories"] = plan["stories"][:-1]
            segs, photos, stories = segs[:-1], photos[:-1], stories[:-1]
    log(f"• Timeline {tl.total:.1f}s, {len(tl.stories)} headlines")
    mix = A.mix(tl.total, spans, sfx, cfg["audio"])
    wav = TMP / "mix.wav"
    A.write_wav(wav, mix)
    OUT.mkdir(exist_ok=True)
    stamp = slot_time.strftime("%Y-%m-%d") + "_" + slot["id"]
    out = OUT / f"eilblick_{stamp}.mp4"
    prev = OUT / "preview"
    prev.mkdir(exist_ok=True)
    t0 = time.time()
    log("• Rendering video…")
    render_video(tl, wav, out, prev)
    log(f"  rendered in {time.time()-t0:.0f}s → {out.name} ({out.stat().st_size/1e6:.1f} MB)")
    return out, tl


def _retry(fn, tries=3, wait=20):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            log(f"  attempt {i+1}/{tries} failed: {e}")
            if i + 1 == tries:
                raise
            time.sleep(wait * (i + 1))


# ------------------------------------------------------------------ commands
def cmd_post_comments() -> None:
    from . import upload_facebook as FB
    from . import upload_youtube as YT
    data = state.load()
    now = datetime.now(timezone.utc).isoformat()
    changed = False
    for r in data["runs"]:
        c = r.get("comment")
        if not c or c.get("done") or r.get("publish_at", "9") > now:
            continue
        try:
            if r.get("youtube_id") and not c.get("yt"):
                c["yt"] = YT.comment(r["youtube_id"], c["text"])
            if r.get("facebook_id") and not c.get("fb"):
                c["fb"] = FB.comment(r["facebook_id"], c["text"])
            c["done"] = True
            changed = True
            log(f"  comment posted for {r['date']} {r['slot']}")
        except Exception as e:
            log(f"  comment pending ({r['date']} {r['slot']}): {e}")
    if changed:
        state.save(data)


def cmd_run(args) -> int:
    from . import editor, feeds, seo
    cfg = settings()
    if args.slot:
        slot, slot_time = slot_by_id(args.slot)
    else:
        found = current_slot()
        if not found:
            log(f"No slot in the build window right now ({now_berlin():%H:%M} Berlin) – only posting due comments.")
            if not args.no_upload:
                try:
                    cmd_post_comments()
                except Exception as e:
                    log(f"  (comments skipped: {e})")
            return 0
        slot, slot_time = found
    date = slot_time.strftime("%Y-%m-%d")
    log(f"=== EILBLICK {slot['id']} · {german_date(slot_time)} {slot['time']} Berlin ===")
    if state.slot_done(date, slot["id"]) and not args.force:
        log("Slot already published – skipping (use --force to rebuild).")
        return 0

    images.reset_tmp()
    if not args.no_upload:
        try:
            cmd_post_comments()
        except Exception as e:
            log(f"  (comments skipped: {e})")

    log("• Collecting news…")
    stories = feeds.gather(cfg["editorial"])
    if len(stories) < cfg["editorial"]["stories_per_short"]:
        raise RuntimeError(f"Only {len(stories)} verified stories – not enough for a Short.")
    already = [s["headline"] for s in state.recent_titles(cfg["editorial"]["dedupe_days"])]
    log("• Editorial desk (selection + German script + SEO)…")
    plan = editor.plan_short(stories, slot, slot_time, already)
    cands = plan.pop("_candidates")
    chosen = [cands[s["candidate_id"]] for s in plan["stories"]]
    for i, s in enumerate(plan["stories"]):
        log(f"  {i+1}. [{s['region']}/{s['pillar']}] {s['headline']}  ←  {', '.join(chosen[i].outlets[:4])}")

    log("• Collecting news photos into temporary folder…")
    photos = images.collect(chosen, plan["stories"])

    video, tl = make_video(plan, slot, slot_time, chosen, photos)
    chosen = chosen[:len(plan["stories"])]
    credits = [p.credit for ph in photos[:len(plan["stories"])] for p in ph]
    srcs = list(dict.fromkeys(o for s in chosen for o in s.outlets))
    title, desc, tags = seo.youtube_meta(plan, credits, srcs)
    fb_caption = seo.facebook_caption(plan)
    meta = {"title": title, "description": desc, "tags": tags, "facebook": fb_caption,
            "plan": plan, "duration": round(tl.total, 1)}
    (OUT / f"{video.stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    entry = {"date": date, "slot": slot["id"], "publish_at": slot_time.astimezone(timezone.utc).isoformat(),
             "title": title, "duration": round(tl.total, 1),
             "stories": [{"headline": s["headline"], "region": s["region"], "pillar": s["pillar"]}
                         for s in plan["stories"]],
             "comment": {"text": plan.get("comment_question", ""), "done": not plan.get("comment_question")}}
    errors = []
    if not args.no_upload:
        from . import upload_facebook as FB
        from . import upload_youtube as YT
        if cfg["youtube"]["enabled"]:
            try:
                entry["youtube_id"] = _retry(lambda: YT.upload(
                    video, title, desc, tags, slot_time, slot.get("notify_subscribers", True)))
            except Exception as e:
                errors.append(f"YouTube: {e}")
        if cfg["facebook"]["enabled"]:
            try:
                entry["facebook_id"] = _retry(lambda: FB.upload(video, fb_caption, slot_time))
            except Exception as e:
                errors.append(f"Facebook: {e}")
        if not cfg["youtube"]["post_first_comment"]:
            entry["comment"]["done"] = True
        if entry.get("youtube_id") or entry.get("facebook_id"):
            state.record(entry)
    images.cleanup_tmp()   # news photos deleted right after upload
    log("• Temporary photo folder deleted.")

    summary(f"## Eilblick {slot['id']} – {german_date(slot_time)} {slot['time']}\n"
            f"**{title}** ({tl.total:.1f}s)\n\n" +
            "\n".join(f"{i+1}. {s['headline']}" for i, s in enumerate(plan["stories"])) +
            (f"\n\nYouTube: https://youtube.com/shorts/{entry['youtube_id']}" if entry.get("youtube_id") else "") +
            (f"\n\nFacebook reel id: {entry['facebook_id']}" if entry.get("facebook_id") else "") +
            ("\n\n**Errors:** " + "; ".join(errors) if errors else ""))
    if errors:
        log("ERRORS: " + " | ".join(errors))
        return 1
    return 0


def cmd_check_feeds() -> int:
    from . import feeds
    arts, status = feeds.fetch_all(verbose=True)
    trends = feeds.fetch_trends()
    log(f"\n{sum(1 for v in status.values() if v.startswith('ok'))}/{len(status)} feeds OK, "
        f"{len(arts)} articles, {len(trends)} Google-Trends terms")
    stories = feeds.gather(settings()["editorial"], verbose=False)
    for s in stories[:15]:
        log(f"  {s.score:5.1f}  [{','.join(sorted(s.regions))}] ({len(s.outlets)}) {s.lead.title[:90]}")
    summary("## Feed check\n" + "\n".join(f"- {k}: {v}" for k, v in status.items()))
    return 0


def cmd_check_tokens() -> int:
    import requests
    from .config import env
    ok = True
    try:
        from .upload_youtube import access_token
        tok = access_token()
        ch = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=30).json()
        log("YouTube ✓ " + ", ".join(i["snippet"]["title"] for i in ch.get("items", [])))
    except Exception as e:
        ok = False
        log(f"YouTube ✗ {e}")
    try:
        from .upload_facebook import check_token
        info = check_token()
        log(f"Facebook ✓ page: {info['me'].get('name')} ({info['me'].get('id')}) scopes: {info['token'].get('scopes')}")
    except Exception as e:
        ok = False
        log(f"Facebook ✗ {e}")
    try:
        r = requests.get("https://api.elevenlabs.io/v1/voices/" + settings()["voice"]["voice_id"],
                         headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, timeout=30)
        r.raise_for_status()
        log(f"ElevenLabs ✓ voice: {r.json().get('name')}")
    except Exception as e:
        ok = False
        log(f"ElevenLabs ✗ {e}")
    try:
        r = requests.get("https://api.anthropic.com/v1/models", headers={
            "x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}, timeout=30)
        r.raise_for_status()
        log("Anthropic ✓ key valid")
    except Exception as e:
        ok = False
        log(f"Anthropic ✗ {e}")
    return 0 if ok else 1


def cmd_demo(args) -> int:
    from .demo import demo_inputs
    slot, slot_time = slot_by_id(args.slot or "morgen")
    images.reset_tmp()
    plan, stories, photos = demo_inputs()
    video, tl = make_video(plan, slot, slot_time, stories, photos, offline_voice=not args.real_voice)
    log(f"Demo ready: {video}  ({tl.total:.1f}s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eilblick")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--slot")
    r.add_argument("--force", action="store_true")
    r.add_argument("--no-upload", action="store_true")
    d = sub.add_parser("demo")
    d.add_argument("--slot")
    d.add_argument("--real-voice", action="store_true")
    sub.add_parser("check-feeds")
    sub.add_parser("check-tokens")
    sub.add_parser("post-comments")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return cmd_run(a)
    if a.cmd == "demo":
        return cmd_demo(a)
    if a.cmd == "check-feeds":
        return cmd_check_feeds()
    if a.cmd == "check-tokens":
        return cmd_check_tokens()
    if a.cmd == "post-comments":
        cmd_post_comments()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
