#!/usr/bin/env python3
"""
tracker.py — one Excel file instead of a folder per application.

`applications.xlsx` in the project root is the whole record: one row per job,
with the apply link, the date the row was created, and a column you set to
mark whether you actually submitted. The CV you send is always the same one —
your master in OneDrive — so nothing has to be generated per job.

The file is yours to edit. A scan only ever appends rows it has never seen
(matched on the apply link) and never touches a row you have already filled in.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
except ModuleNotFoundError:  # pragma: no cover - environment guard
    raise SystemExit(
        "ERROR: the tracker needs openpyxl. Install it with:\n"
        "       python -m pip install -r engine/requirements.txt"
    ) from None

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
# The live tracker is the one next to START.bat, which interactive_picker.py
# also writes; TOOL_FILES\applications.xlsx is a stale leftover.
TRACKER_PATH = PROJECT_ROOT.parent / "applications.xlsx"
SHEET_TITLE = "הגשות"

# (header, column width). The order here is the order in the sheet.
COLUMNS: list[tuple[str, int]] = [
    ("נוצר", 12),
    ("חברה", 20),
    ("תפקיד", 46),
    ("מיקום", 22),
    ("קישור להגשה", 52),
    ("הוגש?", 10),
    ("תאריך הגשה", 14),
    ("הערות", 34),
]
URL_COL = 5
STATUS_COL = 6
NOT_SUBMITTED = "לא"
SUBMITTED = "כן"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
LINK_FONT = Font(color="0563C1", underline="single")


def _normalise(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _new_workbook() -> Workbook:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_TITLE
    sheet.sheet_view.rightToLeft = True

    for index, (header, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=1, column=index, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.column_dimensions[get_column_letter(index)].width = width

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}1"

    # A dropdown, so the column stays two values and not five spellings of "yes".
    validation = DataValidation(type="list", formula1=f'"{SUBMITTED},{NOT_SUBMITTED}"', allow_blank=True)
    validation.error = "כן או לא"
    sheet.add_data_validation(validation)
    letter = get_column_letter(STATUS_COL)
    validation.add(f"{letter}2:{letter}2000")
    return workbook


def load() -> tuple[Workbook, Any]:
    """The tracker, created on first use."""
    if TRACKER_PATH.exists():
        workbook = load_workbook(TRACKER_PATH)
        sheet = workbook[SHEET_TITLE] if SHEET_TITLE in workbook.sheetnames else workbook.active
        return workbook, sheet
    workbook = _new_workbook()
    return workbook, workbook.active


def save(workbook: Workbook) -> None:
    try:
        workbook.save(TRACKER_PATH)
    except PermissionError:
        raise SystemExit(
            f"ERROR: cannot write {TRACKER_PATH.name} — it is open in Excel.\n"
            f"       Close it and run this again; nothing was lost."
        ) from None


def existing_urls(sheet: Any) -> set[str]:
    found = set()
    for row in sheet.iter_rows(min_row=2, min_col=URL_COL, max_col=URL_COL):
        cell = row[0]
        url = cell.hyperlink.target if cell.hyperlink else cell.value
        if url:
            found.add(_normalise(str(url)))
    return found


def add_rows(entries: Iterable[dict[str, str]], check_content_hash: bool = False) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Append the jobs the tracker has not seen. Returns (added, already_there).

    Args:
        entries: Job entries to add
        check_content_hash: If True, also check for duplicates by content hash (title+company)
    """
    workbook, sheet = load()
    seen = existing_urls(sheet)
    seen_content_hashes = set()

    # Build set of existing content hashes if checking
    if check_content_hash:
        for row in sheet.iter_rows(min_row=2, min_col=2, max_col=3):
            company = row[0].value or ""
            title = row[1].value or ""
            if company and title:
                content_hash = _hash_job_content(company, title)
                seen_content_hashes.add(content_hash)

    added, skipped = [], []
    for entry in entries:
        key = _normalise(entry.get("url", ""))
        if key and key in seen:
            skipped.append(entry)
            continue

        # Check content hash if enabled
        if check_content_hash:
            company = entry.get("company", "")
            title = entry.get("title", "")
            if company and title:
                content_hash = _hash_job_content(company, title)
                if content_hash in seen_content_hashes:
                    skipped.append(entry)
                    continue
                seen_content_hashes.add(content_hash)

        seen.add(key)
        row = sheet.max_row + 1
        sheet.cell(row=row, column=1, value=entry.get("created") or date.today().isoformat())
        sheet.cell(row=row, column=2, value=entry.get("company", ""))
        sheet.cell(row=row, column=3, value=entry.get("title", ""))
        sheet.cell(row=row, column=4, value=entry.get("location", ""))

        link = sheet.cell(row=row, column=URL_COL, value=entry.get("url", ""))
        if entry.get("url"):
            link.hyperlink = entry["url"]
            link.font = LINK_FONT

        sheet.cell(row=row, column=STATUS_COL, value=entry.get("status") or NOT_SUBMITTED).alignment = Alignment(
            horizontal="center"
        )
        sheet.cell(row=row, column=7, value=entry.get("submitted_on", ""))
        sheet.cell(row=row, column=8, value=entry.get("note", ""))
        added.append(entry)

    if added:
        save(workbook)
    return added, skipped


def _hash_job_content(company: str, title: str) -> str:
    """Create a content hash for deduplication."""
    import hashlib
    content = f"{company.lower().strip()}|{title.lower().strip()}"
    return hashlib.md5(content.encode()).hexdigest()


def seed_from_folders(applications_dir: Path | None = None) -> list[dict[str, str]]:
    """Carry the folders you already prepared into the tracker, so the history
    is in one place. The folders themselves are left exactly as they are."""
    applications_dir = applications_dir or (PROJECT_ROOT / "applications")
    if not applications_dir.is_dir():
        return []

    entries = []
    for folder in sorted(applications_dir.iterdir()):
        jd = folder / "job_description.txt"
        if not folder.is_dir() or not jd.exists():
            continue
        header = jd.read_text(encoding="utf-8", errors="replace")[:1000]

        def field(name: str) -> str:
            match = re.search(rf"^{name}:\s*(.+)$", header, flags=re.MULTILINE)
            return match.group(1).strip() if match else ""

        created = folder.name[:10] if re.match(r"\d{4}-\d{2}-\d{2}", folder.name) else ""
        entries.append(
            {
                "created": created,
                "company": field("Company"),
                "title": field("Title"),
                "location": field("Location"),
                "url": field("Apply"),
                "note": f"תיקייה מותאמת קיימת: {folder.name}",
            }
        )
    return entries


def counts() -> tuple[int, int]:
    """(rows, rows marked submitted)."""
    if not TRACKER_PATH.exists():
        return 0, 0
    _, sheet = load()
    total = submitted = 0
    for row in sheet.iter_rows(min_row=2, min_col=1, max_col=STATUS_COL):
        if not any(cell.value for cell in row):
            continue
        total += 1
        if str(row[STATUS_COL - 1].value or "").strip() == SUBMITTED:
            submitted += 1
    return total, submitted
