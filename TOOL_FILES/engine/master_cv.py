#!/usr/bin/env python3
"""
master_cv.py — locate the master CV everything is tailored from.

Deliberately dependency-light (pathlib + dotenv) so a quick "does the master
exist?" check does not have to import the Anthropic SDK, python-docx and fpdf.
Reading the file is tailor_resume's job; finding it is this module's.

The master lives wherever `RESUME_INPUT` in `.env` points, absolute or relative
to the project root. It does not have to sit inside this folder.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
DEFAULT_MASTER = "my_resume.docx"

# Paths copied out of OneDrive or Explorer often carry invisible right-to-left
# marks in the filename, so a path that looks correct can still miss by a few
# characters you cannot see. Matching ignores them.
_BIDI_MARKS = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _visible_name(name: str) -> str:
    return "".join(ch for ch in name if ch not in _BIDI_MARKS).strip().lower()


def configured_master_path(cli_value: Path | None = None) -> Path:
    """What .env (or --resume) says the master is, before checking it exists."""
    load_dotenv(PROJECT_ROOT / ".env")
    raw = cli_value or os.getenv("RESUME_INPUT") or DEFAULT_MASTER
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


def resolve_master_path(path: Path) -> Path:
    """The master CV on disk, tolerating invisible marks in the configured name."""
    if path.exists():
        return path

    if path.parent.is_dir():
        wanted = _visible_name(path.name)
        for candidate in sorted(path.parent.iterdir()):
            if candidate.is_file() and _visible_name(candidate.name) == wanted:
                return candidate

    raise SystemExit(
        f"ERROR: master CV not found at {path}\n"
        f"       Fix the RESUME_INPUT line in .env, or pass --resume <path>."
    )


def master_files() -> list[Path]:
    """The master CV as sendable files: what RESUME_INPUT points at, plus its
    .pdf/.docx twin in the same folder if there is one."""
    try:
        primary = resolve_master_path(configured_master_path())
    except SystemExit:
        return []

    found: list[Path] = []
    for suffix in (".pdf", ".docx"):
        candidate = primary if primary.suffix.lower() == suffix else primary.with_suffix(suffix)
        if candidate.exists():
            found.append(candidate)
    return found
