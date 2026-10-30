"""Facebook Page Reels upload via the Graph API (start → upload → finish),
with scheduled publishing at the slot time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import env, settings


def _g() -> str:
    return f"https://graph.facebook.com/{settings()['facebook']['graph_version']}"


def upload(video: Path, description: str, publish_at: datetime) -> str:
    page = env("FB_PAGE_ID")
    tok = env("FB_PAGE_TOKEN")
    r = requests.post(f"{_g()}/{page}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"FB start failed: {r.text[:400]}")
    vid = r.json()["video_id"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(
            f"https://rupload.facebook.com/video-upload/{settings()['facebook']['graph_version']}/{vid}",
            headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)},
            data=f, timeout=900,
        )
    if up.status_code >= 400 or not up.json().get("success", False):
        raise RuntimeError(f"FB upload failed: {up.text[:400]}")
    data = {"upload_phase": "finish", "video_id": vid, "description": description[:2200], "access_token": tok}
    ts = int(publish_at.astimezone(timezone.utc).timestamp())
    if publish_at.astimezone(timezone.utc) > datetime.now(timezone.utc) + timedelta(minutes=12):
        data.update(video_state="SCHEDULED", scheduled_publish_time=str(ts))
    else:
        data.update(video_state="PUBLISHED")
    fin = requests.post(f"{_g()}/{page}/video_reels", data=data, timeout=60)
    if fin.status_code >= 400:
        raise RuntimeError(f"FB finish failed: {fin.text[:400]}")
    print(f"  Facebook ✓ reel {vid} ({data['video_state']})")
    return vid


def comment(video_id: str, text: str) -> str:
    r = requests.post(f"{_g()}/{video_id}/comments", data={"message": text, "access_token": env("FB_PAGE_TOKEN")},
                      timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"FB comment failed: {r.text[:300]}")
    return r.json().get("id", "")


def check_token() -> dict:
    """Shows which Page the token belongs to and that it can post."""
    tok = env("FB_PAGE_TOKEN")
    me = requests.get(f"{_g()}/me", params={"fields": "id,name", "access_token": tok}, timeout=30).json()
    perms = requests.get(f"{_g()}/debug_token", params={"input_token": tok, "access_token": tok}, timeout=30).json()
    return {"me": me, "token": perms.get("data", perms)}
