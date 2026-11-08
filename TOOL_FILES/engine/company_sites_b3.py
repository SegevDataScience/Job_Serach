#!/usr/bin/env python3
"""
company_sites_b3.py — third batch of company career-site readers (verified
2026-11-08): Ichilov, Hadassah, Mekorot, Strauss, Osem-Nestle, Tnuva, Shufersal.
Imported at the end of company_sites.py, which merges READERS / DESCRIBERS.

Not readable (checked the same day): Bazan and Israel Post (Cloudflare block
page), Super-Pharm (Reblaze challenge, HTTP 247), ZIM (job list is a lazy React
widget; Akamai denies headless browsers), IEC (Angular app, job source not found).
Both ZIM and IEC are Haifa-based anyway.
"""

from __future__ import annotations

import html as htmlmod
import re

from curl_cffi import requests as cr

from company_sites import _get, page_description
from company_sites_b2 import _iso, _place_loc, _post, _strip
from find_jobs import Job


def from_redmatch(company: str, slug: str) -> list[Job]:
    """RedMatch / TopMatch board (Ichilov; Clalit uses the same system).
    slug = "<api host>|<affiliate GUID>|<apply page base>|<default city>"."""
    host, guid, apply_base, city = (slug.split("|") + ["", "", "", ""])[:4]
    data = _post(f"https://{host}/CandidateAPI/api//position/Search/{guid}",
                 json={"KeyWords": "", "CategoryId": [], "countryId": 2, "cityId": []}, timeout=90).json()
    jobs = []
    for p in data.get("positions") or []:
        title = (p.get("jobTitleText") or "").strip()
        jobs.append(Job(company=company, title=title, location=_place_loc(p.get("displayLocation") or "", title, city),
                        url=f"{apply_base}?compPositionID={p.get('compPositionID')}", ats="redmatch", slug=slug,
                        job_id=str(p.get("compPositionID", "")), updated=(p.get("activationDate") or "")[:10]))
    return jobs


def from_hadassah(company: str, slug: str) -> list[Job]:
    """Static list of links; every opening is in Jerusalem (Ein Kerem / Mount Scopus)."""
    page = _get("https://he.hadassah.org.il/wanted/careers/").text
    jobs, seen = [], set()
    for url, inner in re.findall(r'<a[^>]+href="(https://he\.hadassah\.org\.il/wanted/position-\d+/?)"[^>]*>(.*?)</a>', page, re.S):
        if url in seen:
            continue
        seen.add(url)
        name = re.search(r'nameContainer[^"]*">(.*?)</div>', inner, re.S)
        title = _strip(name.group(1) if name else inner)
        if not title:
            continue
        jobs.append(Job(company=company, title=title, location="ירושלים, Israel", url=url, ats="hadassah",
                        slug=slug, job_id=url.rstrip("/").rsplit("-", 1)[-1]))
    return jobs


def from_mekorot(company: str, slug: str) -> list[Job]:
    page = _get("https://careers.mekorot.co.il/open-jobs/").text
    jobs = []
    for block in page.split('class="jobs-post"')[1:]:
        name = re.search(r'job-name[^>]*>(.*?)</div>', block, re.S)
        link = re.search(r'href="(https://careers\.mekorot\.co\.il/\?job=[^"]+)"', block)
        if not name or not link:
            continue
        title = _strip(name.group(1))
        cells = [c for c in (_strip(x) for x in re.findall(r'role="cell"[^>]*>(.*?)</div>', block, re.S)) if c]
        region = next((c for c in cells if c in ("מרכז", "צפון", "דרום", "ירושלים", "שרון", "שפלה", "כל הארץ")), "")
        date = re.search(r"(\d{2}/\d{2}/\d{4})", block)
        jobs.append(Job(company=company, title=title, location=_place_loc(region, title),
                        url=htmlmod.unescape(link.group(1)), ats="mekorot", slug=slug, job_id=link.group(1),
                        updated=_iso(date.group(1)) if date else ""))
    return jobs


def from_strauss(company: str, slug: str) -> list[Job]:
    page = _get("https://www.strauss-group.co.il/career/jobs/", timeout=60).text
    jobs = []
    for block in page.split('class="order_desc_title_job">')[1:]:
        title = _strip(block.split("</h2>", 1)[0])
        job_id = re.search(r"jobid%3D(\d+)", block) or re.search(r"jobs_order_open_btn_(\d+)", block)
        if not title or not job_id:
            continue
        jid = job_id.group(1)
        jobs.append(Job(company=company, title=title, location=_place_loc("", title),
                        url=f"https://www.strauss-group.co.il/career/jobs/?jobid={jid}", ats="strauss", slug=slug, job_id=jid))
    return jobs


def from_osem(company: str, slug: str) -> list[Job]:
    jobs, seen = [], set()
    for page_no in range(0, 15):
        page = _get(f"https://www.osem-nestle.co.il/career/open-positions?page={page_no}").text
        found = 0
        for row in page.split('class="column-job views-row"')[1:]:
            link = re.search(r'field-job-offer-title.*?href="(/career/open-positions/(\d+))"[^>]*>(.*?)</a>', row, re.S)
            if not link or link.group(2) in seen:
                continue
            seen.add(link.group(2))
            found += 1
            place = re.search(r"field-job-offer-location.*?<a[^>]*>(.*?)</a>", row, re.S)
            location = re.sub(r"^\s*מִקוּם\s*", "", _strip(place.group(1))) if place else ""
            title = _strip(link.group(3))
            jobs.append(Job(company=company, title=title, location=_place_loc(location, title),
                            url="https://www.osem-nestle.co.il" + link.group(1), ats="osem", slug=slug, job_id=link.group(2)))
        if not found:
            break
    return jobs


def from_tnuva(company: str, slug: str) -> list[Job]:
    jobs, seen = [], set()
    for page_no in range(1, 30):
        url = "https://www.tnuva.co.il/jobs/" if page_no == 1 else f"https://www.tnuva.co.il/jobs/page/{page_no}/"
        response = cr.get(url, impersonate="chrome", timeout=40)
        if response.status_code == 404:
            break
        response.raise_for_status()
        found = 0
        for href, inner in re.findall(r'<a href="(https://www\.tnuva\.co\.il/jobs/[^"]+)"[^>]*class="job-title"[^>]*>(.*?)</a>', response.text, re.S):
            if href in seen:
                continue
            seen.add(href)
            found += 1
            title = _strip(inner)
            jobs.append(Job(company=company, title=title, location=_place_loc("", title), url=href,
                            ats="tnuva", slug=slug, job_id=href))
        if not found:
            break
    return jobs


def from_shufersal(company: str, slug: str) -> list[Job]:
    """Wix site whose page calls a backend web method (Position.jsw/searchPosition).
    The Adam HR fields are the same as Bezeq's."""
    session = cr.Session(impersonate="chrome")
    tokens = session.get("https://www.shufersal.co.il/corp/_api/v1/access-tokens", timeout=30).json()
    instance = ((tokens.get("apps") or {}).get("675bbcef-18d8-41f5-800e-131ec9e08762") or {}).get("instance", "")
    response = session.post(
        "https://www.shufersal.co.il/corp/_api/wix-code-public-dispatcher-ng/siteview/_webMethods/backend/"
        "Position.jsw/searchPosition.ajax?gridAppId=3a70ca04-71d9-42c7-96d8-ab8bc9e0b8c1&viewMode=site",
        json=[{"keyWords": "", "categoryId": [], "cityId": [], "sectionId": [], "countryId": 2}],
        headers={"Authorization": instance}, timeout=60)
    response.raise_for_status()
    jobs = []
    for r in response.json().get("result") or []:
        title = (r.get("description") or "").strip()
        keys = ["Order_place", "work_area"] + [f"living_area{i}" for i in range(1, 7)]
        region = ", ".join(dict.fromkeys(str(r[k]).strip() for k in keys if r.get(k) and str(r[k]).strip()))
        jobs.append(Job(company=company, title=title, location=_place_loc(region, title),
                        url=f"https://www.shufersal.co.il/corp/jobs#{r.get('order_id')}", ats="shufersal", slug=slug,
                        job_id=str(r.get("order_id", "")), updated=_iso(r.get("update_date") or r.get("orderDate") or "")))
    return jobs


READERS = {"redmatch": from_redmatch, "hadassah": from_hadassah, "mekorot": from_mekorot, "strauss": from_strauss,
           "osem": from_osem, "tnuva": from_tnuva, "shufersal": from_shufersal}
DESCRIBERS = {ats: page_description for ats in ("redmatch", "hadassah", "mekorot", "osem", "tnuva")}
