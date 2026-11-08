#!/usr/bin/env python3
"""
build_master.py — LEGACY. Rebuild a .docx/.pdf from a markdown master.

The master CV is now the file RESUME_INPUT points at in .env (a Word/PDF file
you edit directly), so nothing in the normal flow calls this any more. It is
kept for the old markdown-master route: pass --source explicitly.

`my_resume.md` was the editable source of truth for the master resume.
Edit it (add metrics, fix a date, reword a bullet), run this, and the .docx that
`tailor_resume.py` reads is regenerated from it.

    python build_master.py
    python build_master.py --check     # validate only, write nothing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tailor_resume import build_docx, build_pdf, parse_markdown, read_docx_text

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
DEFAULT_SOURCE = ENGINE_DIR / "_old_master" / "my_resume.md"
DEFAULT_TARGET = ENGINE_DIR / "_old_master" / "my_resume.docx"

# Text that must never survive into a resume you actually send.
PLACEHOLDER_PATTERNS = [
    (r"YOUR-HANDLE", "LinkedIn URL is still a placeholder"),
    (r"\bTODO\b", "a TODO marker is still in the text"),
    (r"\bTBD\b", "a TBD marker is still in the text"),
    (r"\[[^\]]*\byour\b[^\]]*\]", "a [your ...] placeholder is still in the text"),
    (r"\bXX+\b", "an XX placeholder is still in the text"),
]


def check_placeholders(markdown: str) -> list[str]:
    warnings = []
    for pattern, message in PLACEHOLDER_PATTERNS:
        for match in re.finditer(pattern, markdown, flags=re.IGNORECASE):
            line_no = markdown[: match.start()].count("\n") + 1
            warnings.append(f"line {line_no}: {message} ({match.group(0)!r})")
    return warnings


def main(argv: list[str] | None = None) -> int:
    import logging

    for noisy in ("fontTools", "fontTools.subset", "fontTools.ttLib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--check", action="store_true", help="Validate only; write nothing.")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"ERROR: {args.source} not found.")
        return 1

    markdown = args.source.read_text(encoding="utf-8")
    blocks = parse_markdown(markdown)
    if not blocks:
        print(f"ERROR: {args.source.name} produced no content.")
        return 1

    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    print(f"Parsed {args.source.name}: {len(blocks)} blocks ({summary})")

    if counts.get("h1", 0) != 1:
        print(f"WARNING: expected exactly one '# Name' heading, found {counts.get('h1', 0)}.")

    warnings = check_placeholders(markdown)
    for warning in warnings:
        print(f"WARNING: {warning}")

    if args.check:
        print("Check only — nothing written.")
        return 1 if warnings else 0

    try:
        build_docx(blocks, args.target)
    except PermissionError:
        print(f"ERROR: cannot write {args.target.name} — close it in Word and retry.")
        return 1

    text = read_docx_text(args.target)
    print(f"Wrote {args.target.name} ({args.target.stat().st_size:,} bytes)")
    print(f"Read-back check: {len(text):,} characters over {len(text.splitlines())} lines")

    # A PDF of the master doubles as the always-available fallback for a job folder.
    pdf_target = args.target.with_suffix(".pdf")
    try:
        build_pdf(blocks, pdf_target)
        print(f"Wrote {pdf_target.name} ({pdf_target.stat().st_size:,} bytes)")
    except PermissionError:
        print(f"WARNING: cannot write {pdf_target.name} — close it in your PDF viewer.")
    except Exception as exc:
        print(f"WARNING: PDF generation failed ({exc}). The .docx is fine.")

    if warnings:
        print("\nFix the warnings above before sending anything generated from this master.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
