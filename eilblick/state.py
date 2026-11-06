"""Small JSON state committed back to the repo.

Every published edition is stored in its OWN file state/runs/<date>_<slot>.json, so two
builds that finish at the same time can never conflict when they push (this happened on
6 Nov). The old list in state/published.json is still read for history."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import STATE_DIR

FILE = STATE_DIR / "published.json"
RUNS = STATE_DIR / "runs"


def load() -> dict:
    runs = []
    if FILE.exists():
        for r in json.loads(FILE.read_text(encoding="utf-8")).get("runs", []):
            r["_file"] = None
            runs.append(r)
    if RUNS.exists():
        for f in sorted(RUNS.glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                r["_file"] = f.name
                runs.append(r)
            except Exception:
                pass
    runs.sort(key=lambda r: r.get("created", ""))
    return {"runs": runs}


def save(data: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    RUNS.mkdir(exist_ok=True)
    legacy = []
    for r in data["runs"]:
        f = r.get("_file")
        clean = {k: v for k, v in r.items() if k != "_file"}
        if f:
            (RUNS / f).write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            legacy.append(clean)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    legacy = [r for r in legacy if r.get("created", "") >= cutoff]
    FILE.write_text(json.dumps({"runs": legacy}, ensure_ascii=False, indent=1), encoding="utf-8")


def slot_done(date: str, slot: str) -> bool:
    return any(r["date"] == date and r["slot"] == slot and (r.get("youtube_id") or r.get("facebook_id"))
               for r in load()["runs"])


def recent_titles(days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for r in load()["runs"]:
        if r.get("created", "") >= cutoff:
            out.extend(r.get("stories", []))
    return out


def record(entry: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    entry["created"] = datetime.now(timezone.utc).isoformat()
    (RUNS / f"{entry['date']}_{entry['slot']}.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
