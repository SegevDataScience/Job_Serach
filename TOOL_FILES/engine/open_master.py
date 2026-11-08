#!/usr/bin/env python3
"""
open_master.py — open (or check) the master CV that everything is tailored from.

The master lives wherever `RESUME_INPUT` in `.env` points — for Segev, the Word
file in OneDrive. Edit it there and the next tailoring run picks it up; there is
no build step.

    python open_master.py            # open it in its default app
    python open_master.py --check    # print one ASCII warning line if unusable
    python open_master.py --folder   # open the folder it lives in
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from master_cv import configured_master_path, resolve_master_path  # noqa: E402


def locate() -> Path:
    return resolve_master_path(configured_master_path())


def main(argv: list[str]) -> int:
    check = "--check" in argv
    folder_only = "--folder" in argv

    try:
        master = locate()
    except SystemExit as exc:
        if check:
            # ASCII only: this line is echoed by START.bat in a console.
            print("Master CV not found - fix RESUME_INPUT in .env")
            return 0
        print(exc)
        return 1

    if check:
        return 0

    # Prefer the .docx twin: that is the one you can actually edit.
    editable = master.with_suffix(".docx")
    target = editable if editable.exists() else master

    print(f"Master CV: {target}")
    os.startfile(str(target.parent) if folder_only else str(target))  # noqa: S606 - Windows shell open
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
