#!/usr/bin/env python3
"""
find_jobs_combined.py — the scan behind START.bat [2].

Two halves:
- find_jobs.py: the company ATS boards in job_search_config.json
  (Greenhouse, Lever, Ashby, Comeet, Workday).
- market_sources.py: keyword searches over the whole Israeli market
  (LinkedIn guest search + Drushim), so non-tech employers show up too.

Banks and insurers are dropped in both halves (exclude_companies in the
config). Roles already marked submitted in applications.xlsx are hidden.
The result goes to jobs_found.json next to START.bat, which is what
interactive_picker.py reads.
"""

import json
import math
import re
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from find_jobs import scan as scan_ats, drop_applied, report_hidden
from market_sources import scan_market
from personalized_ranking import rank_jobs

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
DATA_ROOT = PROJECT_ROOT.parent
CONFIG_PATH = ENGINE_DIR / "job_search_config.json"


LAST_DURATION = ENGINE_DIR / ".last_scan_seconds"
DEFAULT_DURATION = 180  # parallel scan with fast LinkedIn backoff, measured 2026-11-08 (2:52)


class ScanClock:
    """Prints "~N min left" once a minute while the scan runs.

    The estimate is the previous scan's real duration (saved at the end of
    each run), so it tracks whatever the sources actually cost on this machine.
    """

    def __init__(self) -> None:
        import threading
        import time

        self._time = time
        try:
            self.expected = float(LAST_DURATION.read_text())
        except (OSError, ValueError):
            self.expected = DEFAULT_DURATION
        self.start = time.monotonic()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick, daemon=True)

    def __enter__(self):
        print(f"[clock] Scan started — about {math.ceil(self.expected / 60)} min.\n", flush=True)
        self._thread.start()
        return self

    def _tick(self) -> None:
        while not self._stop.wait(60):
            elapsed = self._time.monotonic() - self.start
            left = math.ceil((self.expected - elapsed) / 60)
            done = f"{int(elapsed // 60)}:{int(elapsed % 60):02d} elapsed"
            if left >= 1:
                print(f"\n[clock] ~{left} min left  ({done})\n", flush=True)
            else:
                print(f"\n[clock] almost done...  ({done})\n", flush=True)

    def __exit__(self, exc_type, *_):
        self._stop.set()
        elapsed = self._time.monotonic() - self.start
        if exc_type is None:
            try:
                LAST_DURATION.write_text(f"{elapsed:.0f}")
            except OSError:
                pass
        print(f"\n[clock] Scan took {int(elapsed // 60)}:{int(elapsed % 60):02d}.", flush=True)


def _pair(job) -> tuple[str, str]:
    norm = lambda s: re.sub(r"[^\w]+", " ", (s or "").lower()).strip()
    return norm(job.company), norm(job.title)


def scan_all_sources(config_path: str | Path = None) -> tuple[list[dict], str]:
    """Scan ATS boards + the whole-market sources, merge, rank.

    Returns:
        Tuple of (ranked_jobs_list, combined_markdown)
    """
    config_path = Path(config_path) if config_path else CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    print("=" * 60)
    print("JOB SEARCH: COMPANY BOARDS + WHOLE MARKET")
    print("=" * 60)
    print()

    # The company boards (~2.5 min) and the market sources (~6 min, LinkedIn is
    # the long pole) hit different sites, so they run at the same time.
    import concurrent.futures

    print("Company ATS boards + whole market (LinkedIn, posts, Drushim, AllJobs, JobMaster, gov), in parallel — ~6 minutes")
    print("-" * 60)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        ats_future = pool.submit(scan_ats, config)
        market_future = pool.submit(scan_market, config)
        ats_jobs = ats_future.result()
        market_jobs = market_future.result()
    print(f"\n  ATS boards: {len(ats_jobs)} matching roles\n")

    # A role on a company board and on LinkedIn is one role; keep the board
    # copy, its link goes straight to the application form.
    seen = {_pair(job) for job in ats_jobs}
    market_new = [job for job in market_jobs if _pair(job) not in seen]

    # Postings older than max_age_days go; undated ones (Lever) stay. Government
    # tenders stay too: they run ~4 weeks and the sources return only open ones.
    max_age = config.get("max_age_days")
    fresh, stale = ats_jobs + market_new, 0
    if max_age:
        cutoff = (date.today() - timedelta(days=int(max_age))).isoformat()
        fresh = [job for job in fresh
                 if not job.updated or job.updated[:10] >= cutoff or job.ats in ("civil_service", "govil")]
        stale = len(ats_jobs) + len(market_new) - len(fresh)

    all_jobs, applied = drop_applied(fresh)

    print("\nResults:")
    print(f"  ATS boards:                    {len(ats_jobs)}")
    print(f"  Whole market (new):            {len(market_new)}")
    if max_age:
        print(f"  Older than {max_age} days (dropped):   {stale}")
    print(f"  Total:                         {len(all_jobs)}")
    report_hidden(applied)
    print()

    ranked_jobs = rank_jobs([asdict(job) for job in all_jobs])
    return ranked_jobs, _jobs_to_combined_markdown(ranked_jobs)


def _jobs_to_combined_markdown(jobs: list[dict]) -> str:
    """Generate markdown table showing all sources."""
    if not jobs:
        return "No jobs found."

    sorted_jobs = sorted(jobs, key=lambda j: j.get("relevance_score", 0), reverse=True)

    lines = [
        "| # | Company | Role | Source | Location | Score |",
        "|---|---------|------|--------|----------|-------|"
    ]

    for idx, job in enumerate(sorted_jobs[:100], 1):
        company = (job.get("company", "")[:18]).replace("|", "-")
        title = (job.get("title", "")[:35]).replace("|", "-")
        source = (job.get("ats", "")[:12]).replace("|", "-")
        location = (job.get("location", "")[:12]).replace("|", "-")
        score = round(job.get("personalized_score", job.get("relevance_score", 0)))

        lines.append(f"| {idx} | {company} | {title} | {source} | {location} | {score} |")

    if len(sorted_jobs) > 100:
        lines.append(f"| … | *{len(sorted_jobs) - 100} more jobs* | | | | |")

    return "\n".join(lines)


def create_selected_summary(job_numbers: str, jobs_file: str | Path = None) -> str:
    """
    Create a summary file of selected jobs based on numbers.

    Args:
        job_numbers: String like "1,3,5" or "1-3" or "2,4-6"
        jobs_file: Path to jobs_found.json

    Returns:
        Path to created summary file
    """
    jobs_file = Path(jobs_file) if jobs_file else DATA_ROOT / "jobs_found.json"

    # Load all jobs
    with open(jobs_file, 'r', encoding='utf-8') as f:
        all_jobs = json.load(f)

    # Parse job numbers (handle "1,3,5" and "1-3" formats)
    selected_indices = set()
    for part in job_numbers.split(','):
        part = part.strip()
        if '-' in part:
            start, end = map(int, part.split('-'))
            selected_indices.update(range(start - 1, end))  # Convert to 0-based index
        else:
            selected_indices.add(int(part) - 1)  # Convert to 0-based index

    # Get selected jobs
    selected_jobs = []
    for idx in sorted(selected_indices):
        if 0 <= idx < len(all_jobs):
            job = all_jobs[idx].copy()
            job['original_number'] = idx + 1  # Keep track of original number
            selected_jobs.append(job)

    # Create summary file
    summary_path = DATA_ROOT / "jobs_to_apply.json"
    summary_data = {
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "total_selected": len(selected_jobs),
        "selected_numbers": sorted(selected_indices),
        "jobs": selected_jobs
    }

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # Also create a human-readable version
    summary_txt = DATA_ROOT / "jobs_to_apply.txt"
    with open(summary_txt, 'w', encoding='utf-8') as f:
        f.write("SELECTED JOBS FOR APPLICATION\n")
        f.write("=" * 70 + "\n\n")
        for job in selected_jobs:
            num = job.get('original_number', '?')
            company = job.get('company', 'Unknown')
            title = job.get('title', 'Unknown')
            location = job.get('location', 'Unknown')
            url = job.get('url', 'No URL')
            f.write(f"#{num} {company} - {title}\n")
            f.write(f"    Location: {location}\n")
            f.write(f"    Link: {url}\n")
            f.write(f"    Source: {job.get('source', 'Unknown')}\n\n")

    return str(summary_path)


if __name__ == "__main__":
    import sys
    from datetime import date

    try:
        with ScanClock():
            all_jobs, combined_markdown = scan_all_sources()

        # Save JSON to TOOL_FILES/jobs_found.json
        output_path = DATA_ROOT / "jobs_found.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_jobs, f, ensure_ascii=False, indent=2)

        # Also save markdown for display
        md_path = DATA_ROOT / "jobs_found.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# Combined Job Search Results — {date.today().isoformat()}\n\n")
            f.write(f"Total: {len(all_jobs)} unique jobs\n\n")
            f.write(combined_markdown + "\n")

        print(combined_markdown)
        print(f"\nWrote to: {output_path}")

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)
