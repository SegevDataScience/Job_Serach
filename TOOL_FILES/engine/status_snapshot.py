#!/usr/bin/env python3
"""
status_snapshot.py — refresh the automatic part of STATUS.md.

Run by a Claude Code SessionEnd hook (.claude/settings.local.json) at the end of
every session, and safe to run by hand. It only rewrites the block between the
AUTO markers; the hand-written sections above it (tasks, process, status) are
left exactly as they are.
"""

from __future__ import annotations

import collections
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
ROOT = ENGINE.parent.parent
STATUS = ROOT / "STATUS.md"
START, END = "<!-- AUTO:START -->", "<!-- AUTO:END -->"


def _scan() -> list[str]:
    path = ROOT / "jobs_found.json"
    if not path.exists():
        return ["- סריקה: עוד לא רצה"]
    jobs = json.loads(path.read_text(encoding="utf-8"))
    when = datetime.fromtimestamp(path.stat().st_mtime)
    by_src = collections.Counter(j.get("ats", "") for j in jobs)
    big = ", ".join(f"{k} {v}" for k, v in by_src.most_common(6))
    lines = [f"- סריקה אחרונה: {when:%d/%m/%Y %H:%M} · {len(jobs)} משרות ({big})"]
    try:
        secs = float((ENGINE / ".last_scan_seconds").read_text())
        lines.append(f"- משך הסריקה האחרונה: {int(secs // 60)}:{int(secs % 60):02d} דק'")
    except (OSError, ValueError):
        pass
    top = sorted(jobs, key=lambda j: -j.get("personalized_score", 0))[:5]
    if top:
        lines.append("- 5 הכי גבוהות (ציון תפקיד): " + "; ".join(f"{j.get('company', '')} — {j.get('title', '')[:40]}" for j in top))
    return lines


def _tracker() -> list[str]:
    try:
        sys.path.insert(0, str(ENGINE))
        import tracker

        if not tracker.TRACKER_PATH.exists():
            return ["- applications.xlsx: עוד לא נוצר"]
        _, sheet = tracker.load()
        statuses = [str(r[tracker.STATUS_COL - 1].value or "").strip() for r in sheet.iter_rows(min_row=2) if any(c.value for c in r)]
        sent = sum(1 for s in statuses if s == tracker.SUBMITTED)
        return [f"- applications.xlsx: {len(statuses)} שורות · {sent} הוגשו · {len(statuses) - sent} ממתינות"]
    except Exception as exc:  # the tracker open in Excel must not break the snapshot
        return [f"- applications.xlsx: לא נקרא ({type(exc).__name__})"]


def _config() -> list[str]:
    try:
        cfg = json.loads((ENGINE / "job_search_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sites = ", ".join(s["name"] for s in cfg.get("career_sites", []))
    return [f"- חברות בסריקה: {len(cfg.get('companies', []))} · חלון זמן: {cfg.get('max_age_days')} ימים",
            f"- אתרי קריירה לבדיקה ידנית ({len(cfg.get('career_sites', []))}): {sites}"]


def _github() -> list[str]:
    import os

    clone = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JobSearch" / "publish" / "Job_Serach"
    if not (clone / ".git").exists():
        return ["- GitHub: אין עותק פרסום מקומי"]
    out = subprocess.run(["git", "-C", str(clone), "log", "-1", "--format=%h %cd %s", "--date=format:%d/%m/%Y %H:%M"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [f"- GitHub (SegevDataScience/Job_Serach): {out.stdout.strip() or 'לא ידוע'}"]


def snapshot() -> str:
    lines = [START, f"## מצב אוטומטי (עודכן {datetime.now():%d/%m/%Y %H:%M})", "",
             *_scan(), *_tracker(), *_config(), *_github(), END]
    return "\n".join(lines)


def main() -> None:
    text = STATUS.read_text(encoding="utf-8") if STATUS.exists() else "# סטטוס — כלי חיפוש העבודה\n\n"
    block = snapshot()
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _m: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    STATUS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a hook must never fail loudly at session end
        print(f"status snapshot skipped: {exc}", file=sys.stderr)
