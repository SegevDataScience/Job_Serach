#!/usr/bin/env python3
"""
publish_github.py — push the tool's code (only the code) to GitHub.

The local project's git history contains personal files (the CV, the
applications tracker), and the GitHub repo is public. So publishing never pushes
this folder's history: it keeps a separate clone of the GitHub repo in
%LOCALAPPDATA%\\JobSearch\\publish, copies a fixed whitelist of code files into
it, refuses to continue if anything personal slipped in, and pushes one commit.

Run:  python publish_github.py           (or the "עדכן GitHub" button in the page)
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_URL = "https://github.com/SegevDataScience/Job_Serach.git"
ENGINE_DIR = Path(__file__).resolve().parent
PROJECT = ENGINE_DIR.parent.parent
CLONE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "JobSearch" / "publish" / "Job_Serach"

# What goes to GitHub. Anything else never leaves the machine.
WHITELIST = [
    "START.bat", "WORKFLOW.md", "README.md",
    "TOOL_FILES/.env.example",
    "TOOL_FILES/engine/*.py",
    "TOOL_FILES/engine/adapters/*.py",
    "TOOL_FILES/engine/web/*.html",
    "TOOL_FILES/engine/job_search_config.json",
    "TOOL_FILES/engine/requirements.txt",
]
# Repo-only files that publishing must not delete.
KEEP_IN_REPO = {".gitignore"}

FORBIDDEN_NAME = re.compile(r"(^|/)\.env$|\.(xlsx|pdf|docx)$|candidate_memory|skill_cache|first_seen|manual_jobs|"
                            r"jobs_found|cover_letters/|\.cv_skills|web_app\.log", re.I)
FORBIDDEN_TEXT = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|\b05\d-?\d{7}\b", re.I)


def personal_strings() -> list[str]:
    """Email addresses and phone numbers that appear in the master CV, read at run time
    so this file itself never has to contain them."""
    try:
        import skill_match

        text = skill_match.cv_text()
    except Exception:  # no CV reachable: the generic patterns still apply
        return []
    found = set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    found |= {re.sub(r"\D", "", p) for p in re.findall(r"\+?\d[\d\s-]{8,14}\d", text) if len(re.sub(r"\D", "", p)) >= 9}
    return sorted(found)


def git(*args: str, cwd: Path = CLONE, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                            errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def wanted_files() -> list[str]:
    files = []
    for pattern in WHITELIST:
        files += [str(p.relative_to(PROJECT)).replace("\\", "/") for p in PROJECT.glob(pattern) if p.is_file()]
    return sorted(set(files))


def matches_whitelist(rel: str) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in WHITELIST)


def publish(message: str = "") -> str:
    CLONE.parent.mkdir(parents=True, exist_ok=True)
    if not (CLONE / ".git").exists():
        git("clone", REPO_URL, str(CLONE), cwd=CLONE.parent)
    else:
        git("pull", "--ff-only")

    files = wanted_files()
    # Mirror: copy the whitelist in, drop whitelisted files that no longer exist locally.
    for rel in files:
        target = CLONE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT / rel, target)
    for path in CLONE.rglob("*"):
        rel = str(path.relative_to(CLONE)).replace("\\", "/")
        if path.is_file() and not rel.startswith(".git/") and rel not in KEEP_IN_REPO \
                and matches_whitelist(rel) and rel not in files:
            path.unlink()

    git("add", "-A")
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line]
    if not staged:
        return "אין שינויים לפרסם: GitHub כבר מעודכן."

    # Last line of defence before anything leaves the machine.
    personal = personal_strings()
    for rel in staged:
        path = CLONE / rel
        if FORBIDDEN_NAME.search(rel):
            git("reset", "-q")
            raise RuntimeError(f"נעצר: הקובץ {rel} נראה אישי ולא יועלה.")
        content = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        compact = re.sub(r"[\s-]", "", content)  # a phone written with dashes/spaces still counts
        if FORBIDDEN_TEXT.search(content) or any(p in content or (p.isdigit() and p in compact) for p in personal):
            git("reset", "-q")
            raise RuntimeError(f"נעצר: בקובץ {rel} יש פרט אישי או מפתח. לא הועלה כלום.")

    if not git("config", "user.name", check=False):
        git("config", "user.name", "Job Search Tool")
        git("config", "user.email", "oofek14@gmail.com")
    summary = message or f"Update {datetime.now():%Y-%m-%d %H:%M}: " + ", ".join(Path(f).name for f in staged[:8]) \
        + (f" and {len(staged) - 8} more" if len(staged) > 8 else "")
    git("commit", "-q", "-m", summary + "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    git("push", "-q", "origin", "HEAD")
    return f"עודכן ב-GitHub: {len(staged)} קבצים ({git('rev-parse', '--short', 'HEAD')})."


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(publish(" ".join(sys.argv[1:])))
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)
