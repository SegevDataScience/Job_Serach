#!/usr/bin/env python3
"""
find_jobs_social.py — Scan all social job sources in parallel.

Aggregates job listings from:
- LinkedIn posts (via scraping)
- Google Jobs
- Indeed (RSS + Web)
- Stack Overflow
- GitHub Jobs
- Israeli boards: Drushim, AllJobs, JobMaster
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.cache_manager import CacheManager
from engine.dedup_engine import DedupEngine
from engine.adapters.indeed_adapter import IndeedAdapter
from engine.adapters.github_jobs_adapter import GitHubJobsAdapter
from engine.adapters.stackoverflow_adapter import StackOverflowAdapter
from engine.adapters.linkedin_posts_adapter import LinkedInPostsAdapter
from engine.adapters.drushim_adapter import DrushimAdapter
from engine.adapters.alljobs_adapter import AllJobsAdapter
from engine.adapters.jobmaster_adapter import JobMasterAdapter

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent


def scan_social_sources(config: dict, cache_dir: str, parallel_workers: int = 4) -> tuple[list[dict], str]:
    """Scan all enabled social sources and return merged, deduplicated jobs.

    Args:
        config: Job search configuration dict with 'social_sources' section
        cache_dir: Directory for caching responses
        parallel_workers: Number of concurrent adapter workers

    Returns:
        Tuple of (jobs_list, markdown_table)
    """
    cache = CacheManager(cache_dir, default_ttl_hours=12)
    dedup = DedupEngine()

    adapters = []
    for source_config in config.get("social_sources", []):
        if not source_config.get("enabled"):
            continue

        source_name = source_config["name"]
        try:
            if source_name == "indeed":
                adapter = IndeedAdapter(
                    keywords_en=source_config.get("keywords_en", []),
                    keywords_he=source_config.get("keywords_he", [])
                )
            elif source_name == "github_jobs":
                adapter = GitHubJobsAdapter(
                    keywords_en=source_config.get("keywords_en", [])
                )
            elif source_name == "stackoverflow":
                adapter = StackOverflowAdapter(
                    keywords_en=source_config.get("keywords_en", [])
                )
            elif source_name == "linkedin_posts":
                adapter = LinkedInPostsAdapter(
                    keywords_en=source_config.get("keywords_en", []),
                    keywords_he=source_config.get("keywords_he", []),
                    cache_manager=cache
                )
            elif source_name == "drushim":
                adapter = DrushimAdapter(
                    keywords_he=source_config.get("keywords_he", []),
                    cache_manager=cache
                )
            elif source_name == "alljobs":
                adapter = AllJobsAdapter(
                    keywords_he=source_config.get("keywords_he", []),
                    cache_manager=cache
                )
            elif source_name == "jobmaster":
                adapter = JobMasterAdapter(
                    keywords_he=source_config.get("keywords_he", []),
                    cache_manager=cache
                )
            elif source_name == "google_jobs":
                from engine.adapters.google_jobs_adapter import GoogleJobsAdapter
                adapter = GoogleJobsAdapter(
                    keywords_en=source_config.get("keywords_en", []),
                    keywords_he=source_config.get("keywords_he", []),
                    location="Israel"
                )
            else:
                print(f"Warning: Unknown source '{source_name}'")
                continue

            adapters.append((source_name, adapter))
        except Exception as e:
            print(f"Error initializing {source_name}: {str(e)}")

    # Scan all sources in parallel
    jobs = []
    results_by_source = {}

    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {
            executor.submit(adapter.scan): (source_name, adapter)
            for source_name, adapter in adapters
        }

        for future in as_completed(futures):
            source_name, adapter = futures[future]
            try:
                source_jobs = future.result()
                results_by_source[source_name] = len(source_jobs)
                jobs.extend(source_jobs)
                print(f"✓ {source_name}: {len(source_jobs)} jobs found")
            except Exception as e:
                print(f"⚠ {source_name}: Failed ({str(e)})")
                results_by_source[source_name] = 0

    # Deduplicate
    unique_jobs = []
    for job in jobs:
        if dedup.add_job(job):
            unique_jobs.append(job)

    removed = len(jobs) - len(unique_jobs)
    if removed > 0:
        print(f"─ Duplicates removed: {removed}")
    print(f"─ Total unique: {len(unique_jobs)} jobs\n")

    markdown = _jobs_to_markdown(unique_jobs)
    return unique_jobs, markdown


def _jobs_to_markdown(jobs: list[dict]) -> str:
    """Convert jobs list to Markdown table sorted by relevance."""
    if not jobs:
        return "No jobs found."

    sorted_jobs = sorted(jobs, key=lambda j: j.get("relevance_score", 0), reverse=True)

    lines = [
        "| # | Company | Role | Location | Source | Score |",
        "|---|---------|------|----------|--------|-------|"
    ]

    for idx, job in enumerate(sorted_jobs[:50], 1):
        company = (job.get("company", "")[:20]).replace("|", "-")
        title = (job.get("title", "")[:40]).replace("|", "-")
        location = (job.get("location", "")[:15]).replace("|", "-")
        source = (job.get("source", "")[:12]).replace("|", "-")
        score = job.get("relevance_score", 0)

        lines.append(f"| {idx} | {company} | {title} | {location} | {source} | {score} |")

    if len(sorted_jobs) > 50:
        lines.append(f"| … | *{len(sorted_jobs) - 50} more jobs* | | | | |")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from datetime import date

    config_path = ENGINE_DIR / "job_search_config.json"
    cache_dir = ENGINE_DIR / ".cache"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        jobs, markdown = scan_social_sources(config, str(cache_dir))

        # Save JSON to jobs_found.json (START.bat expects this)
        output_path = PROJECT_ROOT / "jobs_found.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)

        # Also save markdown for display
        md_path = PROJECT_ROOT / "jobs_found.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# Social Job Search Results — {date.today().isoformat()}\n\n")
            f.write(f"Total: {len(jobs)} unique jobs\n\n")
            f.write(markdown + "\n")

        print(markdown)
        print(f"\nWrote to: {output_path}")

    except Exception as e:
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)
