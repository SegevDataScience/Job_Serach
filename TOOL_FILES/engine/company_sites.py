#!/usr/bin/env python3
"""
company_sites.py — readers for company career sites that are not on a standard
ATS (found and verified 2026-11-07). Each reader takes (company, slug) like the
adapters in find_jobs.py and returns Job objects; find_jobs.fetch_company falls
back to READERS here for an unknown `ats`.

- hibob:   HiBob's careers platform (HiBob, Sapiens). GET /api/job-ad needs the
           `companyidentifier` header. slug = "<subdomain>|<default city>",
           the city is used when a posting names none (HiBob never does).
- eightfold: Amdocs. /api/pcsx/search, 10 per page. slug = "<host>|<domain>".
- elbit:   a public JSON dump of all openings. No city field: the city is the
           first wanted place the posting text names, else its English area.
- matrix:  static HTML, 10 per page. Location = Hebrew region (גוש דן...).
- malam:   one ~7.5 MB HTML page with every opening. Location = Hebrew region.

Matrix and Malam give regions, not cities, and no dates. "גוש דן" is in the
config's locations for that reason.
"""

from __future__ import annotations

import html as htmlmod
import json
import re
from datetime import datetime, timezone
from typing import Any

from find_jobs import Job, html_to_text

try:
    from curl_cffi import requests as cr
except ImportError:  # pragma: no cover
    cr = None


def _get(url: str, timeout: int = 30, **kw):
    if cr is None:
        raise RuntimeError("curl_cffi is not installed")
    response = cr.get(url, impersonate="chrome", timeout=timeout, **kw)
    response.raise_for_status()
    return response


def _wanted_place(text: str) -> str:
    """First wanted city named in a Hebrew/English text, as the config spells it."""
    from find_jobs import load_config

    config = load_config()
    low = (text or "").lower()
    for bad in config.get("exclude_locations", []):
        low = low.replace(bad.lower(), " ")
    for place in config.get("locations", []):
        p = place.lower()
        # Whole words only ("שיפור" holds "יפו"); Hebrew may add one prefix letter (בתל אביב).
        prefix = "[בלמוה]?" if p[:1] >= "א" else ""
        if re.search(rf"(?<![a-zא-ת]){prefix}{re.escape(p)}(?![a-zא-ת])", low):
            return place
    return ""


# ------------------------------------------------------------------ HiBob

def from_hibob(company: str, slug: str) -> list[Job]:
    sub, _, default_city = slug.partition("|")
    payload = _get(f"https://{sub}.careers.hibob.com/api/job-ad", headers={"companyidentifier": sub}).json()
    jobs = []
    for ad in payload.get("jobAdDetails", []):
        if (ad.get("country") or "").lower() != "israel":
            continue
        cities = [l.get("city") for l in ad.get("postingLocations") or [] if l.get("city")]
        jobs.append(Job(
            company=company, title=(ad.get("title") or "").strip(),
            location=", ".join(cities or [default_city or "Israel"]) + ", Israel",
            url=f"https://{sub}.careers.hibob.com/jobs/{ad.get('id')}",
            ats="hibob", slug=slug, job_id=str(ad.get("id", "")),
            updated=(ad.get("publishedAt") or "")[:10],
        ))
    return jobs


def hibob_description(job: Job) -> str:
    sub = job.slug.partition("|")[0]
    payload = _get(f"https://{sub}.careers.hibob.com/api/job-ad", headers={"companyidentifier": sub}).json()
    for ad in payload.get("jobAdDetails", []):
        if str(ad.get("id")) == job.job_id:
            return html_to_text("".join(str(ad.get(k) or "") for k in ("description", "responsibilities", "requirements")))
    raise SystemExit("ERROR: that HiBob posting is no longer listed.")


# ------------------------------------------------------------------ Eightfold (Amdocs)

def from_eightfold(company: str, slug: str) -> list[Job]:
    host, _, domain = slug.partition("|")
    jobs, start = [], 0
    while start < 1000:
        data = _get(f"https://{host}/api/pcsx/search", params={
            "domain": domain, "query": "", "location": "Israel", "start": start, "sort_by": "timestamp"}).json()
        positions = (data.get("data") or {}).get("positions") or []
        if not positions:
            break
        for p in positions:
            locations = p.get("standardizedLocations") or p.get("locations") or []
            posted = p.get("postedTs")
            jobs.append(Job(
                company=company, title=(p.get("name") or "").strip(),
                location="; ".join(map(str, locations)),
                url=f"https://{host}{p.get('positionUrl', '')}",
                ats="eightfold", slug=slug, job_id=str(p.get("id", "")),
                updated=datetime.fromtimestamp(posted, timezone.utc).date().isoformat() if posted else "",
            ))
        start += len(positions)
    return jobs


# ------------------------------------------------------------------ Elbit

_ELBIT_CACHE: dict[str, list[dict[str, Any]]] = {}


def _elbit_rows(url: str) -> list[dict[str, Any]]:
    if url not in _ELBIT_CACHE:
        _ELBIT_CACHE[url] = _get(url, timeout=60).json()
    return _ELBIT_CACHE[url]


def _elbit_text(row: dict[str, Any]) -> str:
    return html_to_text(htmlmod.unescape(row.get("description") or "")
                        + "\n" + htmlmod.unescape(row.get("requirements") or ""))


def from_elbit(company: str, slug: str) -> list[Job]:
    jobs = []
    for row in _elbit_rows(slug):
        text = _elbit_text(row)
        city = _wanted_place(text)
        area = row.get("area") or ""
        jobs.append(Job(
            company=f"{company} — {row.get('employerName')}" if row.get("employerName") else company,
            title=(row.get("jobTitle") or "").strip(),
            location=f"{city}, Israel" if city else f"{area} (Elbit area), Israel",
            # No per-job page exists; the jobs page plus the job code is what Elbit offers.
            url=f"https://elbitsystemscareer.com/jobs?code={row.get('jobCode', '')}",
            ats="elbit", slug=slug, job_id=str(row.get("jobId", "")),
            updated=(row.get("updateDate") or row.get("openDate") or "")[:10],
        ))
    return jobs


def elbit_description(job: Job) -> str:
    for row in _elbit_rows(job.slug):
        if str(row.get("jobId")) == job.job_id:
            return f"קוד משרה: {row.get('jobCode', '')} (לחיפוש באתר אלביט)\n\n" + _elbit_text(row)
    raise SystemExit("ERROR: that Elbit posting is no longer listed.")


# ------------------------------------------------------------------ Matrix

_MATRIX_ITEM = re.compile(r'<div[^>]*class="[^"]*job-item[^"]*"[^>]*job-id="(\d+)"(.*?)(?=<div[^>]*class="[^"]*job-item|</main|$)', re.S)


def from_matrix(company: str, slug: str) -> list[Job]:
    from find_jobs import excluded_sector, load_config

    config = load_config()
    base = slug.rstrip("/") + "/"
    jobs, seen = [], set()
    for page in range(1, 80):
        url = base if page == 1 else f"{base}page/{page}/"
        response = cr.get(url, impersonate="chrome", timeout=30)
        if response.status_code == 404:
            break
        response.raise_for_status()
        found = 0
        for job_id, block in _MATRIX_ITEM.findall(response.text):
            link = re.search(r'<a[^>]*class="[^"]*job-title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S) \
                or re.search(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*job-title[^"]*"[^>]*>(.*?)</a>', block, re.S)
            if not link or job_id in seen:
                continue
            seen.add(job_id)
            found += 1
            areas = re.search(r'<b[^>]*class="[^"]*job-areas[^"]*"[^>]*>(.*?)</b>', block, re.S)
            # Matrix staffs for banks and insurers without naming them ("לבנק מוביל"); the listing carries
            # the posting text, so the sector filter can read it here (score_job only sees the title).
            if excluded_sector(company, html_to_text(block), config):
                continue
            jobs.append(Job(
                company=company, title=htmlmod.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip(),
                location=htmlmod.unescape(re.sub(r"<[^>]+>", "", areas.group(1))).strip() + ", Israel" if areas else "Israel",
                url=htmlmod.unescape(link.group(1)), ats="matrix", slug=slug, job_id=job_id,
            ))
        if not found:
            break
    return jobs


# ------------------------------------------------------------------ Malam Team

def from_malam(company: str, slug: str) -> list[Job]:
    page = _get(slug, timeout=90).text
    jobs, seen = [], set()
    # Each opening is an <li class="s_career"> holding nested lists, so split on
    # the opening tags instead of matching to a closing one.
    for block in re.split(r'<li[^>]*class="[^"]*s_career[^"]*"', page)[1:]:
        title = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
        link = re.search(r'<a[^>]*href="([^"]*/%D7%9E%D7%A9%D7%A8%D7%94/[^"]*|[^"]*/משרה/[^"]*)"', block)
        if not title or not link:
            continue
        url = htmlmod.unescape(link.group(1))
        if url in seen:
            continue
        seen.add(url)
        cells = [htmlmod.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<li[^>]*>(.*?)</li>", block.split("ferow", 1)[-1], re.S)]
        region = cells[2] if len(cells) > 2 else ""
        jobs.append(Job(
            company=company, title=htmlmod.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(),
            location=(region + ", Israel") if region else "Israel",
            url=url, ats="malam", slug=slug, job_id=cells[0] if cells else url,
        ))
    return jobs


def page_description(job: Job) -> str:
    return html_to_text(_get(job.url).text)[:20000]


READERS = {"hibob": from_hibob, "eightfold": from_eightfold, "elbit": from_elbit,
           "matrix": from_matrix, "malam": from_malam}
DESCRIBERS = {"hibob": hibob_description, "elbit": elbit_description,
              "eightfold": page_description, "matrix": page_description, "malam": page_description}


# Second batch lives in its own module and registers here.
import company_sites_b2 as _b2  # noqa: E402

READERS.update(_b2.READERS)
DESCRIBERS.update(_b2.DESCRIBERS)

import company_sites_b3 as _b3  # noqa: E402

READERS.update(_b3.READERS)
DESCRIBERS.update(_b3.DESCRIBERS)
