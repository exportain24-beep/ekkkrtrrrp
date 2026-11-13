"""Publish an EILBLICK FOKUS episode beyond YouTube.

Facebook : regular 16:9 page video (chunked upload to /{page}/videos), same time as YouTube.
           Owner rules: NO website/link in the caption, no comment replies.
TikTok/X : via Buffer (same path as the Shorts), video hosted as a GitHub release asset.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from .. import upload_facebook as fb


def _fb_caption(ep: dict) -> str:
    intro = ep["description_intro"].strip()
    for bad in ("http", "www.", "eilblick.de"):      # owner rule: never a link on Facebook
        intro = intro.replace(bad, "")
    return (f"{ep['youtube_title']}\n\n{intro}\n\n"
            f"EILBLICK FOKUS – jeden Tag ein Hintergrundbericht zu einem Thema, das Deutschland bewegt. "
            f"Neutral, belegt, verständlich. Alle Quellen stehen im Video und in der YouTube-Beschreibung.\n\n"
            + " ".join(ep["hashtags"] + ["#Nachrichten", "#Deutschland"]))[:5000]


def facebook_video(ep: dict, mp4: Path, thumb: Path, when: datetime, public_now: bool) -> str:
    g = fb._g().replace("graph.facebook.com", "graph-video.facebook.com")
    page, tok = fb.page_id(), fb.page_token()
    auth = fb._auth(tok)
    size = mp4.stat().st_size
    r = requests.post(f"{g}/{page}/videos", data={"upload_phase": "start", "file_size": size, **auth}, timeout=60)
    j = r.json()
    if "upload_session_id" not in j:
        raise RuntimeError(f"FB start: {r.text[:300]}")
    sid, vid = j["upload_session_id"], j["video_id"]
    start, end = int(j["start_offset"]), int(j["end_offset"])
    with open(mp4, "rb") as f:
        while start < end:
            f.seek(start)
            chunk = f.read(end - start)
            for attempt in range(3):
                try:
                    t = requests.post(f"{g}/{page}/videos",
                                      data={"upload_phase": "transfer", "upload_session_id": sid,
                                            "start_offset": start, **auth},
                                      files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
                                      timeout=300).json()
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
            if "start_offset" not in t:
                raise RuntimeError(f"FB transfer: {str(t)[:300]}")
            start, end = int(t["start_offset"]), int(t["end_offset"])
    data = {"upload_phase": "finish", "upload_session_id": sid, "title": ep["youtube_title"][:250],
            "description": _fb_caption(ep), **auth}
    ts = int(when.timestamp())
    if not public_now and ts > datetime.now(timezone.utc).timestamp() + 11 * 60:
        data.update({"published": "false", "scheduled_publish_time": ts})
    with open(thumb, "rb") as th:
        fin = requests.post(f"{g}/{page}/videos", data=data,
                            files={"thumb": ("thumb.jpg", th, "image/jpeg")}, timeout=120)
    if fin.status_code >= 400 or not fin.json().get("success", True):
        raise RuntimeError(f"FB finish: {fin.text[:300]}")
    return vid


def buffer_posts(ep: dict, mp4: Path, when: datetime, public_now: bool, yt_id: str | None, tag: str) -> dict:
    from .. import upload_buffer as bf
    if not bf.key():
        return {"buffer": "no BUFFER_API_KEY"}
    tags = " ".join(ep["hashtags"])
    tiktok = f"{ep['youtube_title']} – der ganze Hintergrund in {ep.get('_minutes', 8)} Minuten. {tags} #Nachrichten #Deutschland"
    x = f"{ep['youtube_title']}\n\nDer Hintergrundbericht von EILBLICK FOKUS"
    if yt_id:
        x += f": https://youtu.be/{yt_id}"
    x = (x + f"\n{tags}")[:270]
    due = None if public_now else when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    out = {}
    url = bf.host_video(mp4, tag)
    for c in bf.channels():
        svc = c["service"].lower()
        if svc not in ("tiktok", "twitter", "x"):
            continue
        text = tiktok if svc == "tiktok" else x
        meta = bf.metadata_for(svc, ep["youtube_title"])
        try:
            try:
                pid = bf.create_video_post(c["id"], text, url, due, meta)
            except RuntimeError:
                if not meta:
                    raise
                pid = bf.create_video_post(c["id"], text, url, due, None)
            out[svc] = f"✓ {pid}"
        except Exception as e:
            out[svc] = f"✗ {str(e)[:160]}"
    return out


def publish_all(ep: dict, mp4: Path, thumb: Path, when: datetime, public_now: bool,
                yt_id: str | None, tag: str) -> list[str]:
    lines = []
    if os.environ.get("FB_PAGE_TOKEN"):
        try:
            v = facebook_video(ep, mp4, thumb, when, public_now)
            lines.append(f"- Facebook ✓ Video {v} ({'sofort' if public_now else 'geplant'})")
        except Exception as e:
            lines.append(f"- Facebook ✗ {str(e)[:200]}")
    else:
        lines.append("- Facebook – kein FB_PAGE_TOKEN")
    try:
        for svc, st in buffer_posts(ep, mp4, when, public_now, yt_id, tag).items():
            lines.append(f"- {svc} {st}")
    except Exception as e:
        lines.append(f"- Buffer ✗ {str(e)[:200]}")
    return lines
