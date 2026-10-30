"""Editorial rules + validation for the plan that Claude (the scheduled-task news
desk) writes. The full editorial brief lives in docs/EDITOR_GUIDE.md."""
from __future__ import annotations

import json
from pathlib import Path

from .config import settings

PILLARS = {"POLITIK", "WIRTSCHAFT", "WELT", "TECHNOLOGIE"}
REGIONS = {"DE", "AT", "CH", "EU", "INT"}
REQUIRED = ["youtube_title", "description_lead", "tags", "hashtags", "facebook_caption_line1",
            "facebook_question", "comment_question", "hook_text"]


def validate(plan: dict, n_candidates: int) -> list[str]:
    cfg = settings()["editorial"]
    wmin, wmax = cfg["words_per_story"]
    errs = []
    st = plan.get("stories") or []
    if not (cfg["stories_per_short"] <= len(st) <= cfg["max_stories_per_short"]):
        errs.append(f"need {cfg['stories_per_short']}–{cfg['max_stories_per_short']} stories (got {len(st)})")
    total = 0
    ids = set()
    for k, s in enumerate(st):
        w = len(s.get("voice", "").split())
        total += w
        if not (wmin - 3 <= w <= wmax + 3):
            errs.append(f"story {k+1}: voice has {w} words (target {wmin}–{wmax})")
        if not s.get("headline") or len(s["headline"]) > 44:
            errs.append(f"story {k+1}: headline missing or >44 chars")
        if len(s.get("subline", "")) > 80:
            errs.append(f"story {k+1}: subline >80 chars")
        if len(s.get("kicker", "")) > 20 or not s.get("kicker"):
            errs.append(f"story {k+1}: kicker missing or >20 chars")
        if s.get("pillar") not in PILLARS:
            errs.append(f"story {k+1}: pillar must be one of {sorted(PILLARS)}")
        if s.get("region") not in REGIONS:
            errs.append(f"story {k+1}: region must be one of {sorted(REGIONS)}")
        cid = s.get("candidate_id")
        if not isinstance(cid, int) or not (0 <= cid < n_candidates):
            errs.append(f"story {k+1}: invalid candidate_id")
        elif cid in ids:
            errs.append(f"story {k+1}: candidate_id {cid} used twice")
        ids.add(cid)
    regional = sum(1 for s in st if s.get("region") in ("DE", "AT", "CH", "EU"))
    if regional < min(cfg["min_regional_stories"], len(st)):
        errs.append(f"only {regional} DE/AT/CH/EU stories – need {cfg['min_regional_stories']}")
    if total > cfg["max_total_words"] + 4:
        errs.append(f"total {total} words – max {cfg['max_total_words']} (keeps the video under 50 s)")
    for f in REQUIRED:
        if not plan.get(f):
            errs.append(f"missing field: {f}")
    if len(plan.get("youtube_title", "")) > 95:
        errs.append("youtube_title too long (max ~65 recommended, hard 95)")
    if not (8 <= len(plan.get("tags", [])) <= 20):
        errs.append("tags: give 12–15")
    return errs


def load_plan(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
