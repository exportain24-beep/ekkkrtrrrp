"""Tiny JSON state (committed back to the repo): which slots are done and
which stories were already used, so nothing is published twice."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR

FILE = STATE_DIR / "published.json"


def load() -> dict:
    if FILE.exists():
        return json.loads(FILE.read_text(encoding="utf-8"))
    return {"runs": []}


def save(data: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    data["runs"] = [r for r in data["runs"] if r.get("created", "") >= cutoff]
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slot_done(date: str, slot: str) -> bool:
    return any(r["date"] == date and r["slot"] == slot and r.get("youtube_id") or
               r["date"] == date and r["slot"] == slot and r.get("facebook_id")
               for r in load()["runs"])


def recent_titles(days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for r in load()["runs"]:
        if r.get("created", "") >= cutoff:
            out.extend(r.get("stories", []))
    return out


def record(entry: dict) -> None:
    data = load()
    entry["created"] = datetime.now(timezone.utc).isoformat()
    data["runs"].append(entry)
    save(data)
