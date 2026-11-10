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


def is_single(plan: dict) -> bool:
    return plan.get("format") == "single"


def single_story(plan: dict) -> dict:
    """FOKUS plans carry one story; this gives the code a 'stories' entry like the headline format."""
    beats = plan.get("beats") or []
    return {"candidate_id": plan.get("candidate_id"), "pillar": plan.get("pillar"), "region": plan.get("region"),
            "kicker": plan.get("kicker", ""), "headline": plan.get("headline", ""), "highlight": plan.get("highlight", []),
            "voice": " ".join([plan.get("hook_voice", "")] + [b.get("voice", "") for b in beats] + [plan.get("loop_line", "")]),
            "subline": (beats[0].get("label", "") if beats else ""), "entities": plan.get("entities", [])}


def validate_single(plan: dict, n_candidates: int) -> list[str]:
    cfg = settings()["editorial"]
    lo, hi = cfg["single_words"]
    errs = []
    cid = plan.get("candidate_id")
    if not isinstance(cid, int) or not (0 <= cid < n_candidates):
        errs.append("invalid candidate_id")
    if plan.get("pillar") not in PILLARS:
        errs.append(f"pillar must be one of {sorted(PILLARS)}")
    if plan.get("region") not in REGIONS:
        errs.append(f"region must be one of {sorted(REGIONS)}")
    hs = plan.get("hook_screen", "")
    if not hs or len(hs) > 24:
        errs.append("hook_screen: 1–3 shocking words, max 24 chars (e.g. HEIZKOSTEN-SCHOCK!)")
    hv = plan.get("hook_voice", "")
    if not hv or len(hv.split()) > 8:
        errs.append("hook_voice: the shock itself, max 8 words (spoken within ~1.5 s)")
    beats = plan.get("beats") or []
    if not (3 <= len(beats) <= 4):
        errs.append("beats: 3–4 needed")
    for i, b in enumerate(beats):
        if not b.get("voice"):
            errs.append(f"beat {i+1}: voice missing")
        if not b.get("big") or len(b["big"]) > 14:
            errs.append(f"beat {i+1}: big (number/keyword on screen) missing or >14 chars")
        if len(b.get("label", "")) > 42:
            errs.append(f"beat {i+1}: label >42 chars")
    ll = plan.get("loop_line", "")
    if not ll or len(ll.split()) > 16:
        errs.append("loop_line: max 16 words, must lead back into the hook")
    total = len(single_story(plan)["voice"].split())
    if not (lo - 4 <= total <= hi + 4):
        errs.append(f"total voice {total} words (target {lo}–{hi} → 30–35 s)")
    if not plan.get("headline") or len(plan["headline"]) > 44:
        errs.append("headline missing or >44 chars")
    if not plan.get("kicker") or len(plan["kicker"]) > 20:
        errs.append("kicker missing or >20 chars")
    for f in REQUIRED:
        if f != "hook_text" and not plan.get(f):
            errs.append(f"missing field: {f}")
    if not (8 <= len(plan.get("tags", [])) <= 20):
        errs.append("tags: give 12–15")
    import re
    for f in ("facebook_caption_line1", "facebook_question"):
        if re.search(r"https?://|www\.|\b[\w-]+\.(de|com|net|org|at|ch)\b", plan.get(f, ""), re.I):
            errs.append(f"{f}: no website/link allowed in Facebook captions")
    return errs


def validate(plan: dict, n_candidates: int) -> list[str]:
    if is_single(plan):
        errs = validate_single(plan, n_candidates)
        if len(plan.get("youtube_title", "")) > 60:
            errs.append("youtube_title too long: max 60 characters, keyword within the first 40 (Shorts truncate ~40)")
        return errs + repeat_errors(plan)
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
    if len(plan.get("youtube_title", "")) > 60:
        errs.append("youtube_title too long: max 60 characters, keyword within the first 40 (Shorts truncate ~40)")
    import re
    for f in ("facebook_caption_line1", "facebook_question"):
        if re.search(r"https?://|www\.|\b[\w-]+\.(de|com|net|org|at|ch)\b", plan.get(f, ""), re.I):
            errs.append(f"{f}: no website/link allowed in Facebook captions")
    hv = plan.get("hook_voice", "")
    if hv and len(hv.split()) > 8:
        errs.append("hook_voice: max 8 words (must be spoken within ~1.5 seconds)")
    if not (8 <= len(plan.get("tags", [])) <= 20):
        errs.append("tags: give 12–15")
    return errs


# ---- growth 11 Nov 2026: repetition guard -------------------------------------------------
# Data 9–10 Nov: when the same person/story ran several times within a day (Nvidia 4×, Trump 4×),
# those repeats got 3–40 views and the whole channel's per-video reach halved. YouTube treats
# near-duplicate Shorts as repetitious content. So: one story / main person at most once per 24 h.
_STOP = set("""aber alle allen auch beim bereits damit dann dass dem den denn der des die dies diese dieser doch
durch eine einem einen einer eines etwa gegen hier heute ihre jetzt kann keine mehr muss nach neue neuen noch
nicht oder ohne schon sein seine sich sind soll sollen sowie über unter viel vom von vor wann warum was weil
weiter wenn werden wieder will wird wurde zwei drei vier fünf ersten soll droht deutschland europa welt
woche jahr jahre millionen milliarden prozent haben gibt macht gemacht erste erster reichen sagt sagen
kommt zeigt fordert warnt plant""".split())


def _tokens(text: str) -> set:
    import re
    out = set()
    for w in re.findall(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß-]+", text or ""):
        for part in [w] + w.split("-"):
            p = part.lower().strip("-")
            if len(p) >= 4 and p not in _STOP:
                out.add(p)
                if p.endswith("s") and len(p) > 5:
                    out.add(p[:-1])   # genitive: Trumps → trump
    return out


def repeat_errors(plan: dict, hours: int = 24) -> list[str]:
    """Error if the plan's (lead) story shares ≥2 key words with any video published in the last `hours`."""
    if (plan.get("new_development") or "").strip():
        return []   # explicitly declared hard new fact (must be named in the plan)
    from datetime import datetime, timedelta, timezone
    from . import state
    if is_single(plan):
        mine = " ".join([plan.get("youtube_title", ""), plan.get("headline", ""), plan.get("hook_screen", "")])
    else:
        st = (plan.get("stories") or [{}])[0]
        mine = " ".join([plan.get("youtube_title", ""), st.get("headline", "")])
    mt = _tokens(mine)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    errs = []
    for r in state.load()["runs"]:
        if r.get("created", "") < cutoff or r.get("title", "") == plan.get("youtube_title", ""):
            continue
        theirs = " ".join([r.get("title", "")] + [x.get("headline", "") for x in (r.get("stories") or [])[:1]])
        common = mt & _tokens(theirs)
        if len(common) >= 2:
            errs.append(f"repeat: shares {sorted(common)} with '{r.get('title', '')}' ({r.get('date')} {r.get('slot')}) "
                        f"– pick a different story (max once per 24 h) or, only for a hard new fact, set "
                        f"\"new_development\" to that fact")
    return errs[:2]


def load_plan(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ API fallback editor
def api_key() -> str | None:
    import os
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")


def _api_call(system: str, messages: list[dict], model: str, max_tokens: int = 6000) -> str:
    import requests
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": api_key(), "anthropic-version": "2023-06-01",
                               "content-type": "application/json"},
                      json={"model": model, "max_tokens": max_tokens, "system": system, "messages": messages},
                      timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic API {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def _extract_json(text: str) -> dict:
    import re
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def write_plan_via_api(queue_dir: Path) -> dict:
    """Fallback news desk (used only when the Claude scheduled task could not run, e.g. usage
    limit): the same editorial brief (docs/EDITOR_GUIDE.md) sent to the Anthropic API."""
    from .config import ROOT
    guide = (ROOT / "docs" / "EDITOR_GUIDE.md").read_text(encoding="utf-8")
    # comment handling is not part of the fallback
    if "## Step 0" in guide:
        a = guide.index("## Step 0")
        b = guide.index("## ", a + 5)
        guide = guide[:a] + guide[b:]
    perf = ROOT / "state" / "performance.md"
    cdata = json.loads((queue_dir / "candidates.json").read_text(encoding="utf-8"))
    model = settings()["editorial"].get("api_model", "claude-sonnet-5-5")
    system = (guide + "\n\nYou write ONLY the plan.json content. Output a single valid JSON object, nothing else. "
              "Include hook_voice.")
    fmt = cdata.get("slot", {}).get("format", "headlines")
    user = (("THIS SLOT USES THE FOKUS FORMAT (format=single) – write the FOKUS plan.json.\n\n" if fmt == "single"
             else "THIS SLOT USES THE HEADLINE FORMAT (4 stories).\n\n") +
            "candidates.json:\n" + json.dumps(cdata, ensure_ascii=False)[:120_000] +
            ("\n\nstate/performance.md:\n" + perf.read_text(encoding="utf-8")[:6000] if perf.exists() else ""))
    messages = [{"role": "user", "content": user}]
    last = ""
    for _ in range(3):
        raw = _api_call(system, messages, model)
        try:
            plan = _extract_json(raw)
            errs = validate(plan, len(cdata["candidates"]))
        except Exception as e:
            errs = [f"invalid JSON: {e}"]
        if not errs:
            (queue_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
            return plan
        last = "; ".join(errs)
        print("  api plan retry:", last)
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Fix these problems and output the complete JSON again: " + last}]
    raise RuntimeError("API editor failed: " + last)
