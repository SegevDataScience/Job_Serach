#!/usr/bin/env python3
"""
top_15.py - Show top 15 jobs ranked by personalized relevance score.

Usage:
    python top_15.py
"""

import json
from pathlib import Path
from personalized_ranking import print_ranked_jobs

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent

def main():
    # Try both locations for jobs_found.json
    jobs_file = None
    for path in [PROJECT_ROOT / "jobs_found.json", ENGINE_DIR / "jobs_found.json"]:
        if path.exists():
            jobs_file = path
            break

    if not jobs_file:
        print("\nNo jobs_found.json found.")
        print("Run a scan first: python TOOL_FILES/engine/find_jobs_combined.py\n")
        return

    with open(jobs_file, 'r', encoding='utf-8') as f:
        jobs = json.load(f)

    print(f"\nRanking {len(jobs)} jobs from {jobs_file.name}...\n")
    print_ranked_jobs(jobs, n=15)

if __name__ == "__main__":
    main()
