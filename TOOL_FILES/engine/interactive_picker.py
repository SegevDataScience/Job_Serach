#!/usr/bin/env python3
"""
interactive_picker.py — Interactive job selection (concise UI).

Shows top 15 and lets you select which ones to apply for.
Saves directly to applications.xlsx tracker.
"""

import json
from pathlib import Path
from datetime import datetime
from personalized_ranking import rank_jobs

try:
    from openpyxl import load_workbook, Workbook
except ImportError:
    load_workbook = None
    Workbook = None

try:
    # The Windows console has no bidi support: Hebrew prints back to front.
    # get_display() reorders a line into visual order so it reads correctly.
    from bidi import get_display
except ImportError:
    def get_display(text):
        return text

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent.parent  # Go up to JOB_SEARCH root

def main():
    # Load and rank jobs
    jobs_file = PROJECT_ROOT / "jobs_found.json"
    if not jobs_file.exists():
        print("ERROR: jobs_found.json not found. Run a scan first.")
        return

    with open(jobs_file, 'r', encoding='utf-8') as f:
        all_jobs_data = json.load(f)

    ranked = rank_jobs(all_jobs_data)

    # Opening START.bat does not scan; say how old the list on screen is.
    scanned = datetime.fromtimestamp(jobs_file.stat().st_mtime)
    hours = (datetime.now() - scanned).total_seconds() / 3600

    # Display top 15 - concise
    print("\n" + "=" * 105)
    print("TOP 15 - SELECT WHICH TO APPLY FOR")
    print(f"Last scan: {scanned:%d/%m/%Y %H:%M}  ({hours:.0f} hours ago, {len(all_jobs_data)} jobs)")
    if hours > 24:
        print("!! This list is more than a day old. Choose [2] Re-scan below for fresh jobs (~10 min).")
    print("=" * 105)
    print()

    jobs_display = []
    for idx, job in enumerate(ranked[:15], 1):
        score = job.get('personalized_score', 0)
        company = job.get('company', 'Unknown')[:15]
        title = job.get('title', 'Unknown')[:60]
        source = {'linkedin': 'LinkedIn', 'drushim': 'Drushim'}.get(job.get('ats', ''), '')

        jobs_display.append({
            'idx': idx,
            'company': company,
            'title': title,
            'score': score,
            'full_job': job
        })

        # Fit level emoji
        if score >= 75:
            fit = "⭐"
        elif score >= 65:
            fit = "✅"
        elif score >= 55:
            fit = "👍"
        else:
            fit = "•"

        print(f"[{idx:2d}] {fit}  {score:4.0f}/100  | {get_display(company):15} | {get_display(title)}"
              + (f"  ({source})" if source else ""))

    print("=" * 105)
    print("\n  Format: 1  or  1,3,5  or  1-5  or  Enter to skip")
    print()

    while True:
        try:
            selection_str = input("Enter job numbers: ").strip()

            if not selection_str:
                print("Skipped.")
                return

            # Parse selection
            selected_indices = []
            for part in selection_str.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    selected_indices.extend(range(start, end + 1))
                else:
                    selected_indices.append(int(part))

            # Validate
            selected_indices = list(set(selected_indices))
            selected_indices = [i for i in selected_indices if 1 <= i <= 15]

            if not selected_indices:
                print("Invalid. Try: 1  or  1,3,5  or  1-5")
                continue

            break
        except (ValueError, IndexError):
            print("Invalid. Try: 1  or  1,3,5  or  1-5")
            continue

    # Collect selected jobs and save to tracker
    selected_jobs = []
    print("\n" + "=" * 105)
    print("SELECTED - ADDED TO APPLICATIONS TRACKER")
    print("=" * 105)
    print()

    timestamp = datetime.now().strftime("%Y-%m-%d")

    for rank, idx in enumerate(sorted(selected_indices), 1):
        job_display = jobs_display[idx - 1]
        job_full = job_display['full_job']
        url = job_full.get('url', '')
        company = job_full.get('company', '')
        title = job_full.get('title', '')
        score = job_display['score']

        selected_jobs.append({
            "company": company,
            "title": title,
            "location": job_full.get('location', ''),
            "score": score,
            "link": url,
        })

        print(f"{rank}. [{score:.0f}/100] {get_display(company)} - {get_display(title)}")
        print(f"   {url}")
        print()

    # Save to applications.xlsx tracker
    tracker_file = PROJECT_ROOT / "applications.xlsx"

    if load_workbook:
        try:
            if tracker_file.exists():
                wb = load_workbook(tracker_file)
                ws = wb.active
            else:
                wb = Workbook()
                ws = wb.active
                ws['A1'] = 'נוצר'
                ws['B1'] = 'חברה'
                ws['C1'] = 'תפקיד'
                ws['D1'] = 'מיקום'
                ws['E1'] = 'קישור להגשה'
                ws['F1'] = 'הוגש?'
                ws['G1'] = 'תאריך הגשה'
                ws['H1'] = 'הערות'

            # Add selected jobs to tracker
            for job in selected_jobs:
                next_row = ws.max_row + 1
                ws[f'A{next_row}'] = timestamp
                ws[f'B{next_row}'] = job['company']
                ws[f'C{next_row}'] = job['title']
                ws[f'D{next_row}'] = job['location']
                ws[f'E{next_row}'] = job['link']
                ws[f'F{next_row}'] = 'לא'
                ws[f'G{next_row}'] = ''
                ws[f'H{next_row}'] = ''

            wb.save(tracker_file)
            print("=" * 105)
            print(f"✅ Updated: applications.xlsx ({len(selected_jobs)} jobs added)")
            print(f"   File: {tracker_file.absolute()}")
            print("\n📋 Next: Open applications.xlsx → Select jobs to tailor → Use [3] Manual tailor")
            print("=" * 105)
        except Exception as e:
            import traceback
            print("=" * 105)
            print(f"❌ ERROR updating tracker: {e}")
            print(f"   Path: {tracker_file.absolute()}")
            traceback.print_exc()
            print("=" * 105)
    else:
        print("⚠️ openpyxl not available")

if __name__ == "__main__":
    main()
