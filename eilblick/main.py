"""Eilblick orchestrator.

  python -m eilblick candidates --slot mittag    # step 1: hot verified stories → queue/<date>_<slot>/candidates.json
  (Claude writes queue/<date>_<slot>/plan.json following docs/EDITOR_GUIDE.md)
  python -m eilblick validate-plan queue/<dir>   # step 2: check the plan against all rules
  python -m eilblick run --queue queue/<dir>     # step 3: photos, voice, render, upload, SEO
  python -m eilblick channel-seo                 # one-time channel/page SEO
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
from .render import Beat, SingleTimeline, StoryClip, Timeline, render_single, render_thumbnail, render_video
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
    t = 0.05   # growth 8 Nov: voice starts at frame 0 – no silent lead-in (54 % swiped away)
    voice_spans = [(t, intro_seg.audio)]
    sfx = [("swoop", 0.0)]
    t += intro_seg.duration + 0.15
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
    # growth 8 Nov: no logo end card – the last sentence flows straight back into the hook (loop),
    # the retention curve showed the end card losing viewers; branding is on screen the whole time.
    total = end_start + 0.1
    first = plan["stories"][0]
    tl = Timeline(
        total=total, intro_end=intro_end, end_start=end_start,
        hook_text=plan.get("hook_text") or first["headline"],
        hook_highlight=first.get("highlight", []),
        date_text=german_date(slot_time), slot_label=slot.get("badge") or "DIE SCHLAGZEILEN", clock=slot["time"],
        stories=clips, ticker=[s["headline"] for s in plan["stories"]] + [settings()["channel"]["slogan"]],
    )
    return tl, voice_spans, sfx


def make_video(plan, slot, slot_time, stories, photos, offline_voice=False) -> tuple[Path, Timeline]:
    cfg = settings()
    # Algorithm: the keyword must be heard in the first second (viewed-vs-swiped is decided there)
    intro_text = (plan.get("hook_voice") or "").strip() or f"{plan.get('hook_text', '')}. Eilblick {slot['label']}."
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
    render_thumbnail(tl, OUT / f"{out.stem}_thumb.jpg")
    log(f"  rendered in {time.time()-t0:.0f}s → {out.name} ({out.stat().st_size/1e6:.1f} MB)")
    return out, tl


def make_video_single(plan, slot, slot_time, story, photos, offline_voice=False):
    """FOKUS: hook → 3–4 data beats → loop line. No intro, no outro (the video loops)."""
    cfg = settings()
    texts = [plan["hook_voice"]] + [b["voice"] for b in plan["beats"]] + [plan["loop_line"]]
    log("• Voice-over (ElevenLabs)…" if not offline_voice else "• Voice-over (offline stand-in)…")
    segs = tts.voice_all(texts, offline=offline_voice)
    hard = cfg["editorial"]["single_hard_max_seconds"]
    for _ in range(2):
        total = 0.12 + sum(sg.duration for sg in segs) + 0.12 * (len(segs) - 1) + 0.15
        if total <= hard:
            break
        f = min(1.15, (total - 0.4) / max(1.0, total - (total - hard) - 0.4))
        log(f"  {total:.1f}s > {hard}s → tightening voice ×{f:.3f}")
        segs = [speed_up(sg, f) for sg in segs]
    t = 0.12
    spans, beats, sfx = [], [], [("sting", 0.0)]
    meta = [("", "")] + [(b.get("big", ""), b.get("label", "")) for b in plan["beats"]] + [("", "")]
    for i, (sg, (big, label)) in enumerate(zip(segs, meta)):
        spans.append((t, sg.audio))
        end = t + sg.duration + 0.12
        beats.append(Beat(start=t if i else 0.0, end=end, words=[(w, t + a, t + b) for w, a, b in sg.words],
                          big=big, label=label))
        if 0 < i < len(segs) - 1:
            sfx.append(("whoosh", max(0, t - 0.2)))
        t = end
    total = t + 0.03
    tl = SingleTimeline(total=total, hook_end=beats[0].end, hook_screen=plan["hook_screen"],
                        kicker=plan["kicker"], highlight=plan.get("highlight", []),
                        photos=[p for ph in photos for p in ph], sources=story.outlets,
                        beats=beats, loop_start=beats[-1].start)
    log(f"• FOKUS timeline {total:.1f}s")
    mixcfg = dict(cfg["audio"])
    mix = A.mix(total, spans, sfx, mixcfg)
    wav = TMP / "mix.wav"
    A.write_wav(wav, mix)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"eilblick_{slot_time:%Y-%m-%d}_{slot['id']}.mp4"
    prev = OUT / "preview"
    prev.mkdir(exist_ok=True)
    t0 = time.time()
    log("• Rendering FOKUS video…")
    render_single(tl, wav, out, prev, thumb=OUT / f"{out.stem}_thumb.jpg")
    log(f"  rendered in {time.time()-t0:.0f}s → {out.name} ({out.stat().st_size/1e6:.1f} MB)")
    tl.stories = [StoryClip(beats[0].start, total, beats[0].start, [w for b in beats for w in b.words], tl.photos,
                            plan["kicker"], plan["headline"], plan.get("highlight", []), plan["pillar"],
                            story.outlets, 1, 1)]
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


QUEUE = ROOT / "queue"


def queue_dir(slot: dict, slot_time) -> Path:
    return QUEUE / f"{slot_time:%Y-%m-%d}_{slot['id']}"


def srt_from_timeline(tl: Timeline) -> str:
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"
    cues, n = [], 1
    for st in tl.stories:
        words = st.words
        for i in range(0, len(words), 6):
            g = words[i:i + 6]
            cues.append(f"{n}\n{ts(g[0][1])} --> {ts(g[-1][2] + 0.1)}\n{' '.join(w[0] for w in g)}\n")
            n += 1
    return "\n".join(cues)


def cmd_candidates(args) -> int:
    from . import feeds
    from .feeds import story_to_dict
    cfg = settings()
    slot, slot_time = slot_by_id(args.slot) if args.slot else (current_slot() or (None, None))
    if not slot:
        log("no slot in window; pass --slot")
        return 1
    log(f"• Collecting news for {slot['id']} {german_date(slot_time)} {slot['time']}…")
    stories = feeds.gather(cfg["editorial"])
    already = [s["headline"] for s in state.recent_titles(cfg["editorial"]["dedupe_days"])]
    d = queue_dir(slot, slot_time)
    d.mkdir(parents=True, exist_ok=True)
    data = {"slot": slot, "slot_time": slot_time.isoformat(), "date_text": german_date(slot_time),
            "already_published": already[-40:],
            "candidates": [story_to_dict(s, i) for i, s in enumerate(stories[:28])]}
    (d / "candidates.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  {len(data['candidates'])} candidates → {d.relative_to(ROOT)}/candidates.json")
    for c in data["candidates"][:12]:
        log(f"  #{c['id']:2d} {c['score']:5.1f} [{','.join(c['regions'])}] ({len(c['outlets'])}) {c['articles'][0]['title'][:90]}")
    # tidy: drop queue folders older than 3 days
    for old in sorted(QUEUE.glob("*_*")):
        if old.name[:10] < f"{(slot_time - __import__('datetime').timedelta(days=3)):%Y-%m-%d}":
            import shutil
            shutil.rmtree(old, ignore_errors=True)
    return 0


def cmd_fallback(args) -> int:
    """GitHub-only fallback (no Claude session needed). Runs ~45 min before each slot:
    if the Claude news desk did not deliver the edition (no plan.json, nothing published),
    collect news, write the edition via the Anthropic API key and build it. One try only."""
    import subprocess
    import time as _t
    from datetime import timedelta
    from . import editor
    cfg = settings()
    now = now_berlin()
    found = None
    for slot in cfg["slots"]:
        t = slot_by_id(slot["id"], now)[1]
        if timedelta(minutes=10) <= t - now <= timedelta(minutes=75):
            found = (slot, t)
    if args.slot:
        found = slot_by_id(args.slot, now)
    if not found:
        log(f"fallback: no slot in the next 10–75 min ({now:%H:%M} Berlin) – nothing to do")
        return 0
    slot, slot_time = found
    date = slot_time.strftime("%Y-%m-%d")
    d = queue_dir(slot, slot_time)
    if state.slot_done(date, slot["id"]):
        log(f"fallback: {slot['id']} already published – nothing to do")
        return 0
    if (d / "plan.json").exists():
        log(f"fallback: {d.name}/plan.json exists – the news desk handled it (one try only) – nothing to do")
        return 0
    cand = d / "candidates.json"
    if cand.exists() and _t.time() - cand.stat().st_mtime < 30 * 60:
        wait = cfg["editorial"].get("fallback_wait_minutes", 10)
        log(f"fallback: news desk seems busy, waiting up to {wait} min for its plan…")
        for _ in range(wait * 2):
            _t.sleep(30)
            subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT)
            if (d / "plan.json").exists() or state.slot_done(date, slot["id"]):
                log("fallback: news desk delivered – nothing to do")
                return 0
    if not editor.api_key():
        log("fallback: no ANTHROPIC_API_KEY secret – cannot write the edition")
        return 1
    log(f"fallback: the Claude news desk did not deliver {slot['id']} – using the Anthropic API")
    args.slot = slot["id"]
    cmd_candidates(args)
    editor.write_plan_via_api(d)
    (d / "FALLBACK").write_text("written by the Anthropic API fallback\n", encoding="utf-8")
    log("fallback: plan written ✓")
    return 0


def cmd_validate(args) -> int:
    from . import editor
    d = ROOT / args.queue if not Path(args.queue).is_absolute() else Path(args.queue)
    cands = json.loads((d / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    plan = editor.load_plan(d / "plan.json")
    errs = editor.validate(plan, len(cands))
    if errs:
        log("PLAN INVALID:\n- " + "\n- ".join(errs))
        return 1
    log("plan OK ✓")
    return 0


def cmd_run(args) -> int:
    try:
        return _cmd_run(args)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        log(tb)
        try:
            d = ROOT / args.queue if not Path(args.queue).is_absolute() else Path(args.queue)
            (d / "result.md").write_text("## BUILD FAILED\n\n```\n" + tb[-3000:] + "\n```\n", encoding="utf-8")
        except Exception:
            pass
        raise


def _cmd_run(args) -> int:
    from . import editor, seo
    from .feeds import story_from_dict
    cfg = settings()
    d = ROOT / args.queue if not Path(args.queue).is_absolute() else Path(args.queue)
    cdata = json.loads((d / "candidates.json").read_text(encoding="utf-8"))
    slot = cdata["slot"]
    slot_time = datetime.fromisoformat(cdata["slot_time"])
    date = slot_time.strftime("%Y-%m-%d")
    log(f"=== EILBLICK {slot['id']} · {german_date(slot_time)} {slot['time']} Berlin ===")
    if state.slot_done(date, slot["id"]) and not args.force:
        log("Slot already published – skipping (use --force to rebuild).")
        return 0
    plan = editor.load_plan(d / "plan.json")
    errs = editor.validate(plan, len(cdata["candidates"]))
    if errs:
        raise RuntimeError("plan invalid: " + "; ".join(errs))

    images.reset_tmp()
    if not args.no_upload:
        try:
            cmd_post_comments()
        except Exception as e:
            log(f"  (comments skipped: {e})")
    single = editor.is_single(plan)
    if single:
        plan["stories"] = [editor.single_story(plan)]
    chosen = [story_from_dict(cdata["candidates"][s["candidate_id"]]) for s in plan["stories"]]
    for i, s in enumerate(plan["stories"]):
        log(f"  {i+1}. [{s['region']}/{s['pillar']}] {s['headline']}  ←  {', '.join(chosen[i].outlets[:4])}")

    log("• Collecting news photos into temporary folder…")
    photos = images.collect(chosen, plan["stories"])

    if single:
        video, tl = make_video_single(plan, slot, slot_time, chosen[0], photos)
    else:
        video, tl = make_video(plan, slot, slot_time, chosen, photos)
    chosen = chosen[:len(plan["stories"])]
    credits = [p.credit for ph in photos[:len(plan["stories"])] for p in ph]
    srcs = list(dict.fromkeys(o for s in chosen for o in s.outlets))
    title, desc, tags = seo.youtube_meta(plan, credits, srcs, german_date(slot_time))
    fb_caption = seo.facebook_caption(plan)
    srt = srt_from_timeline(tl)
    thumb = OUT / f"{video.stem}_thumb.jpg"
    meta = {"title": title, "description": desc, "tags": tags, "facebook": fb_caption,
            "plan": plan, "duration": round(tl.total, 1)}
    (OUT / f"{video.stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{video.stem}.de.srt").write_text(srt, encoding="utf-8")

    entry = {"date": date, "slot": slot["id"], "publish_at": slot_time.astimezone(timezone.utc).isoformat(),
             "title": title, "duration": round(tl.total, 1),
             "stories": [{"headline": s["headline"], "region": s["region"], "pillar": s["pillar"]}
                         for s in plan["stories"]],
             "comment": {"text": plan.get("comment_question", ""), "done": not plan.get("comment_question")}}
    errors, notes = [], []
    if not args.no_upload:
        from . import upload_facebook as FB
        from . import upload_youtube as YT
        yc = cfg["youtube"]
        if yc["enabled"]:
            try:
                vid = _retry(lambda: YT.upload(video, title, desc, tags, slot_time,
                                               slot.get("notify_subscribers", True)))
                entry["youtube_id"] = vid
                if yc.get("custom_thumbnail") and thumb.exists():
                    try:
                        YT.set_thumbnail(vid, thumb)
                    except Exception as e:
                        notes.append(f"thumbnail: {e}")
                if yc.get("upload_captions"):
                    try:
                        YT.upload_captions(vid, srt)
                    except Exception as e:
                        notes.append(f"captions: {e}")
                if yc.get("use_playlists"):
                    try:
                        pl_file = state.STATE_DIR / "playlists.json"
                        store = json.loads(pl_file.read_text()) if pl_file.exists() else {}
                        store = YT.ensure_playlists(cfg["seo"]["playlists"], store)
                        pl_file.write_text(json.dumps(store, indent=1))
                        for key in ["ALLE"] + list(dict.fromkeys(s["pillar"] for s in plan["stories"])):
                            if store.get(key):
                                YT.add_to_playlist(store[key], vid)
                        log("  playlists ✓")
                    except Exception as e:
                        notes.append(f"playlists: {e}")
            except Exception as e:
                errors.append(f"YouTube: {e}")
        if cfg["facebook"]["enabled"]:
            try:
                entry["facebook_id"] = _retry(lambda: FB.upload(video, fb_caption, slot_time))
                if thumb.exists():
                    try:
                        FB.set_thumbnail(entry["facebook_id"], thumb)
                    except Exception as e:
                        notes.append(f"fb thumbnail: {e}")
            except Exception as e:
                errors.append(f"Facebook: {e}")
        from . import upload_buffer as BU
        if BU.key():
            try:
                due = slot_time.astimezone(timezone.utc)
                due_iso = due.strftime("%Y-%m-%dT%H:%M:%S.000Z") if due > datetime.now(timezone.utc) + \
                    __import__("datetime").timedelta(minutes=10) else None
                entry["buffer"] = BU.post_video_everywhere(
                    video, f"media-{date}_{slot['id']}", seo.tiktok_caption(plan), seo.x_caption(plan),
                    plan.get("hook_text") or plan["youtube_title"], due_iso)
            except Exception as e:
                errors.append(f"Buffer (TikTok/X): {e}")
        if not cfg["youtube"]["post_first_comment"]:
            entry["comment"]["done"] = True
        if entry.get("youtube_id") or entry.get("facebook_id"):
            state.record(entry)
    images.cleanup_tmp()   # news photos deleted right after upload
    log("• Temporary photo folder deleted.")
    report = (f"## Eilblick {slot['id']} – {german_date(slot_time)} {slot['time']}\n"
              f"**{title}** ({tl.total:.1f}s)\n\n" +
              "\n".join(f"{i+1}. {s['headline']}" for i, s in enumerate(plan["stories"])) +
              (f"\n\nYouTube: https://youtube.com/shorts/{entry['youtube_id']}" if entry.get("youtube_id") else "") +
              (f"\n\nFacebook reel id: {entry['facebook_id']}" if entry.get("facebook_id") else "") +
              (f"\n\nBuffer (TikTok/X): {entry['buffer']}" if entry.get("buffer") else "") +
              ("\n\nNotes: " + "; ".join(notes) if notes else "") +
              ("\n\n**Errors:** " + "; ".join(errors) if errors else ""))
    summary(report)
    (d / "result.md").write_text(report, encoding="utf-8")
    if errors:
        log("ERRORS: " + " | ".join(errors))
        return 1
    return 0


def _report(name: str, lines: list[str]) -> None:
    state.STATE_DIR.mkdir(exist_ok=True)
    (state.STATE_DIR / name).write_text(
        f"# {name} – {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def cmd_check_feeds() -> int:
    from . import feeds
    arts, status = feeds.fetch_all(verbose=True)
    trends = feeds.fetch_trends()
    lines = [f"- {k}: {v}" for k, v in status.items()]
    lines.append(f"\n{sum(1 for v in status.values() if v.startswith('ok'))}/{len(status)} feeds OK, "
                 f"{len(arts)} articles, {len(trends)} Google-Trends terms\n")
    stories = feeds.gather(settings()["editorial"], verbose=False)
    for s in stories[:15]:
        lines.append(f"- {s.score:5.1f} [{','.join(sorted(s.regions))}] ({len(s.outlets)}) {s.lead.title[:90]}")
    log("\n".join(lines))
    _report("check_feeds.md", lines)
    return 0


def cmd_check_tokens() -> int:
    import requests
    from .config import env
    lines, ok = [], True
    names = ["BUFFER_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ELEVENLABS_API_KEY", "YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN",
             "FB_PAGE_ID", "FB_PAGE_TOKEN", "FB_APP_ID", "FB_APP_SECRET"]
    lines.append("Secrets present: " + ", ".join(f"{n}={'yes' if os.environ.get(n) else 'NO'}" for n in names))
    try:
        from .upload_youtube import access_token
        tok = access_token()
        ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                          params={"part": "snippet,status,statistics", "mine": "true"},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=30).json()
        sc = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": tok}, timeout=30).json()
        for i in ch.get("items", []):
            lines.append(f"YouTube OK: channel '{i['snippet']['title']}' ({i['id']}), "
                         f"longUploads={i.get('status', {}).get('longUploadsStatus')}, "
                         f"subs={i.get('statistics', {}).get('subscriberCount')}")
        if not ch.get("items"):
            ok = False
            lines.append(f"YouTube FAIL: no channel for this token: {str(ch)[:200]}")
        lines.append("YouTube scopes: " + str(sc.get("scope", "?")))
    except Exception as e:
        ok = False
        lines.append(f"YouTube FAIL: {str(e)[:300]}")
    try:
        from .upload_facebook import check_token
        info = check_token()
        lines.append(f"Facebook: me={ {k: v for k, v in info['me'].items() if k != 'access_token'} }, token={info['token']}"
                     + (f"  WARNING: {info['warning']}" if info.get("warning") else ""))
        if "error" in info["me"]:
            ok = False
    except Exception as e:
        ok = False
        lines.append(f"Facebook FAIL: {str(e)[:300]}")
    try:
        v = settings()["voice"]
        r = requests.get("https://api.elevenlabs.io/v1/voices/" + v["voice_id"],
                         headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, timeout=30)
        lines.append(f"ElevenLabs voice info: HTTP {r.status_code} "
                     + (f"name='{r.json().get('name')}'" if r.ok else r.text[:250]))
        t = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{v['voice_id']}",
                          params={"output_format": "mp3_44100_64"},
                          headers={"xi-api-key": env("ELEVENLABS_API_KEY")},
                          json={"text": "Eilblick.", "model_id": v["model_id"]}, timeout=60)
        if t.ok and len(t.content) > 1000:
            lines.append(f"ElevenLabs OK: test speech generated with {v['model_id']} ({len(t.content)} bytes)")
        else:
            ok = False
            lines.append(f"ElevenLabs TTS FAIL: HTTP {t.status_code} {t.text[:300]}")
    except Exception as e:
        ok = False
        lines.append(f"ElevenLabs FAIL: {str(e)[:200]}")
    try:
        from .editor import _api_call, api_key
        if api_key():
            txt = _api_call("Antworte nur mit: OK", [{"role": "user", "content": "Test"}],
                            settings()["editorial"].get("api_model", "claude-sonnet-5-5"), 10)
            lines.append(f"Anthropic API OK: model {settings()['editorial'].get('api_model')} answered '{txt.strip()[:20]}'")
        else:
            lines.append("Anthropic API: no key secret found (ANTHROPIC_API_KEY / CLAUDE_API_KEY)")
    except Exception as e:
        ok = False
        lines.append(f"Anthropic API FAIL: {str(e)[:300]}")
    try:
        from . import upload_buffer as BU
        if BU.key():
            chs = BU.channels()
            lines.append("Buffer OK: " + ", ".join(f"{c['service']} '{c['name']}' ({c['id']})" for c in chs))
        else:
            lines.append("Buffer: no BUFFER_API_KEY secret found")
    except Exception as e:
        ok = False
        lines.append(f"Buffer FAIL: {str(e)[:300]}")
    log("\n".join(lines))
    _report("check_tokens.md", lines)
    return 0 if ok else 1


def cmd_channel_seo() -> int:
    seo_cfg = settings()["seo"]
    lines = []
    try:
        from . import upload_youtube as YT
        info = YT.channel_seo(seo_cfg["channel_description"], seo_cfg["channel_keywords"])
        lines.append(f"YouTube channel SEO ✓ {info}")
        pl_file = state.STATE_DIR / "playlists.json"
        store = json.loads(pl_file.read_text()) if pl_file.exists() else {}
        store = YT.ensure_playlists(seo_cfg["playlists"], store)
        pl_file.write_text(json.dumps(store, indent=1))
        lines.append(f"YouTube playlists ✓ {list(store)}")
    except Exception as e:
        lines.append(f"YouTube channel SEO FAIL: {str(e)[:300]}")
    try:
        from . import upload_facebook as FB
        res = FB.page_seo(settings()["channel"]["slogan"] + " Viermal täglich die wichtigsten Nachrichten aus "
                          "Deutschland, Österreich, der Schweiz und der Welt – in unter 50 Sekunden.",
                          settings()["channel"]["website"])
        lines.append(f"Facebook page SEO: {res}")
    except Exception as e:
        lines.append(f"Facebook page SEO FAIL: {str(e)[:300]}")
    log("\n".join(lines))
    _report("channel_seo.md", lines)
    return 0


def cmd_comments_fetch() -> int:
    """Collect every unanswered comment → state/comments_inbox.json (no names stored)."""
    from . import upload_facebook as FB
    from . import upload_youtube as YT
    done = set(json.loads((state.STATE_DIR / "comments_done.json").read_text())
               if (state.STATE_DIR / "comments_done.json").exists() else [])
    inbox, errs = [], []
    try:
        inbox += YT.unanswered_comments()
    except Exception as e:
        errs.append(f"youtube: {e}")
    # Owner rule 9 Nov 2026: never reply to Facebook comments – only YouTube comments are collected.
    if settings().get("facebook", {}).get("reply_to_comments", False):
        try:
            fb_ids = [r["facebook_id"] for r in state.load()["runs"] if r.get("facebook_id")][-60:]
            inbox += FB.unanswered_comments(fb_ids)
        except Exception as e:
            errs.append(f"facebook: {e}")
    titles = {r.get("youtube_id"): r.get("title") for r in state.load()["runs"]}
    titles.update({r.get("facebook_id"): r.get("title") for r in state.load()["runs"]})
    inbox = [dict(c, video_title=titles.get(c["video"], "")) for c in inbox if c["id"] not in done]
    (state.STATE_DIR / "comments_inbox.json").write_text(
        json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "errors": errs, "comments": inbox},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{len(inbox)} unanswered comments" + (f"; errors: {errs}" if errs else ""))
    try:
        performance_report()
    except Exception as e:
        log(f"  performance report skipped: {e}")
    return 0


def performance_report() -> None:
    """Views/likes/comments of recent videos → state/performance.md, so the news desk
    learns which topics, hooks and titles the algorithm and the audience reward."""
    import requests
    runs = [r for r in state.load()["runs"] if r.get("youtube_id")][-40:]
    if not runs:
        return
    from . import upload_facebook as FB
    from . import upload_youtube as YT
    stats = {}
    try:
        ids = ",".join(r["youtube_id"] for r in runs)
        js = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics", "id": ids},
                          headers={"Authorization": f"Bearer {YT._tok()}"}, timeout=30).json()
        stats = {i["id"]: i["statistics"] for i in js.get("items", [])}
    except Exception as e:
        log(f"  yt stats: {e}")
    rows = []
    for r in runs:
        st = stats.get(r["youtube_id"], {})
        fbv = ""
        try:
            ins = requests.get(f"{FB._g()}/{r['facebook_id']}/video_insights",
                               params=FB._auth(FB.page_token()), timeout=20).json().get("data", [])
            m = {x.get("name"): (x.get("values") or [{}])[0].get("value") for x in ins}
            fbv = m.get("blue_reels_play_count") or m.get("fb_reels_total_plays") or m.get("total_video_views") or ""
        except Exception:
            pass
        fbl = fbc = ""
        try:   # growth 11 Nov: Facebook engagement per reel (likes / comments) for the night analysis
            js2 = requests.get(f"{FB._g()}/{r['facebook_id']}",
                               params=dict(FB._auth(FB.page_token()),
                                           fields="likes.summary(true).limit(0),comments.summary(true).limit(0)"),
                               timeout=20).json()
            fbl = ((js2.get("likes") or {}).get("summary") or {}).get("total_count", "")
            fbc = ((js2.get("comments") or {}).get("summary") or {}).get("total_count", "")
        except Exception:
            pass
        rows.append((int(st.get("viewCount", 0) or 0), r, st, fbv, fbl, fbc))
    rows.sort(key=lambda x: -x[0])
    lines = ["| YT views | YT likes | YT comments | FB plays | FB likes | FB comments | slot | title | story 1 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for v, r, st, fbv, fbl, fbc in rows:
        lines.append(f"| {v} | {st.get('likeCount', '')} | {st.get('commentCount', '')} | {fbv} | {fbl} | {fbc} | "
                     f"{r['date']} {r['slot']} | {r.get('title', '')} | {(r.get('stories') or [{}])[0].get('headline', '')} |")
    (state.STATE_DIR / "performance.md").write_text(
        f"# Performance (best first) – {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8")


def cmd_comments_post() -> int:
    """Post the replies Claude wrote in state/comments_replies.json."""
    from . import upload_facebook as FB
    from . import upload_youtube as YT
    rf = state.STATE_DIR / "comments_replies.json"
    if not rf.exists():
        log("no replies file")
        return 0
    replies = json.loads(rf.read_text(encoding="utf-8"))
    df = state.STATE_DIR / "comments_done.json"
    done = json.loads(df.read_text()) if df.exists() else []
    ok = fail = 0
    for r in replies:
        if r["id"] in done:
            continue
        if r.get("platform") != "youtube" and not settings().get("facebook", {}).get("reply_to_comments", False):
            continue                    # owner rule 9 Nov 2026: never reply on Facebook
        if not r.get("reply"):          # deliberately skipped (spam / abuse)
            done.append(r["id"])
            continue
        try:
            (YT.reply if r["platform"] == "youtube" else FB.reply)(r["id"], r["reply"][:900])
            done.append(r["id"])
            ok += 1
        except Exception as e:
            fail += 1
            log(f"  reply failed {r['platform']} {r['id']}: {e}")
    df.write_text(json.dumps(done[-5000:]), encoding="utf-8")
    rf.unlink()
    inbox = state.STATE_DIR / "comments_inbox.json"
    if inbox.exists():
        inbox.unlink()
    log(f"replied {ok}, failed {fail}")
    return 0


def cmd_recover() -> int:
    """List the newest uploads on YouTube + Facebook and re-create missing state entries
    (e.g. when a push of the publish log failed)."""
    import requests
    from . import upload_facebook as FB
    from . import upload_youtube as YT
    lines = []
    known_yt = {r.get("youtube_id") for r in state.load()["runs"]}
    tok = YT._tok()
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "contentDetails", "mine": "true"},
                      headers={"Authorization": f"Bearer {tok}"}, timeout=30).json()
    up = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = requests.get("https://www.googleapis.com/youtube/v3/playlistItems",
                         params={"part": "snippet,status", "playlistId": up, "maxResults": 15},
                         headers={"Authorization": f"Bearer {tok}"}, timeout=30).json().get("items", [])
    reels = requests.get(f"{FB._g()}/{FB.page_id()}/video_reels",
                         params={"fields": "id,description,created_time", "limit": 15, **FB._auth(FB.page_token())},
                         timeout=30).json().get("data", [])
    for it in items:
        sn = it["snippet"]
        vid = sn["resourceId"]["videoId"]
        lines.append(f"- YT {vid} {sn.get('publishedAt')} {'(known)' if vid in known_yt else '(NOT IN STATE)'} {sn['title']}")
    for r in reels:
        lines.append(f"- FB {r['id']} {r.get('created_time')} {(r.get('description') or '')[:70]!r}")
    # re-create entries for queue folders whose title matches an unknown upload
    for d in sorted(QUEUE.glob("*_*")):
        meta = OUT / f"eilblick_{d.name}.json"
        pf = d / "plan.json"
        if not pf.exists():
            continue
        date, slot = d.name.split("_", 1)
        if state.slot_done(date, slot):
            continue
        plan = json.loads(pf.read_text(encoding="utf-8"))
        title = plan.get("youtube_title", "").strip()
        yt = next((it["snippet"]["resourceId"]["videoId"] for it in items
                   if it["snippet"]["title"].strip() == title[:100]), None)
        line1 = plan.get("facebook_caption_line1", "")
        fb = next((r["id"] for r in reels if line1 and line1 in (r.get("description") or "")), None)
        if yt or fb:
            single = plan.get("format") == "single"
            stories = [editor_single(plan)] if single else plan["stories"]
            state.record({"date": date, "slot": slot, "title": title, "youtube_id": yt, "facebook_id": fb,
                          "publish_at": datetime.now(timezone.utc).isoformat(), "recovered": True,
                          "stories": [{"headline": s["headline"], "region": s["region"], "pillar": s["pillar"]} for s in stories],
                          "comment": {"text": plan.get("comment_question", ""), "done": False}})
            lines.append(f"RECOVERED {d.name}: yt={yt} fb={fb}")
    log("\n".join(lines))
    _report("recent_uploads.md", lines)
    return 0


def editor_single(plan):
    from .editor import single_story
    return single_story(plan)


def cmd_buffer_test() -> int:
    """Renders the offline demo and sends it to Buffer as DRAFTS (never published)."""
    from . import upload_buffer as BU
    from .demo import demo_inputs
    slot, slot_time = slot_by_id("morgen")
    images.reset_tmp()
    plan, stories, photos = demo_inputs()
    video, tl = make_video(plan, slot, slot_time, stories, photos, offline_voice=True)
    lines = []
    try:
        lines.append("PostInputMetaData fields: " + str(BU._input_fields("PostInputMetaData")))
        res = BU.post_video_everywhere(video, "media-buffer-test", "TEST – bitte löschen", "TEST – bitte löschen",
                                       "Test", None, draft=True)
        lines.append(f"Buffer draft test OK: {res}")
    except Exception as e:
        lines.append(f"Buffer draft test FAIL: {str(e)[:400]}")
    log("\n".join(lines))
    _report("buffer_test.md", lines)
    return 0


def cmd_buffer_delete(args) -> int:
    from . import upload_buffer as BU
    lines = []
    for pid in args.ids:
        try:
            lines.append(f"deleted {pid}: {BU.delete_post(pid)}")
        except Exception as e:
            lines.append(f"delete {pid} FAIL: {str(e)[:300]}")
    log("\n".join(lines))
    _report("buffer_test.md", lines)
    return 0


def cmd_demo(args) -> int:
    from .demo import demo_inputs
    slot, slot_time = slot_by_id(args.slot or "morgen")
    images.reset_tmp()
    plan, stories, photos = demo_inputs()
    video, tl = make_video(plan, slot, slot_time, stories, photos, offline_voice=not args.real_voice)
    (OUT / f"{video.stem}.de.srt").write_text(srt_from_timeline(tl), encoding="utf-8")
    log(f"Demo ready: {video}  ({tl.total:.1f}s)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eilblick")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--slot")
    fb = sub.add_parser("fallback")
    fb.add_argument("--slot")
    v = sub.add_parser("validate-plan")
    v.add_argument("queue")
    r = sub.add_parser("run")
    r.add_argument("--queue", required=True)
    r.add_argument("--force", action="store_true")
    r.add_argument("--no-upload", action="store_true")
    bd = sub.add_parser("buffer-delete")
    bd.add_argument("ids", nargs="+")
    d = sub.add_parser("demo")
    d.add_argument("--slot")
    d.add_argument("--real-voice", action="store_true")
    for n in ("check-feeds", "check-tokens", "post-comments", "channel-seo", "comments-fetch", "comments-post", "recover", "buffer-test"):
        sub.add_parser(n)
    a = ap.parse_args(argv)
    fn = {"candidates": lambda: cmd_candidates(a), "fallback": lambda: cmd_fallback(a), "validate-plan": lambda: cmd_validate(a),
          "run": lambda: cmd_run(a), "demo": lambda: cmd_demo(a), "check-feeds": cmd_check_feeds,
          "check-tokens": cmd_check_tokens, "channel-seo": cmd_channel_seo,
          "comments-fetch": cmd_comments_fetch, "comments-post": cmd_comments_post, "recover": cmd_recover, "buffer-test": cmd_buffer_test, "buffer-delete": lambda: cmd_buffer_delete(a),
          "post-comments": lambda: cmd_post_comments() or 0}[a.cmd]
    return fn()


if __name__ == "__main__":
    sys.exit(main())
