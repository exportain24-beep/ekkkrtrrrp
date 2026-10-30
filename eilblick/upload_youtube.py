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


# ------------------------------------------------------------------ extra SEO
_TOK: dict = {}


def _tok() -> str:
    if "t" not in _TOK:
        _TOK["t"] = access_token()
    return _TOK["t"]


def set_thumbnail(video_id: str, jpg: Path) -> None:
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                      params={"videoId": video_id, "uploadType": "media"},
                      headers={"Authorization": f"Bearer {_tok()}", "Content-Type": "image/jpeg"},
                      data=jpg.read_bytes(), timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"thumbnail {r.status_code}: {r.text[:200]}")
    print("  YouTube thumbnail ✓")


def upload_captions(video_id: str, srt: str) -> None:
    boundary = "eilblick_caption_boundary"
    meta = json.dumps({"snippet": {"videoId": video_id, "language": "de", "name": "Deutsch", "isDraft": False}})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n{srt}\r\n--{boundary}--\r\n").encode("utf-8")
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/captions",
                      params={"part": "snippet", "uploadType": "multipart"},
                      headers={"Authorization": f"Bearer {_tok()}",
                               "Content-Type": f"multipart/related; boundary={boundary}"},
                      data=body, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"captions {r.status_code}: {r.text[:200]}")
    print("  YouTube German captions ✓")


def ensure_playlists(defs: dict, store: dict) -> dict:
    """Create the SEO playlists once; ids are kept in state/playlists.json."""
    for key, d in defs.items():
        if store.get(key):
            continue
        r = requests.post("https://www.googleapis.com/youtube/v3/playlists", params={"part": "snippet,status"},
                          headers={"Authorization": f"Bearer {_tok()}"},
                          json={"snippet": {"title": d["title"], "description": d["description"],
                                            "defaultLanguage": "de"},
                                "status": {"privacyStatus": "public"}}, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"playlist {key} {r.status_code}: {r.text[:200]}")
        store[key] = r.json()["id"]
        print(f"  playlist created: {d['title']}")
    return store


def add_to_playlist(playlist_id: str, video_id: str) -> None:
    r = requests.post("https://www.googleapis.com/youtube/v3/playlistItems", params={"part": "snippet"},
                      headers={"Authorization": f"Bearer {_tok()}"},
                      json={"snippet": {"playlistId": playlist_id,
                                        "resourceId": {"kind": "youtube#video", "videoId": video_id}}}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"playlistItem {r.status_code}: {r.text[:200]}")


def channel_seo(description: str, keywords: list[str]) -> dict:
    """One-time channel SEO: description, keywords, country DE, default language de."""
    h = {"Authorization": f"Bearer {_tok()}"}
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                      params={"part": "brandingSettings,snippet", "mine": "true"}, headers=h, timeout=30).json()
    item = ch["items"][0]
    bs = item.get("brandingSettings", {})
    chan = bs.get("channel", {})
    chan["description"] = description[:1000]
    chan["keywords"] = " ".join(f'"{k}"' if " " in k else k for k in keywords)[:500]
    chan["country"] = "DE"
    chan["defaultLanguage"] = "de"
    bs["channel"] = chan
    r = requests.put("https://www.googleapis.com/youtube/v3/channels", params={"part": "brandingSettings"},
                     headers=h, json={"id": item["id"], "brandingSettings": bs}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"channel update {r.status_code}: {r.text[:300]}")
    return {"channel": item["snippet"]["title"], "id": item["id"]}
