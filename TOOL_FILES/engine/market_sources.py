#!/usr/bin/env python3
"""
market_sources.py — job searches that cover the whole Israeli market, not a
fixed list of tech companies.

    LinkedIn  the public "guest" job search (no login). Every sector: media,
              retail, industry, health, consulting, government contractors...
    Drushim   the JSON API behind drushim.co.il. Hebrew postings, staffing
              agencies, and the non-tech employers that never touch an ATS.

Both are keyword searches. Keywords live in job_search_config.json under
`market_sources`; results go through the same title / location / bank-and-
insurance filters as the ATS boards (find_jobs.score_job).

Verified working on 2026-10-02. Both are undocumented endpoints, so if one of
them starts returning 0 it has probably changed shape — the scan reports it
per source rather than failing.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from find_jobs import Job, html_to_text, score_job

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 30


def _get(url: str, *, accept: str = "text/html") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": accept})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


# ==========================================================================
# LinkedIn (guest job search)
# ==========================================================================

LINKEDIN_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_POSTING = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

_LI_CARD = re.compile(r'<div[^>]*class="[^"]*base-card[^"]*"[^>]*data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)</li>', re.S)
_LI_TITLE = re.compile(r'base-search-card__title[^>]*>(.*?)</h3>', re.S)
_LI_COMPANY = re.compile(r'base-search-card__subtitle[^>]*>(.*?)</h4>', re.S)
_LI_LOCATION = re.compile(r'job-search-card__location[^>]*>(.*?)</span>', re.S)
_LI_DATE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_TAGS = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", fragment or ""))).strip()


def _linkedin_page(keyword: str, start: int, days: int) -> list[Job]:
    query = urllib.parse.urlencode({
        "keywords": keyword,
        "location": "Israel",
        "f_TPR": f"r{days * 86400}",
        "start": start,
    })
    page = _get(f"{LINKEDIN_SEARCH}?{query}")
    jobs = []
    for job_id, body in _LI_CARD.findall(page):
        title = _LI_TITLE.search(body)
        company = _LI_COMPANY.search(body)
        location = _LI_LOCATION.search(body)
        posted = _LI_DATE.search(body)
        jobs.append(Job(
            company=_clean(company.group(1)) if company else "",
            title=_clean(title.group(1)) if title else "",
            location=_clean(location.group(1)) if location else "",
            url=f"https://www.linkedin.com/jobs/view/{job_id}/",
            ats="linkedin",
            slug="",
            job_id=job_id,
            updated=posted.group(1) if posted else "",
        ))
    return jobs


def scan_linkedin(settings: dict[str, Any], days: int = 30) -> list[Job]:
    pages = int(settings.get("pages_per_keyword", 10))
    found: list[Job] = []
    for keyword in settings.get("keywords", []):
        for page in range(pages):
            # LinkedIn answers 429 after ~7 quick requests and lets us back in about a second later
            # (measured 2026-11-08). The old fixed 20 s wait + skipping the page cost ~220 s per scan
            # and lost pages; now: short waits, doubling, and the same page is retried.
            batch, wait = None, 2.0
            for _attempt in range(5):
                try:
                    batch = _linkedin_page(keyword, page * 10, days)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code != 429:
                        break
                    time.sleep(wait)
                    wait *= 2
                except Exception:
                    break
            if batch is None:
                break
            found.extend(batch)
            if len(batch) < 10:
                break
            time.sleep(1.0)
    return found


# ==========================================================================
# Drushim (webapi.drushim.co.il)
# ==========================================================================

DRUSHIM_SEARCH = "https://webapi.drushim.co.il/api/jobs/search"
DRUSHIM_JOB = "https://webapi.drushim.co.il/api/jobs/job"


def _drushim_page(keyword: str, page: int) -> dict[str, Any]:
    """The API intermittently answers IsError with no results for a query that
    works a second later, so every page gets a few attempts."""
    query = urllib.parse.urlencode({"searchterm": keyword, "page": page})
    payload: dict[str, Any] = {}
    for _ in range(6):
        payload = json.loads(_get(f"{DRUSHIM_SEARCH}?{query}", accept="application/json"))
        if not payload.get("IsError"):
            return payload
        time.sleep(1.5)
    return payload


def _drushim_job(entry: dict[str, Any]) -> tuple[Job, str]:
    content = entry.get("JobContent") or {}
    info = entry.get("JobInfo") or {}
    company = (entry.get("Company") or {}).get("CompanyDisplayName") or ""
    cities = []
    for address in content.get("Addresses") or []:
        english = (address.get("CityEnglish") or "").strip()
        hebrew = (address.get("City") or "").strip()
        cities.append(f"{english} ({hebrew})" if english and hebrew else english or hebrew)
    location = "; ".join(dict.fromkeys(c for c in cities if c)) or "Israel"
    text = html_to_text(f"{content.get('Description') or ''}\n{content.get('Requirements') or ''}")
    job = Job(
        company=company.strip(),
        title=(content.get("Name") or content.get("FullName") or "").strip(),
        location=f"{location}, Israel",
        url="https://www.drushim.co.il" + (info.get("Link") or ""),
        ats="drushim",
        slug="",
        job_id=f"{entry.get('Code')}/{info.get('Hash') or ''}",
        updated=(info.get("DisplayDate") or info.get("Date") or "")[:10],
    )
    return job, text


def scan_drushim(settings: dict[str, Any]) -> list[tuple[Job, str]]:
    pages = int(settings.get("pages_per_keyword", 5))
    found: list[tuple[Job, str]] = []
    for keyword in settings.get("keywords", []):
        for page in range(1, pages + 1):
            try:
                payload = _drushim_page(keyword, page)
            except Exception:
                break
            entries = (payload.get("ResultList") or []) + (payload.get("ExtentionResultList") or [])
            found.extend(_drushim_job(entry) for entry in entries)
            if not entries or not payload.get("NextPageNumber") or page >= (payload.get("TotalPagesNumber") or 0):
                break
            time.sleep(0.5)
    return found


# ==========================================================================
# Entry points
# ==========================================================================


def _dedup_key(job: Job) -> tuple[str, str]:
    norm = lambda s: re.sub(r"[^\w]+", " ", (s or "").lower()).strip()
    return norm(job.company), norm(job.title)


def scan_market(config: dict[str, Any]) -> list[Job]:
    """Run every enabled market source, filter, and drop duplicates."""
    sources = config.get("market_sources", {})

    import extra_sources
    import israeli_boards

    days = int(config.get("max_age_days", 30))
    tasks = [
        ("LinkedIn", "linkedin", lambda s: [(job, "") for job in scan_linkedin(s, days)]),
        ("Drushim", "drushim", scan_drushim),
        ("LinkedIn posts", "linkedin_posts",
         lambda s: extra_sources.scan_linkedin_posts(s, days, config.get("locations", []),
                                                     config.get("title_keywords", []))),
        ("Civil service", "civil_service", lambda s: extra_sources.scan_civil_service()),
        ("gov.il", "govil", extra_sources.scan_govil),
        ("AllJobs", "alljobs", lambda s: israeli_boards.as_jobs(
            israeli_boards.scan_alljobs(s.get("keywords", []), int(s.get("pages_per_keyword", 3))), "alljobs")),
        ("JobMaster", "jobmaster", lambda s: israeli_boards.as_jobs(
            israeli_boards.scan_jobmaster(s.get("keywords", []), int(s.get("pages_per_keyword", 5))), "jobmaster")),
    ]
    tasks = [t for t in tasks if sources.get(t[1], {}).get("enabled")]

    # Every source is a different site, so they run side by side (one thread
    # each). Inside a source the requests stay sequential with their delays,
    # so no single site sees more traffic than before. Was ~10 min in series.
    def run(task):
        label, key, scan = task
        started = time.monotonic()
        try:
            pairs = scan(sources[key])
        except Exception as exc:
            print(f"  [SKIP] {label:<18} {type(exc).__name__}: {exc}", flush=True)
            return []
        print(f"  [OK]   {label:<18} {len(pairs):>4} postings  ({time.monotonic() - started:.0f}s)", flush=True)
        return [(key, job, text) for job, text in pairs]

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        results = list(pool.map(run, tasks))  # keeps source order, so dedup prefers LinkedIn as before
    candidates: list[tuple[str, Job, str]] = [c for chunk in results for c in chunk]

    seen: set[tuple[str, str]] = set()
    matches: list[Job] = []
    excluded = 0
    from find_jobs import excluded_sector

    for _, job, text in candidates:
        key = _dedup_key(job)
        if key in seen:
            continue
        seen.add(key)
        if excluded_sector(job.company, text, config):
            excluded += 1
            continue
        scored = score_job(job, config, text)
        if scored is not None:
            matches.append(scored)

    print(f"\n  {len(seen)} unique postings, {excluded} dropped as bank/insurance, "
          f"{len(matches)} match your titles and locations.")
    return matches


def fetch_description(source: str, job_id: str) -> str:
    """Full posting text for --pick / tailoring."""
    if source == "linkedin":
        page = _get(LINKEDIN_POSTING.format(job_id=job_id))
        match = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page, re.S)
        if not match:
            raise SystemExit("ERROR: LinkedIn did not return that posting (expired, or rate-limited).")
        return html_to_text(match.group(1))
    if source == "drushim":
        code, _, job_hash = job_id.partition("/")
        query = urllib.parse.urlencode({"jobCode": code, "jobHash": job_hash})
        payload = json.loads(_get(f"{DRUSHIM_JOB}?{query}", accept="application/json"))
        content = payload.get("JobContent") or payload.get("Job", {}).get("JobContent") or {}
        text = html_to_text(f"{content.get('Description') or ''}\n\n{content.get('Requirements') or ''}")
        if not text.strip():
            raise SystemExit("ERROR: Drushim did not return that posting's text.")
        return text
    raise SystemExit(f"ERROR: unknown market source {source!r}.")
