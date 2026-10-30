"""Berlin-time slot logic. GitHub cron runs in UTC and is often late, so the
workflow fires twice per slot (CET + CEST) and this module decides which slot
— if any — the current run belongs to."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo("Europe/Berlin")

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONAT = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
         "September", "Oktober", "November", "Dezember"]


def now_berlin() -> datetime:
    return datetime.now(TZ)


def slot_datetime(slot: dict, day: datetime) -> datetime:
    h, m = map(int, slot["time"].split(":"))
    return day.replace(hour=h, minute=m, second=0, microsecond=0)


def current_slot(now: datetime | None = None) -> tuple[dict, datetime] | None:
    now = now or now_berlin()
    win = settings()["build_window_minutes"]
    for slot in settings()["slots"]:
        for day_shift in (0, 1):
            t = slot_datetime(slot, now + timedelta(days=day_shift))
            if t - timedelta(minutes=win["before"]) <= now <= t + timedelta(minutes=win["after"]):
                return slot, t
    return None


def slot_by_id(slot_id: str, now: datetime | None = None) -> tuple[dict, datetime]:
    now = now or now_berlin()
    for slot in settings()["slots"]:
        if slot["id"] == slot_id:
            t = slot_datetime(slot, now)
            if t < now - timedelta(minutes=settings()["build_window_minutes"]["after"]):
                t += timedelta(days=1)
            return slot, t
    raise ValueError(f"unknown slot {slot_id}")


def german_date(d: datetime) -> str:
    return f"{WOCHENTAG[d.weekday()]}, {d.day}. {MONAT[d.month - 1]} {d.year}"


def german_date_short(d: datetime) -> str:
    return f"{d.day}. {MONAT[d.month - 1]}"
