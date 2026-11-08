#!/usr/bin/env python3
"""
company_sites_b4.py — readers added for the Dun & Bradstreet 2026 list
(verified 2026-11-08). Imported at the end of company_sites.py.

- comeet_api: Comeet's public careers API, for companies whose careers page embeds
  the Comeet widget (Panaya, Overwolf, WSC Sports). slug = "<company uid>|<token>";
  both are in the company's own public careers page (COMEET.init / comeetvar).
- google: google.com/about/careers job results for Israel, 20 per page, parsed
  from the server-rendered cards (title in the "Learn more about" label, offices
  in the card text).
"""

from __future__ import annotations

import html as htmlmod
import re
import time

from curl_cffi import requests as cr

from company_sites import _get, page_description
from find_jobs import Job, html_to_text


def from_comeet_api(company: str, slug: str) -> list[Job]:
    uid, _, token = slug.partition("|")
    positions = _get(f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions",
                     params={"token": token, "details": "false"}).json()
    jobs = []
    for p in positions:
        loc = p.get("location") or {}
        if (loc.get("country") or "").upper() not in ("IL", "ISRAEL"):
            continue
        place = ", ".join(x for x in (loc.get("city"), loc.get("state"), "Israel") if x)
        jobs.append(Job(company=company, title=(p.get("name") or "").strip(), location=place,
                        url=p.get("url_active_page") or p.get("url_comeet_hosted_page") or "",
                        ats="comeet_api", slug=slug, job_id=str(p.get("uid", "")),
                        updated=(p.get("time_updated") or "")[:10]))
    return jobs


def comeet_api_description(job: Job) -> str:
    uid, _, token = job.slug.partition("|")
    data = _get(f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions/{job.job_id}",
                params={"token": token, "details": "true"}).json()
    details = (data.get("details") or []) if isinstance(data, dict) else []
    return html_to_text("".join(f"<h3>{d.get('name', '')}</h3>{d.get('value', '')}" for d in details))


_G_BASE = "https://www.google.com/about/careers/applications/"


def from_google(company: str, slug: str) -> list[Job]:
    jobs, seen = [], set()
    for page in range(1, 20):
        text = _get(f"{_G_BASE}jobs/results/", params={"location": "Israel", "page": page}).text
        found = 0
        for card in re.split(r'aria-label="Learn more about ', text)[1:]:
            title = htmlmod.unescape(card.split('"', 1)[0]).strip()
            link = re.search(r'href="(jobs/results/(\d{6,})[^"?]*)', card) or \
                re.search(r'href="(jobs/results/(\d{6,})[^"?]*)', text[max(0, text.find(title) - 3000):text.find(title)])
            if not link or link.group(2) in seen:
                continue
            seen.add(link.group(2))
            found += 1
            visible = re.sub(r"<[^>]+>", " | ", card[:6000])
            offices = sorted(set(m.strip() for m in re.findall(r"(?:Tel Aviv|Haifa|Jerusalem|Herzliya|Petah Tikva)[^|;]{0,20}?Israel", visible)))
            jobs.append(Job(company=company, title=title, location="; ".join(offices) or "Israel",
                            url=_G_BASE + link.group(1), ats="google", slug=slug, job_id=link.group(2)))
        if not found:
            break
        time.sleep(0.5)
    return jobs


READERS = {"comeet_api": from_comeet_api, "google": from_google}
DESCRIBERS = {"comeet_api": comeet_api_description, "google": page_description}
