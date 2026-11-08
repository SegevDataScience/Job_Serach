#!/usr/bin/env python3
"""
create_submission_list.py — Display jobs selected from top 15 in a submission-ready format.

Usage:
    python create_submission_list.py 1           # Show job #1 from top 15
    python create_submission_list.py 1,3,5       # Show multiple
    python create_submission_list.py 1-5         # Show a range
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from personalized_ranking import rank_jobs
from find_jobs import parse_picks

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent

def main():
    if len(sys.argv) < 2:
        print("Usage: python create_submission_list.py <numbers>")
        print("  Examples: 1  or  1,3,5  or  1-5")
        sys.exit(1)

    spec = sys.argv[1]

    # Load all jobs
    jobs_file = PROJECT_ROOT / "jobs_found.json"
    if not jobs_file.exists():
        print(f"ERROR: {jobs_file} not found. Run a scan first.")
        sys.exit(1)

    with open(jobs_file, 'r', encoding='utf-8') as f:
        all_jobs_data = json.load(f)

    # Rank them
    ranked = rank_jobs(all_jobs_data)

    # Parse the pick spec
    picks = parse_picks(spec, len(ranked))

    # Filter to max 15
    picks = [p for p in picks if 1 <= p <= 15]

    if not picks:
        print("ERROR: No valid job numbers from top 15.")
        sys.exit(1)

    print("\n" + "=" * 110)
    print(f"SELECTED JOBS FOR MANUAL SUBMISSION ({len(picks)} jobs)")
    print("=" * 110)
    print()

    # Prepare data for saving
    selected_jobs_data = []
    for pick_idx, pick_num in enumerate(picks, 1):
        job = ranked[pick_num - 1]
        selected_jobs_data.append({
            "rank": pick_idx,
            "position": pick_num,
            "company": job.get('company', 'Unknown'),
            "title": job.get('title', 'Unknown'),
            "location": job.get('location', 'Not specified'),
            "link": job.get('url', 'No URL'),
            "score": job.get('personalized_score', 0)
        })

        print(f"{pick_idx}. {job.get('company', 'Unknown')} — {job.get('title', 'Unknown')}")
        print(f"   Location: {job.get('location', 'Not specified')}")
        print(f"   Link: {job.get('url', 'No URL')}")
        print(f"   Score: {job.get('personalized_score', 0):.0f}/100")
        print()

    # Save to file
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    submission_file = PROJECT_ROOT / f"selected_jobs_{timestamp}.json"

    with open(submission_file, 'w', encoding='utf-8') as f:
        json.dump(selected_jobs_data, f, ensure_ascii=False, indent=2)

    print("=" * 110)
    print(f"✅ SAVED: {submission_file.name}")
    print()
    print("NEXT STEPS:")
    print("  1. Review the jobs above")
    print("  2. Click each link and read the full job description")
    print("  3. Copy the full description into: TOOL_FILES/engine/job_description.txt")
    print("  4. Run: python TOOL_FILES/engine/find_jobs.py --manual")
    print("  5. A tailored CV will be created in: applications/YYYY-MM-DD__company__role/")
    print("=" * 110)
    print()

if __name__ == "__main__":
    main()
