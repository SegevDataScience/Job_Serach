#!/usr/bin/env python3
"""
pick_from_ranked.py — Convert top-15 numbers to jobs_found.json indices and tailor CVs.

Usage:
    python pick_from_ranked.py 1           # Pick #1 from top 15
    python pick_from_ranked.py 1,3,5       # Pick multiple
    python pick_from_ranked.py 1-5         # Pick a range
"""

import json
import sys
from pathlib import Path
from personalized_ranking import rank_jobs

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent

# Import find_jobs for tailor logic
sys.path.insert(0, str(ENGINE_DIR))
from find_jobs import load_saved, parse_picks as parse_pick_spec

def main():
    if len(sys.argv) < 2:
        print("Usage: python pick_from_ranked.py <numbers>")
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

    # Parse the pick spec (1,3,5 format)
    picks = parse_pick_spec(spec, 15)  # Max 15 from top 15

    # Map top-15 picks to actual job indices in jobs_found.json
    selected_indices = []
    for pick_num in picks:
        if 1 <= pick_num <= len(ranked):
            # Find this job in the original all_jobs list
            selected_job = ranked[pick_num - 1]
            for idx, job in enumerate(all_jobs_data):
                if (job.get('company') == selected_job.get('company') and
                    job.get('title') == selected_job.get('title') and
                    job.get('url') == selected_job.get('url')):
                    selected_indices.append(idx + 1)  # 1-based for --pick
                    break

    if not selected_indices:
        print("ERROR: No matching jobs found.")
        sys.exit(1)

    # Convert to find_jobs.py format
    indices_str = ','.join(map(str, selected_indices))

    # Call find_jobs.py with these indices
    import subprocess
    result = subprocess.run(
        [sys.executable, "find_jobs.py", "--pick", indices_str],
        cwd=ENGINE_DIR
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
