#!/usr/bin/env python3
"""
find_jobs.py — scan public ATS job boards for roles that match your profile,
then hand a chosen posting straight to tailor_resume.py.

    python find_jobs.py                 # scan -> jobs_found.md + jobs_found.json
    python find_jobs.py --list          # reprint the last scan, no network
    python find_jobs.py --verify        # which company slugs actually resolve
    python find_jobs.py --pick 3        # fetch posting #3, tailor, write apply link
    python find_jobs.py --pick 1,4,7    # several in one go
    python find_jobs.py --pick 3-6      # a range
    python find_jobs.py --pick 3 --no-tailor
    python find_jobs.py --manual        # tailor to job_description.txt instead
    python find_jobs.py --all           # include roles you already submitted

Every run writes into applications/YYYY-MM-DD__company__role, so applying to the
same role again later leaves the earlier attempt intact.

What it covers
--------------
Companies on **Greenhouse**, **Lever**, **Ashby**, **Comeet** or **Workday** —
boards that publish their openings without authentication. That is most
Israeli tech. Comeet has no open API, so its adapter reads the JSON the public
board page already ships; that is why a Comeet slug carries the board uid too.

The rest of the market — LinkedIn and Drushim keyword searches — lives in
market_sources.py and is run by find_jobs_combined.py (START.bat [2]), not by
this script on its own.

Banks and insurers are dropped everywhere (exclude_companies in the config).

What it does NOT cover
----------------------
AllJobs, JobMaster, gov.il, and employers that post neither on an ATS board
nor on LinkedIn/Drushim. Those still need a manual search.

Roles you have already submitted (the הוגש? column in applications.xlsx says כן)
are dropped from the listing. --all brings them back.

Edit `job_search_config.json` to change the company list or the filters.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
# The folder START.bat lives in. The scan results and applications.xlsx sit
# here, because that is where interactive_picker.py and the user look.
DATA_ROOT = PROJECT_ROOT.parent
CONFIG_PATH = ENGINE_DIR / "job_search_config.json"
RESULTS_JSON = DATA_ROOT / "jobs_found.json"
RESULTS_MD = DATA_ROOT / "jobs_found.md"
RUNS_DIR = PROJECT_ROOT / "applications"

USER_AGENT = "Mozilla/5.0 (compatible; resume-tailor/1.0; +local job search)"
TIMEOUT = 20
MAX_WORKERS = 8


# ==========================================================================
# HTTP
# ==========================================================================


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.URLError:
        # boards-api.greenhouse.io served a certificate for the wrong host on
        # 2026-11-07; api.greenhouse.io answers the same public Job Board API.
        if "://boards-api.greenhouse.io/" not in url:
            raise
        return fetch_json(url.replace("://boards-api.greenhouse.io/", "://api.greenhouse.io/"))


# ==========================================================================
# HTML -> text (stdlib only)
# ==========================================================================

_BLOCK_END = re.compile(r"</(p|div|li|ul|ol|h[1-6]|tr|section)\s*>", re.I)
_LIST_ITEM = re.compile(r"<li[^>]*>", re.I)
_LINE_BREAK = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = _LINE_BREAK.sub("\n", text)
    text = _LIST_ITEM.sub("\n- ", text)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = text.replace(" ", " ").replace("\r", "")
    text = _TRAILING_WS.sub("\n", text)
    text = _BLANK_RUN.sub("\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


# ==========================================================================
# Model
# ==========================================================================


@dataclass
class Job:
    company: str
    title: str
    location: str
    url: str
    ats: str
    slug: str
    job_id: str
    updated: str = ""
    score: int = 0
    leadership: bool = False
    matched: list[str] = field(default_factory=list)
    personalized_score: float = 0.0


# ==========================================================================
# ATS adapters
# ==========================================================================


def from_greenhouse(company: str, slug: str) -> list[Job]:
    payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    jobs = []
    for entry in payload.get("jobs", []):
        location = (entry.get("location") or {}).get("name", "") or ""
        jobs.append(
            Job(
                company=company,
                title=entry.get("title", "").strip(),
                location=location.strip(),
                url=entry.get("absolute_url", ""),
                ats="greenhouse",
                slug=slug,
                job_id=str(entry.get("id", "")),
                updated=(entry.get("updated_at") or "")[:10],
            )
        )
    return jobs


def _lever_api(slug: str) -> tuple[str, str]:
    # "eu:mobileye" lives on Lever's EU instance; the US API answers [] for it.
    if slug.startswith("eu:"):
        return "https://api.eu.lever.co", slug[3:]
    return "https://api.lever.co", slug


def from_lever(company: str, slug: str) -> list[Job]:
    host, board = _lever_api(slug)
    payload = fetch_json(f"{host}/v0/postings/{board}?mode=json")
    jobs = []
    for entry in payload if isinstance(payload, list) else []:
        categories = entry.get("categories") or {}
        jobs.append(
            Job(
                company=company,
                title=(entry.get("text") or "").strip(),
                location=(categories.get("location") or "").strip(),
                url=entry.get("hostedUrl", ""),
                ats="lever",
                slug=slug,
                job_id=str(entry.get("id", "")),
                updated=(datetime.fromtimestamp(entry["createdAt"] / 1000).date().isoformat()
                         if entry.get("createdAt") else ""),
            )
        )
    return jobs


def from_ashby(company: str, slug: str) -> list[Job]:
    payload = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = []
    for entry in payload.get("jobs", []):
        if entry.get("isListed") is False:
            continue
        jobs.append(
            Job(
                company=company,
                title=(entry.get("title") or "").strip(),
                location=(entry.get("location") or "").strip(),
                url=entry.get("jobUrl") or entry.get("applyUrl") or "",
                ats="ashby",
                slug=slug,
                job_id=str(entry.get("id", "")),
                updated=(entry.get("publishedAt") or "")[:10],
            )
        )
    return jobs


_COMEET_DATA = re.compile(r"COMPANY_POSITIONS_DATA\s*=\s*")


def _comeet_positions(slug: str) -> list[dict[str, Any]]:
    """Comeet has no open JSON API, but its public board page ships every
    posting as a JSON literal, so the board URL is all we need."""
    request = urllib.request.Request(
        f"https://www.comeet.com/jobs/{slug}",
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        page = response.read().decode("utf-8", "replace")
    match = _COMEET_DATA.search(page)
    if not match:
        raise ValueError("board page carried no positions (uid probably wrong)")
    payload, _ = json.JSONDecoder().raw_decode(page, match.end())
    return payload if isinstance(payload, list) else []


def from_comeet(company: str, slug: str) -> list[Job]:
    # slug is the two halves of the board URL: "thetaray/72.00F".
    jobs = []
    for entry in _comeet_positions(slug):
        location = entry.get("location") or {}
        jobs.append(
            Job(
                company=company,
                title=(entry.get("name") or "").strip(),
                location=(location.get("name") or "").strip(),
                url=entry.get("url_comeet_hosted_page") or entry.get("url_active_page") or "",
                ats="comeet",
                slug=slug,
                job_id=str(entry.get("uid", "")),
                updated=(entry.get("time_updated") or "")[:10],
            )
        )
    return jobs


def _workday_base(slug: str) -> tuple[str, str, str]:
    # slug is "tenant/wdN/site", e.g. "intel/wd1/External".
    tenant, wd, site = slug.split("/")
    return tenant, f"https://{tenant}.{wd}.myworkdayjobs.com", site


def from_workday(company: str, slug: str) -> list[Job]:
    """Workday boards have an unauthenticated JSON search behind the public
    careers page. Searching "Israel" keeps the global firms (Intel, NVIDIA...)
    to their Israeli roles; a posting listed as "3 Locations" is resolved from
    its detail page so the location filter still has something to read."""
    tenant, host, site = _workday_base(slug)
    api = f"{host}/wday/cxs/{tenant}/{site}"
    postings, offset, total = [], 0, 0
    while True:
        body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": offset,
                           "searchText": "Israel"}).encode()
        request = urllib.request.Request(
            f"{api}/jobs", data=body, method="POST",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            page = json.loads(response.read().decode("utf-8", "replace"))
        batch = page.get("jobPostings") or []
        postings.extend(batch)
        offset += 20
        # Workday reports the total on the first page only; later pages say 0.
        total = total or page.get("total") or 0
        if not batch or offset >= total or offset >= 400:
            break

    jobs = []
    for entry in postings:
        path = entry.get("externalPath") or ""
        location = entry.get("locationsText") or ""
        if re.fullmatch(r"\d+ Locations", location) and _title_wanted(entry.get("title", "")):
            try:
                info = fetch_json(f"{api}{path}").get("jobPostingInfo") or {}
                location = "; ".join([info.get("location") or ""] + (info.get("additionalLocations") or []))
            except Exception:
                pass
        jobs.append(
            Job(
                company=company,
                title=(entry.get("title") or "").strip(),
                location=location.strip(),
                url=f"{host}/{site}{path}",
                ats="workday",
                slug=slug,
                job_id=path,
                updated=_workday_posted(entry.get("postedOn") or ""),
            )
        )
    return jobs


def _workday_posted(text: str) -> str:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 5 Days Ago' / 'Posted 30+ Days Ago'
    -> an ISO date, so max_age_days can filter Workday postings too."""
    low = text.lower()
    if "today" in low:
        days = 0
    elif "yesterday" in low:
        days = 1
    else:
        match = re.search(r"(\d+)\+?\s*days?", low)
        if not match:
            return ""
        days = int(match.group(1)) + (1 if "+" in low else 0)
    return (date.today() - timedelta(days=days)).isoformat()


def _title_wanted(title: str) -> bool:
    """Cheap pre-filter so Workday detail pages are fetched only for titles the
    scan would keep anyway."""
    try:
        config = load_config()
    except SystemExit:
        return True
    low = f" {title.lower()} "
    return any(kw.lower() in low for kw in config["title_keywords"])


def from_smartrecruiters(company: str, slug: str) -> list[Job]:
    jobs, offset = [], 0
    while True:
        payload = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        content = payload.get("content") or []
        for entry in content:
            location = (entry.get("location") or {}).get("fullLocation") or ""
            jobs.append(
                Job(
                    company=company,
                    title=(entry.get("name") or "").strip(),
                    location=re.sub(r"(,\s*)+", ", ", location).strip(", "),
                    url=f"https://jobs.smartrecruiters.com/{slug}/{entry.get('id', '')}",
                    ats="smartrecruiters",
                    slug=slug,
                    job_id=str(entry.get("id", "")),
                    updated=(entry.get("releasedDate") or "")[:10],
                )
            )
        offset += 100
        if not content or offset >= (payload.get("totalFound") or 0):
            return jobs


_SF_JOB = re.compile(r"<Job>(.*?)</Job>", re.S)
_ISRAELI_PLACES = re.compile(
    r"Petah[- ]Tikva|Petach[- ]Tikva|Tel[- ]Aviv|Jerusalem|Kfar[- ]Saba|Netanya|Haifa|Modi'?in|"
    r"Herzliya|Ramat[- ]Gan|Rehovot|Airport City|Or Yehuda|Kiryat|Migdal Haemek|Beer[- ]Sheva|"
    r"Ashdod|Yokneam|Israel|ישראל", re.I)


def _sf_field(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return html.unescape(match.group(1)).strip() if match else ""


def _sf_listing(slug: str) -> list[str]:
    # slug is "host/companyId", e.g. "career2.successfactors.eu/1080030P".
    host, company_id = slug.split("/")
    request = urllib.request.Request(
        f"https://{host}/career?company={company_id}&career_ns=job_listing_summary&resultType=XML",
        headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        return _SF_JOB.findall(response.read().decode("utf-8", "replace"))


def from_successfactors(company: str, slug: str) -> list[Job]:
    """SAP SuccessFactors' public XML feed (Teva, Tower, ICL). It carries no
    location field, so the location is the first Israeli place the
    description names; postings that name none are left without one and the
    location filter drops them."""
    host, company_id = slug.split("/")
    jobs = []
    for block in _sf_listing(slug):
        place = _ISRAELI_PLACES.search(_sf_field(block, "Job-Description"))
        posted = _sf_field(block, "Posted-Date")  # MM/DD/YYYY
        try:
            posted = datetime.strptime(posted, "%m/%d/%Y").date().isoformat()
        except ValueError:
            posted = ""
        req_id = _sf_field(block, "ReqId")
        jobs.append(
            Job(
                company=company,
                title=_sf_field(block, "JobTitle"),
                location=f"{place.group(0)}, Israel" if place else "",
                url=f"https://{host}/career?company={company_id}&career_job_req_id={req_id}&career_ns=job_listing",
                ats="successfactors",
                slug=slug,
                job_id=req_id,
                updated=posted,
            )
        )
    return jobs


ADAPTERS = {
    "smartrecruiters": from_smartrecruiters,
    "successfactors": from_successfactors,
    "greenhouse": from_greenhouse,
    "lever": from_lever,
    "ashby": from_ashby,
    "comeet": from_comeet,
    "workday": from_workday,
}


def fetch_company(entry: dict[str, str]) -> tuple[str, list[Job], str]:
    """Return (company name, jobs, error message)."""
    name, ats, slug = entry.get("name", "?"), entry.get("ats", ""), entry.get("slug", "")
    adapter = ADAPTERS.get(ats)
    if adapter is None:
        import company_sites  # own career sites (HiBob platform, Amdocs, Elbit, Matrix, Malam)

        adapter = company_sites.READERS.get(ats)
    if adapter is None:
        return name, [], f"unknown ats {ats!r}"
    try:
        return name, adapter(name, slug), ""
    except urllib.error.HTTPError as exc:
        return name, [], f"HTTP {exc.code} (slug {slug!r} probably wrong)"
    except urllib.error.URLError as exc:
        return name, [], f"network error: {exc.reason}"
    except Exception as exc:
        return name, [], f"{type(exc).__name__}: {exc}"


# ==========================================================================
# Filtering
# ==========================================================================


def matches_location(location: str, wanted: Iterable[str], include_bare_remote: bool,
                     blocked: Iterable[str] = ()) -> bool:
    # Places whose names contain a wanted one ("מודיעין עילית" holds "מודיעין",
    # "אבן יהודה" holds "יהוד") are cut out first, so they never match.
    low = location.lower()
    for term in blocked:
        low = low.replace(term, " ")
    if not low.strip():
        return False
    if any(term in low for term in wanted):
        return True
    return include_bare_remote and "remote" in low


def excluded_sector(company: str, text: str, config: dict[str, Any]) -> str:
    """Return the pattern that marks this employer as a bank or an insurer, or "".

    `exclude_companies` is matched against the company name. Staffing agencies
    on Drushim often hide the client ("חסוי"), so `exclude_description_patterns`
    is matched against the posting text as well ("לבנק מוביל", "לחברת ביטוח").
    `exclude_companies_except` wins over both — ביטוח לאומי is a government
    agency, not an insurer.
    """
    company_low = (company or "").lower()
    text_low = (text or "").lower()
    for keep in config.get("exclude_companies_except", []):
        if keep.lower() in company_low:
            return ""
    for pattern in config.get("exclude_companies", []):
        if re.search(pattern, company_low, re.I):
            return pattern
    for pattern in config.get("exclude_description_patterns", []):
        if text_low and re.search(pattern, text_low, re.I):
            if not any(keep.lower() in text_low for keep in config.get("exclude_companies_except", [])):
                return pattern
    return ""


def score_job(job: Job, config: dict[str, Any], text: str = "") -> Job | None:
    if excluded_sector(job.company, text, config):
        return None

    title = f" {job.title.lower()} "

    for bad in config["exclude_title_keywords"]:
        if bad.lower() in title:
            return None

    matched = [kw for kw in config["title_keywords"] if kw.lower() in title]
    if not matched:
        return None

    # An Israeli recruiting post often names no city; those are kept rather than lost.
    # Commuting zone (geo.py, 2026-11-08): out if every named place is north of Herzliya,
    # Be'er Sheva, or >55 km from Jerusalem and Shoresh; in if any named place is inside.
    # Only when no place is recognisable does the older city whitelist decide.
    import geo

    verdict = geo.zone_verdict(job.location)
    if verdict is False:
        return None
    # Same for employers whose own site never names a place (Max, Cal): "city not stated".
    post_without_city = "city not stated" in job.location
    if verdict is None and not post_without_city and not matches_location(
            job.location, [l.lower() for l in config["locations"]], config.get("include_bare_remote", False),
            [l.lower() for l in config.get("exclude_locations", [])]):
        return None

    job.matched = matched
    job.leadership = any(kw.lower() in title for kw in config["leadership_keywords"])
    job.score = len(matched) * 10 + (25 if job.leadership else 0)
    return job


# ==========================================================================
# Scan
# ==========================================================================


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"ERROR: {CONFIG_PATH.name} not found.")
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {CONFIG_PATH.name} is not valid JSON ({exc}).") from exc


def scan(config: dict[str, Any], *, verify_only: bool = False) -> list[Job]:
    companies = config["companies"]
    print(f"Scanning {len(companies)} company boards...\n")

    all_jobs: list[Job] = []
    resolved, failed = [], []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for name, jobs, error in pool.map(fetch_company, companies):
            if error:
                failed.append((name, error))
            else:
                resolved.append((name, len(jobs)))
                all_jobs.extend(jobs)

    for name, count in sorted(resolved):
        print(f"  [OK]   {name:<18} {count:>4} roles")
    for name, error in sorted(failed):
        print(f"  [SKIP] {name:<18} {error}")

    print(f"\n{len(resolved)}/{len(companies)} boards reachable, {len(all_jobs)} roles total.")

    if verify_only:
        if failed:
            print("\nFix or remove the failing slugs in job_search_config.json.")
        return []

    matches = [j for j in (score_job(job, config) for job in all_jobs) if j is not None]
    matches.sort(key=lambda j: (-j.score, j.company, j.title))
    return matches


def write_results(matches: list[Job], shown: list[Job] | None = None) -> None:
    """The JSON keeps every match; the Markdown keeps only what was shown.

    Jobs you have already submitted stay in the JSON so that --all can bring
    them back later without a rescan — the filtering is applied on the way out.
    """
    shown = matches if shown is None else shown
    RESULTS_JSON.write_text(
        json.dumps([asdict(j) for j in matches], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Job matches — {date.today().isoformat()}",
        "",
        f"{len(shown)} roles matched. Tailor them with "
        "`python find_jobs.py --pick 3` — or several at once: `--pick 1,4,7`, `--pick 3-6`.",
        "",
        "| # | Company | Role | Location | Updated | Lead? | Apply |",
        "|--:|---|---|---|---|:-:|---|",
    ]
    for index, job in enumerate(shown, start=1):
        lines.append(
            f"| {index} | {job.company} | {job.title} | {job.location} | "
            f"{job.updated or '-'} | {'yes' if job.leadership else ''} | [link]({job.url}) |"
        )
    lines.append("")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def _text_key(text: str) -> str:
    """Company and role names, flattened enough that 'Data Scientist ' and
    'data scientist' are the same thing."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def tracker_index() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Two ways into the tracker: by apply link, and by (company, role).

    The second one is not redundant. A row seeded from an old application folder
    usually carries the company's own careers URL, while a scan produces the ATS
    link — so matching on the link alone reports a job you already sent as new.

    Values are "sent" (the הוגש? column says כן) or "listed".
    """
    try:
        import tracker

        if not tracker.TRACKER_PATH.exists():
            return {}, {}
        _, sheet = tracker.load()
    except Exception:
        # The tracker being unreadable (open in Excel, corrupt) must never stop a scan.
        return {}, {}

    by_url: dict[str, str] = {}
    by_pair: dict[tuple[str, str], str] = {}
    for row in sheet.iter_rows(min_row=2, min_col=1, max_col=tracker.STATUS_COL):
        cell = row[tracker.URL_COL - 1]
        url = cell.hyperlink.target if cell.hyperlink else cell.value
        marked = str(row[tracker.STATUS_COL - 1].value or "").strip()
        state = "sent" if marked == tracker.SUBMITTED else "listed"
        if url:
            by_url[str(url).strip().rstrip("/").lower()] = state
        company, title = _text_key(row[1].value), _text_key(row[2].value)
        if company and title:
            # "sent" must win if the same role sits in the file twice.
            if by_pair.get((company, title)) != "sent":
                by_pair[(company, title)] = state
    return by_url, by_pair


def job_state(job: Job, by_url: dict[str, str], by_pair: dict[tuple[str, str], str]) -> str:
    return (
        by_url.get(job.url.strip().rstrip("/").lower())
        or by_pair.get((_text_key(job.company), _text_key(job.title)))
        or ""
    )


def drop_applied(matches: list[Job]) -> tuple[list[Job], list[Job]]:
    """Split off the roles the tracker says you already submitted.

    Rows still marked לא stay in the list — they are on your shortlist, not behind you.
    """
    by_url, by_pair = tracker_index()
    if not by_url and not by_pair:
        return matches, []
    kept, applied = [], []
    for job in matches:
        (applied if job_state(job, by_url, by_pair) == "sent" else kept).append(job)
    return kept, applied


def print_table(matches: list[Job], *, just_written: bool = True) -> None:
    if not matches:
        print("\nNo matches. Loosen title_keywords or locations in job_search_config.json.")
        return
    print(f"\n{len(matches)} matching roles:\n")
    print(f"  {'#':>3}  {'Company':<16} {'Role':<46} {'Location':<24} Lead  Status")
    print("  " + "-" * 104)
    by_url, by_pair = tracker_index()
    for index, job in enumerate(matches, start=1):
        title = job.title if len(job.title) <= 45 else job.title[:42] + "..."
        location = job.location if len(job.location) <= 23 else job.location[:20] + "..."
        done = job_state(job, by_url, by_pair)
        if not done and already_tailored(job):
            done = "folder"
        print(
            f"  {index:>3}. {job.company:<16} {title:<46} {location:<24} "
            f"{'*' if job.leadership else ' '}     {done}"
        )
    if just_written:
        print(f"\nWritten to {RESULTS_MD.name} and {RESULTS_JSON.name}")


def report_hidden(applied: list[Job]) -> None:
    """Say what was left out, so a short list never looks like a broken scan."""
    if not applied:
        return
    names = ", ".join(sorted({job.company for job in applied}))
    print()
    print(f"  {len(applied)} already submitted, hidden: {names}   (--all shows them)")


def load_saved(*, show_all: bool = False) -> list[Job]:
    """The last scan, minus anything you have since marked as submitted.

    The filter runs here rather than only at scan time so that the numbers you
    see in the table and the numbers --pick reads are always the same list, even
    if you ticked a row in Excel between the two.
    """
    if not RESULTS_JSON.exists():
        raise SystemExit("ERROR: no jobs_found.json yet — run `python find_jobs.py` first.")
    jobs = [Job(**record) for record in json.loads(RESULTS_JSON.read_text(encoding="utf-8"))]
    if show_all:
        return jobs
    return drop_applied(jobs)[0]


# ==========================================================================
# Pick + tailor
# ==========================================================================


def slugify(text: str, limit: int = 45) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return slug[:limit].strip("_") or "role"


def folder_tail(job: Job) -> str:
    """The part of the folder name that identifies the role, without the date."""
    return f"{slugify(job.company)}__{slugify(job.title)}"


def job_folder(job: Job) -> Path:
    """Today's folder for this role. Dated, so repeat applications stay apart."""
    return RUNS_DIR / f"{date.today().isoformat()}__{folder_tail(job)}"


def past_folders(job: Job) -> list[Path]:
    """Every folder ever made for this role, oldest name first."""
    if not RUNS_DIR.exists():
        return []
    tail = folder_tail(job)
    return sorted(p for p in RUNS_DIR.glob(f"*{tail}") if p.is_dir() and p.name.endswith(tail))


def already_tailored(job: Job) -> bool:
    return any(
        any(folder.glob("* - CV.pdf")) or any(folder.glob("* - CV.docx"))
        for folder in past_folders(job)
    )


def parse_picks(spec: str, total: int) -> list[int]:
    """'2' -> [2];  '1,4,7' -> [1,4,7];  '3-6' -> [3,4,5,6];  mixes are fine."""
    picks: list[int] = []
    for chunk in re.split(r"[,;\s]+", spec.strip()):
        if not chunk:
            continue
        span = re.fullmatch(r"(\d+)\s*-\s*(\d+)", chunk)
        if span:
            first, last = sorted((int(span.group(1)), int(span.group(2))))
            wanted = range(first, last + 1)
        elif chunk.isdigit():
            wanted = [int(chunk)]
        else:
            raise SystemExit(
                f"ERROR: cannot read {chunk!r} as a job number. "
                "Use 2, or 1,4,7, or 3-6."
            )
        for number in wanted:
            if not 1 <= number <= total:
                raise SystemExit(f"ERROR: {number} is outside the list (1-{total}).")
            if number not in picks:
                picks.append(number)
    if not picks:
        raise SystemExit("ERROR: no job numbers given.")
    return picks


def fetch_description(job: Job) -> str:
    if job.ats == "greenhouse":
        payload = fetch_json(
            f"https://boards-api.greenhouse.io/v1/boards/{job.slug}/jobs/{job.job_id}"
        )
        return html_to_text(payload.get("content", ""))
    if job.ats == "lever":
        host, board = _lever_api(job.slug)
        payload = fetch_json(f"{host}/v0/postings/{board}/{job.job_id}?mode=json")
        parts = [payload.get("description", "")]
        for section in payload.get("lists", []) or []:
            parts.append(f"<h3>{section.get('text','')}</h3>{section.get('content','')}")
        parts.append(payload.get("additional", ""))
        return html_to_text("".join(parts))
    if job.ats == "ashby":
        payload = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{job.slug}")
        for entry in payload.get("jobs", []):
            if str(entry.get("id", "")) == job.job_id:
                return entry.get("descriptionPlain") or html_to_text(entry.get("descriptionHtml", ""))
        raise SystemExit("ERROR: that Ashby posting is no longer on the board.")
    if job.ats == "comeet":
        for entry in _comeet_positions(job.slug):
            if str(entry.get("uid", "")) != job.job_id:
                continue
            details = (entry.get("custom_fields") or {}).get("details") or []
            parts = [f"<h3>{d.get('name','')}</h3>{d.get('value','')}" for d in details]
            return html_to_text("".join(parts))
        raise SystemExit("ERROR: that Comeet posting is no longer on the board.")
    if job.ats == "smartrecruiters":
        payload = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{job.slug}/postings/{job.job_id}")
        sections = ((payload.get("jobAd") or {}).get("sections") or {}).values()
        return html_to_text("".join(f"<h3>{s.get('title', '')}</h3>{s.get('text', '')}" for s in sections))
    if job.ats == "successfactors":
        for block in _sf_listing(job.slug):
            if _sf_field(block, "ReqId") == job.job_id:
                return html_to_text(_sf_field(block, "Job-Description"))
        raise SystemExit("ERROR: that posting is no longer in the SuccessFactors feed.")
    if job.ats == "workday":
        tenant, host, site = _workday_base(job.slug)
        payload = fetch_json(f"{host}/wday/cxs/{tenant}/{site}{job.job_id}")
        return html_to_text((payload.get("jobPostingInfo") or {}).get("jobDescription", ""))
    if job.ats in ("linkedin", "drushim"):
        import market_sources

        return market_sources.fetch_description(job.ats, job.job_id)
    if job.ats in ("alljobs", "jobmaster"):
        import israeli_boards

        fetch = getattr(israeli_boards, f"fetch_{job.ats}_description")
        return fetch(job.job_id)
    if job.ats in ("linkedin_post", "civil_service", "govil"):
        import extra_sources

        return extra_sources.fetch_description(job.ats, job.job_id)
    import company_sites

    if job.ats in company_sites.DESCRIBERS:
        return company_sites.DESCRIBERS[job.ats](job)
    raise SystemExit(f"ERROR: don't know how to fetch a description from {job.ats!r}.")


def ensure_submittable_cv(folder: Path) -> list[str]:
    """A job folder must never exist without something you could actually send.

    If a tailored CV is already there, do nothing. Otherwise drop in a copy of the
    master CV (wherever RESUME_INPUT points), clearly marked '(general)' so it can't be mistaken for a
    tailored one. The tailored run deletes these the moment it succeeds.
    """
    import shutil
    import tailor_resume

    if any(folder.glob("* - CV.pdf")) or any(folder.glob("* - CV.docx")):
        return []

    memory_path = ENGINE_DIR / "candidate_memory.json"
    memory = json.loads(memory_path.read_text(encoding="utf-8")) if memory_path.exists() else {}
    name = (memory.get("candidate_profile") or {}).get("full_name", "").strip() or "Resume"
    name = re.sub(r'[<>:"/\\|?*]', "", name)

    copied = []
    for source in tailor_resume.master_files():
        target = folder / f"{name} - CV (general){source.suffix.lower()}"
        shutil.copy2(source, target)
        copied.append(target.name)

    if copied:
        # ASCII only: this opens in Notepad, which misreads UTF-8 on a Hebrew locale.
        (folder / "READ_ME.txt").write_text(
            "This folder does not have a TAILORED resume yet.\r\n\r\n"
            f"What is here: {', '.join(copied)}\r\n"
            "That is a copy of your master resume, not adapted to this posting.\r\n"
            "It is safe to send, but it is generic.\r\n\r\n"
            "To get the tailored version: run START.bat, choose 1, and pick this\r\n"
            "role again. The tailored file replaces these '(general)' copies\r\n"
            "automatically.\r\n",
            encoding="ascii",
        )
    return copied


def pick_one(job: Job, *, tailor: bool, extra_args: list[str]) -> int:
    print(f"Selected: {job.title} @ {job.company} ({job.location})")

    description = fetch_description(job)
    if len(description) < 200:
        print(f"WARNING: the posting body came back very short ({len(description)} chars).")

    folder = job_folder(job)
    folder.mkdir(parents=True, exist_ok=True)

    header = (
        f"Company: {job.company}\n"
        f"Title: {job.title}\n"
        f"Location: {job.location}\n"
        f"Apply: {job.url}\n"
        f"{'-' * 60}\n\n"
    )
    jd_path = folder / "job_description.txt"
    jd_path.write_text(header + description + "\n", encoding="utf-8")

    (folder / "APPLY.url").write_text(
        f"[InternetShortcut]\nURL={job.url}\n", encoding="ascii", errors="ignore"
    )
    print(f"  Wrote {jd_path.relative_to(PROJECT_ROOT)} ({len(description):,} chars)")
    print(f"  Wrote {(folder / 'APPLY.url').relative_to(PROJECT_ROOT)}")

    if not tailor:
        for name in ensure_submittable_cv(folder):
            print(f"  Wrote {name}  (general copy — not tailored)")
        print(f"\nTailor it with:\n  python tailor_resume.py --jd \"{jd_path}\" --out-dir \"{folder}\"")
        return 0

    import tailor_resume

    argv = [
        "--jd", str(jd_path),
        "--out-dir", str(folder),
        "--company", job.company,
        "--role", job.title,
        *extra_args,
    ]
    print()
    try:
        result = tailor_resume.main(argv)
    except SystemExit as exc:
        result = exc.code if isinstance(exc.code, int) else 1
        print(f"\n{exc}" if exc.code else "")

    if result == 0:
        (folder / "READ_ME.txt").unlink(missing_ok=True)
        for path in sorted(folder.glob("* - CV.*")):
            print(f"  Ready to submit: {path.name}")
        print(f"\nApply here: {job.url}")
        print(f"(or double-click {(folder / 'APPLY.url').relative_to(PROJECT_ROOT)})")
    else:
        # Tailoring failed — never leave the folder without something sendable.
        copied = ensure_submittable_cv(folder)
        if copied:
            print("\nTailoring did not complete, so your master resume was placed here instead:")
            for name in copied:
                print(f"  {name}")
            print("See READ_ME.txt in that folder.")
    return result


def manual_folder() -> Path:
    """A dated folder for a posting you pasted yourself, unique within the day."""
    base = f"{date.today().isoformat()}__manual"
    folder = RUNS_DIR / base
    counter = 2
    while folder.exists() and any(folder.iterdir()):
        folder = RUNS_DIR / f"{base}_{counter}"
        counter += 1
    return folder


def run_manual(extra_args: list[str]) -> int:
    """Tailor to the posting sitting in job_description.txt at the project root."""
    import shutil

    source = PROJECT_ROOT / "job_description.txt"
    body = source.read_text(encoding="utf-8", errors="replace").strip() if source.exists() else ""
    if len(body) < 100 or body.startswith("Paste the full job posting here"):
        raise SystemExit(
            "ERROR: job_description.txt has no posting in it yet.\n"
            "       Paste the full posting there, save, and try again."
        )

    folder = manual_folder()
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, folder / "job_description.txt")
    print(f"Working in applications\\{folder.name}\n")

    import tailor_resume

    argv = ["--jd", str(source), "--out-dir", str(folder), *extra_args]
    try:
        result = tailor_resume.main(argv)
    except SystemExit as exc:
        result = exc.code if isinstance(exc.code, int) else 1
        print(f"\n{exc}" if exc.code else "")

    if result == 0:
        for path in sorted(folder.glob("* - CV.*")):
            print(f"  Ready to submit: {path.name}")
        print(f"\nFiles are in:  applications\\{folder.name}")
    else:
        for name in ensure_submittable_cv(folder):
            print(f"  Placed {name}  (general copy — not tailored)")
    return result


def record_picks(spec: str, *, show_all: bool = False) -> int:
    """The normal path: put the chosen jobs in the tracker and stop there.

    No folder, no API call, nothing generated. You send the same master CV to
    everyone, so the only thing worth keeping is the link, the date, and whether
    you actually submitted.
    """
    import tracker

    jobs = load_saved(show_all=show_all)
    numbers = parse_picks(spec, len(jobs))
    chosen = [jobs[n - 1] for n in numbers]

    entries = [
        {
            "created": date.today().isoformat(),
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "url": job.url,
        }
        for job in chosen
    ]
    added, already = tracker.add_rows(entries)

    print()
    for entry in added:
        print(f"  + {entry['company']} — {entry['title']}")
        print(f"    {entry['url']}")
    for entry in already:
        print(f"  = {entry['company']} — {entry['title']}  (already in the tracker)")

    total, submitted = tracker.counts()
    print()
    print(f"  {len(added)} added, {len(already)} already there. "
          f"Tracker now holds {total} jobs, {submitted} marked submitted.")
    print(f"  {tracker.TRACKER_PATH}")
    print()
    print("  Apply with your master CV, then set the 'הוגש?' column to כן.")
    return 0


def add_manual_row(url: str, company: str, title: str, location: str, note: str) -> int:
    """A job you found yourself (LinkedIn, AllJobs) — same tracker, same CV."""
    import tracker

    if not url.strip():
        print("ERROR: a job without a link is not much use. Paste the apply URL.")
        return 1

    added, already = tracker.add_rows([
        {
            "created": date.today().isoformat(),
            "company": company.strip(),
            "title": title.strip(),
            "location": location.strip(),
            "url": url.strip(),
            "note": note.strip(),
        }
    ])
    if already:
        print("  = that link is already in the tracker.")
    else:
        print(f"  + {company or 'job'} added to the tracker.")
    total, submitted = tracker.counts()
    print(f"  Tracker now holds {total} jobs, {submitted} marked submitted.")
    return 0


def seed_tracker() -> int:
    """One-off: carry the application folders you already made into the tracker."""
    import tracker

    entries = tracker.seed_from_folders()
    if not entries:
        print("  No application folders to carry over.")
        return 0
    added, already = tracker.add_rows(entries)
    for entry in added:
        print(f"  + {entry['created']}  {entry['company']} — {entry['title']}")
    print(f"\n  {len(added)} carried over, {len(already)} already there.")
    return 0


def pick(spec: str, *, tailor: bool, extra_args: list[str], show_all: bool = False) -> int:
    jobs = load_saved(show_all=show_all)
    numbers = parse_picks(spec, len(jobs))

    if len(numbers) == 1:
        return pick_one(jobs[numbers[0] - 1], tailor=tailor, extra_args=extra_args)

    print(f"Preparing {len(numbers)} applications: {', '.join(str(n) for n in numbers)}\n")
    outcomes: list[tuple[int, Job, int]] = []

    for position, number in enumerate(numbers, start=1):
        job = jobs[number - 1]
        print("=" * 72)
        print(f"  [{position}/{len(numbers)}]  #{number}  {job.title} @ {job.company}")
        print("=" * 72)
        try:
            code = pick_one(job, tailor=tailor, extra_args=extra_args)
        except SystemExit as exc:
            # One bad posting must not abandon the rest of the batch.
            code = exc.code if isinstance(exc.code, int) else 1
            print(f"\n{exc}" if exc.code else "")
        except Exception as exc:
            code = 1
            print(f"\nFailed on #{number}: {type(exc).__name__}: {exc}")
        if code != 0 and job_folder(job).is_dir():
            # Same invariant as a single run: never leave a folder with nothing sendable.
            for name in ensure_submittable_cv(job_folder(job)):
                print(f"  Placed {name}  (general copy — not tailored)")
        outcomes.append((number, job, code))
        print()

    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    for number, job, code in outcomes:
        mark = "OK  " if code == 0 else "FAIL"
        print(f"  [{mark}] #{number:<3} {job.company} — {job.title}")
        print(f"         {job_folder(job).name}")
    failures = sum(1 for _, _, code in outcomes if code != 0)
    if failures:
        print(
            f"\n{failures} of {len(outcomes)} did not finish — pick those numbers again to retry."
        )
    return 1 if failures else 0


# ==========================================================================
# CLI
# ==========================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="find_jobs.py",
        description="Scan public ATS boards for matching roles, then tailor your resume to one.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python find_jobs.py\n"
            "  python find_jobs.py --list\n"
            "  python find_jobs.py --verify\n"
            "  python find_jobs.py --pick 3\n"
            "  python find_jobs.py --pick 1,4,7\n"
            "  python find_jobs.py --pick 3-6 --model claude-opus-5 --effort max\n"
        ),
    )
    parser.add_argument(
        "--pick",
        metavar="N",
        help="Add one or more matches to the tracker: 3, or 1,4,7, or 3-6.",
    )
    parser.add_argument(
        "--tailor",
        action="store_true",
        help="With --pick: also build a tailored CV in a dated folder (costs an API call).",
    )
    parser.add_argument("--no-tailor", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--add", action="store_true", help="Add a job you found yourself to the tracker.")
    parser.add_argument("--url", default="", help="With --add: the apply link.")
    parser.add_argument("--company", default="", help="With --add: company name.")
    parser.add_argument("--role", default="", help="With --add: job title.")
    parser.add_argument("--location", default="", help="With --add: location.")
    parser.add_argument("--note", default="", help="With --add: a note for the row.")
    parser.add_argument(
        "--seed-tracker",
        action="store_true",
        help="Carry the application folders you already have into the tracker.",
    )
    parser.add_argument("--list", action="store_true", help="Reprint the last scan without rescanning.")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Tailor to the posting in job_description.txt, into a dated folder.",
    )
    parser.add_argument("--verify", action="store_true", help="Only report which company slugs resolve.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also show roles marked as submitted in applications.xlsx. It renumbers "
             "the list, so pass it to --pick as well.",
    )
    args, extra = parser.parse_known_args(argv)

    if args.add:
        return add_manual_row(args.url, args.company, args.role, args.location, args.note)

    if args.seed_tracker:
        return seed_tracker()

    if args.pick is not None:
        if args.tailor:
            return pick(args.pick, tailor=True, extra_args=extra, show_all=args.all)
        return record_picks(args.pick, show_all=args.all)

    if args.manual:
        return run_manual(extra)

    if args.list:
        jobs = load_saved(show_all=True)
        shown, applied = (jobs, []) if args.all else drop_applied(jobs)
        print_table(shown, just_written=False)
        report_hidden(applied)
        return 0

    config = load_config()
    matches = scan(config, verify_only=args.verify)
    if args.verify:
        return 0
    shown, applied = (matches, []) if args.all else drop_applied(matches)
    write_results(matches, shown)
    print_table(shown)
    report_hidden(applied)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        raise SystemExit(130)
