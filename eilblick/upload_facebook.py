"""Facebook Page Reels upload via the Graph API (start → upload → finish),
with scheduled publishing at the slot time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .config import env, settings


def _auth(token: str) -> dict:
    """access_token + appsecret_proof (the Meta app requires it: a leaked token alone is useless)."""
    import hashlib
    import hmac
    import os
    d = {"access_token": token}
    sec = os.environ.get("FB_APP_SECRET")
    if sec:
        d["appsecret_proof"] = hmac.new(sec.encode(), token.encode(), hashlib.sha256).hexdigest()
    return d


def _g() -> str:
    return f"https://graph.facebook.com/{settings()['facebook']['graph_version']}"


_PT: dict = {}


def page_token() -> str:
    """FB_PAGE_TOKEN may be a Page token or a System-User token. For a System-User
    token the Page access token is fetched automatically (stays valid, never expires)."""
    if "t" in _PT:
        return _PT["t"]
    tok = env("FB_PAGE_TOKEN")
    page = env("FB_PAGE_ID").strip()
    r = requests.get(f"{_g()}/{page}", params={"fields": "access_token,name", **_auth(tok)}, timeout=30).json()
    if not r.get("access_token"):
        # fall back: look the page up in the token owner's page list
        acc = requests.get(f"{_g()}/me/accounts", params={"fields": "id,name,access_token", **_auth(tok)},
                           timeout=30).json()
        pages = acc.get("data", [])
        _PT["pages"] = [(p.get("id"), p.get("name")) for p in pages]
        hit = next((p for p in pages if p.get("id") == page), None)
        if hit:
            r = hit
        elif "error" in acc:
            r.setdefault("error", acc["error"])
    _PT["t"] = r.get("access_token") or tok
    _PT["name"] = r.get("name")
    _PT["err"] = r.get("error")
    return _PT["t"]


def upload(video: Path, description: str, publish_at: datetime) -> str:
    page = env("FB_PAGE_ID")
    tok = page_token()
    r = requests.post(f"{_g()}/{page}/video_reels", data={"upload_phase": "start", **_auth(tok)}, timeout=60)
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
    data = {"upload_phase": "finish", "video_id": vid, "description": description[:2200], **_auth(tok)}
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
    r = requests.post(f"{_g()}/{video_id}/comments", data={"message": text, **_auth(page_token())},
                      timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"FB comment failed: {r.text[:300]}")
    return r.json().get("id", "")


def _app_token() -> str | None:
    import os
    aid = os.environ.get("FB_APP_ID")
    sec = os.environ.get("FB_APP_SECRET")
    return f"{aid}|{sec}" if aid and sec else None


def check_token() -> dict:
    """Which Page the token belongs to, its scopes and expiry (no secrets printed)."""
    raw = env("FB_PAGE_TOKEN")
    dbg = requests.get(f"{_g()}/debug_token", params={"input_token": raw, **({"access_token": _app_token()} if _app_token() else _auth(raw))},
                       timeout=30).json().get("data", {})
    tok = page_token()
    me = requests.get(f"{_g()}/me", params={"fields": "id,name,category,followers_count", **_auth(tok)},
                      timeout=30).json()
    if _PT.get("err"):
        me["page_token_error"] = _PT["err"]
    if _PT.get("pages") is not None:
        me["pages_visible_to_token"] = _PT["pages"]
    me["page_id_secret_len"] = len(env("FB_PAGE_ID").strip())
    info = {"me": me, "token": {k: dbg.get(k) for k in ("type", "is_valid", "expires_at", "data_access_expires_at",
                                                         "scopes", "app_id")}}
    page_id = env("FB_PAGE_ID", required=False)
    if page_id and me.get("id") and page_id != me.get("id"):
        info["warning"] = f"FB_PAGE_ID ({page_id}) does not match the token's page ({me.get('id')})"
    return info


def page_seo(about: str, website: str) -> dict:
    """Best-effort Page SEO (needs pages_manage_metadata)."""
    r = requests.post(f"{_g()}/{env('FB_PAGE_ID')}",
                      data={"about": about[:255], "website": website, **_auth(page_token())}, timeout=30)
    return r.json()
