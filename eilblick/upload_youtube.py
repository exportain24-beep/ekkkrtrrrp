"""YouTube Data API v3 upload (resumable) with scheduled publishing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import env, settings

TOKEN_URL = "https://oauth2.googleapis.com/token"


def access_token() -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": env("YT_CLIENT_ID"),
        "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube token refresh failed: {r.text[:300]}")
    return r.json()["access_token"]


def upload(video: Path, title: str, description: str, tags: list[str], publish_at: datetime,
           notify: bool) -> str:
    cfg = settings()["youtube"]
    tok = access_token()
    now = datetime.now(timezone.utc)
    status = {
        "selfDeclaredMadeForKids": cfg["made_for_kids"],
        "embeddable": True,
        "license": cfg["license"],
        "containsSyntheticMedia": cfg["contains_synthetic_media"],
    }
    if publish_at.astimezone(timezone.utc) > now + timedelta(minutes=10):
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        status["privacyStatus"] = "public"
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags,
            "categoryId": cfg["category_id"],
            "defaultLanguage": "de",
            "defaultAudioLanguage": "de",
        },
        "status": status,
    }
    size = video.stat().st_size
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status",
                "notifySubscribers": "true" if notify else "false"},
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(body), timeout=60,
    )
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube init failed {init.status_code}: {init.text[:400]}")
    loc = init.headers["Location"]
    with open(video, "rb") as f:
        up = requests.put(loc, data=f, headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"},
                          timeout=900)
    if up.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed {up.status_code}: {up.text[:400]}")
    vid = up.json()["id"]
    print(f"  YouTube ✓ https://youtube.com/shorts/{vid}  ({status['privacyStatus']}"
          f"{' → ' + status.get('publishAt', '') if 'publishAt' in status else ''})")
    return vid


def comment(video_id: str, text: str) -> str:
    tok = access_token()
    r = requests.post(
        "https://www.googleapis.com/youtube/v3/commentThreads", params={"part": "snippet"},
        headers={"Authorization": f"Bearer {tok}"},
        json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube comment failed {r.status_code}: {r.text[:300]}")
    return r.json()["id"]
