"""Shared continuous WR ownership for player profiles and Hall of Fame totals."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .database import utc

MICROSECOND = timedelta(microseconds=1)
DAY_US = 86_400_000_000


def merge_wr_reigns(history, now):
    """Merge adjacent ownership only for the same player and leaderboard."""
    if now.tzinfo is None:
        raise ValueError("WR evaluation time must include a timezone")
    now = now.astimezone(timezone.utc)
    intervals = defaultdict(list)
    for row in history:
        start = datetime.fromisoformat(row["wr_started_at"]).astimezone(timezone.utc)
        if start > now:
            continue
        end = datetime.fromisoformat(row["wr_ended_at"]).astimezone(timezone.utc) if row["wr_ended_at"] else None
        key = row["player_key"], row["track_id"], row["category_id"], row["board_key"]
        intervals[key].append({
            "start": start, "end": min(end, now) if end else now,
            "ongoing": end is None or end > now,
            "records": [{"run_id": row["id"], "source_url": row["source_url"]}],
        })

    result = {}
    for key, performances in sorted(intervals.items()):
        reigns = []
        for performance in sorted(performances, key=lambda r: (r["start"], r["end"])):
            if reigns and performance["start"] <= reigns[-1]["end"]:
                reigns[-1]["end"] = max(reigns[-1]["end"], performance["end"])
                reigns[-1]["ongoing"] |= performance["ongoing"]
                reigns[-1]["records"].extend(performance["records"])
            else:
                reigns.append(performance)
        result[key] = [{
            "started_at": utc(r["start"].isoformat()),
            "ended_at": None if r["ongoing"] else utc(r["end"].isoformat()),
            "counted_until": utc(r["end"].isoformat()),
            "duration_us": (r["end"] - r["start"]) // MICROSECOND,
            "records": r["records"],
        } for r in reigns]
    return result


def summarize_wr_reigns(reigns, dates_complete=True):
    """Public profile statistics; unknown chronology is not a zero-day history."""
    if not dates_complete:
        return {
            "dates_complete": False, "total_duration_us": None, "total_days": None,
            "longest_reign_days": None, "current_reign_days": None,
            "reign_count": None, "reigns": [],
        }
    total_us = sum(r["duration_us"] for r in reigns)
    longest_us = max((r["duration_us"] for r in reigns), default=0)
    current_us = sum(r["duration_us"] for r in reigns if r["ended_at"] is None)
    return {
        "dates_complete": True, "total_duration_us": total_us, "total_days": total_us / DAY_US,
        "longest_reign_days": longest_us / DAY_US, "current_reign_days": current_us / DAY_US,
        "reign_count": len(reigns), "reigns": [dict(r, days=r["duration_us"] / DAY_US) for r in reigns],
    }
