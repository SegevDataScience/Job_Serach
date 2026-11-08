#!/usr/bin/env python3
"""
company_sites_b2.py — second batch of company career-site readers (verified
2026-11-07): credit cards, telecom, media, health, IT services. Imported at the
end of company_sites.py, which merges READERS / DESCRIBERS from here.

Many of these give a region ("מרכז", "גוש דן") or nothing, not a city. The
location built here is region + a wanted city named in the title (or a known
default), so the normal location filter in find_jobs.score_job can judge it.
Defaults are used only where checked: Keshet (its jobs site says Tel Aviv),
Sheba (Tel HaShomer, Ramat Gan).
"""

from __future__ import annotations

import base64
import html as htmlmod
import json
import re

from curl_cffi import requests as cr

from company_sites import _get, _wanted_place, page_description
from find_jobs import Job


# Places outside his regions that titles name ("נציג/ה באשדוד", "מוקד צפון"): such a job is not
# "city not stated", it is elsewhere.
_ELSEWHERE = re.compile(r"מודיעין עילית|ביתר|אשדוד|אשקלון|חיפה|קריות|נשר|באר שבע|נתניה|כפר סבא|רעננה|הוד השרון|רחובות|קריית גת|קרית גת|"
                        r"נוף הגליל|נצרת|עפולה|טבריה|כרמיאל|אילת|חדרה|צפון|דרום|השרון|יוקנעם|יקנעם|קיסריה|לוד|רמלה|"
                        r"haifa|ashdod|netanya|beer sheva|north|south")


def _place_loc(region: str, title: str, default_city: str = "", keep_unstated: bool = False) -> str:
    """keep_unstated: for employers whose postings never name a place (Max, Cal), a title with
    no place at all is kept as "city not stated" (score_job lets those through) instead of lost."""
    parts = [p for p in ((region or "").strip(), _wanted_place(title) or default_city) if p]
    if parts:
        return ", ".join(parts) + ", Israel"
    if keep_unstated and not _ELSEWHERE.search((title or "").lower()):
        return "Israel (city not stated)"
    return "Israel"


def _iso(text: str) -> str:
    text = (text or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else ""


def _strip(raw: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", raw or "")).strip()


def _post(url: str, timeout: int = 60, **kw):
    response = cr.post(url, impersonate="chrome", timeout=timeout, **kw)
    response.raise_for_status()
    return response


def from_comeet_city(company: str, slug: str) -> list[Job]:
    """Comeet board whose postings carry no location. slug = "<comeet slug>|<city>"."""
    from find_jobs import from_comeet

    board, _, city = slug.partition("|")
    jobs = from_comeet(company, board)
    for job in jobs:
        job.location = job.location or f"{city}, Israel"
        job.slug = board  # description fetch then goes through the normal comeet path
    return jobs


def from_ness(company: str, slug: str) -> list[Job]:
    data = _get("https://www.ness-tech.co.il/careers/api/Careers/GetOrderDetailsList",
                params={"profId": "", "areasId": "", "freeText": "", "isHot": "false", "rows": 500, "page": 1}).json()
    return [Job(company=company, title=(r.get("title") or "").strip(),
                location=_place_loc(r.get("posLocation") or "", r.get("title") or ""),
                url=f"https://www.ness-tech.co.il/careers/job/{r.get('index')}", ats="ness", slug=slug,
                job_id=str(r.get("index", "")), updated=_iso(r.get("lastUpdated") or ""))
            for r in data.get("allOrderDetailsList") or []]


def from_max(company: str, slug: str) -> list[Job]:
    data = _get("https://www.max.co.il/api/lobby/getLobby", params={
        "lobbyName": "jobs", "page": 0, "isMobile": "false", "catHashName": "", "isBusiness": "false"}).json()
    jobs = []
    for cat in (data.get("result") or {}).get("categories") or []:
        for p in ((cat.get("pages") or {}).get("pages")) or []:
            link = (p.get("linkUrl") or "").split("?")[0]
            url = link if link.startswith("http") else "https://www.max.co.il" + link
            title = (p.get("title") or "").strip()
            jobs.append(Job(company=company, title=title, location=_place_loc("", title, keep_unstated=True), url=url,
                            ats="max", slug=slug, job_id=url))
    return jobs


def from_isracard(company: str, slug: str) -> list[Job]:
    session = cr.Session(impersonate="chrome")
    session.get("https://www.isracard.co.il/career/_api/v1/access-tokens", timeout=30)
    query = {"dataCollectionId": "JobObject", "query": {"filter": {}, "paging": {"offset": 0, "limit": 1000}, "fields": []},
             "referencedItemOptions": [], "returnTotalCount": True, "environment": "LIVE",
             "appId": "7ffafa09-8bdc-4734-9253-7f7c7233013f"}
    r = base64.b64encode(json.dumps(query, separators=(",", ":")).encode()).decode()
    response = session.get(f"https://www.isracard.co.il/career/_api/cloud-data/v2/items/query?.r={r}", timeout=30)
    response.raise_for_status()
    areas = {"10": "צפון", "30": "השרון", "40": "מרכז", "70": "דרום"}
    jobs = []
    for item in response.json().get("dataItems") or []:
        d = item.get("data") or {}
        title = (d.get("title") or "").strip()
        created = d.get("_createdDate") or {}
        created = created.get("$date", "") if isinstance(created, dict) else str(created)
        jobs.append(Job(company=company, title=title,
                        # Isracard's site gives its address as Bnei Brak; a central/unspecified job without a city goes there.
                        location=_place_loc(area := areas.get(str(int(d.get("JobAreaCode1") or 0)), ""), title,
                                            "בני ברק" if area in ("מרכז", "") and not _ELSEWHERE.search(title) else ""),
                        url="https://www.isracard.co.il/career" + (d.get("link-mshrvt-title") or ""),
                        ats="isracard", slug=slug, job_id=str(int(d["JobNumber"])) if d.get("JobNumber") else str(d.get("_id", "")),
                        updated=created[:10] or _iso(d.get("AdamUpdateDate") or "")))
    return jobs


def from_cal(company: str, slug: str) -> list[Job]:
    url = "https://www.cal-online.co.il/about/jobs/"
    page = _get(url).text
    jobs = []
    for block in re.split(r'<div[^>]*class="[^"]*\bjobItem\b', page)[1:]:
        title = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        job_id = re.search(r'data-job-id="([^"]+)"', block)
        if not title or not job_id:
            continue
        t = _strip(title.group(1))
        jobs.append(Job(company=company, title=t, location=_place_loc("", t, keep_unstated=True), url=f"{url}#{job_id.group(1)}",
                        ats="cal", slug=slug, job_id=job_id.group(1)))
    return jobs


def from_bezeq(company: str, slug: str) -> list[Job]:
    data = _get("https://d-api.bezeq.co.il/api/Adam/GetActiveJobs",
                headers={"Referer": "https://www.bezeq.co.il/career_new/", "Origin": "https://www.bezeq.co.il"}).json()
    jobs = []
    for r in data.get("data") or []:
        title = (r.get("description") or r.get("tat_profession_name") or "").strip()
        keys = ["Order_place", "work_area"] + [f"living_area{i}" for i in range(1, 7)]
        region = ", ".join(dict.fromkeys(str(r[k]).strip() for k in keys if r.get(k)))
        jobs.append(Job(company=company, title=title, location=_place_loc(region, title),
                        url=f"https://www.bezeq.co.il/career/jobs/form/?jobs={r.get('order_id')}", ats="bezeq", slug=slug,
                        job_id=str(r.get("order_id", "")), updated=_iso(r.get("update_date") or r.get("orderDate") or "")))
    return jobs


def from_adamtotal(company: str, slug: str) -> list[Job]:
    """career.adamtotal.co.il board (Partner). slug = the company token."""
    jobs, seen = [], set()
    for page in range(1, 30):
        text = _get(f"https://career.adamtotal.co.il/Home/Index?page={page}&token={slug}", timeout=60).text
        text = re.sub(r'src="data:image[^"]+"', "", text)  # every card embeds a base64 logo
        for card in re.split(r"<article", text)[1:]:
            if "job-card" not in card[:400]:
                continue
            title = re.search(r'data-job-title="([^"]*)"', card)
            job_id = re.search(r'data-job-id="([^"]*)"', card)
            link = re.search(r'<a[^>]*class="[^"]*job-detail-link[^"]*"[^>]*href="([^"]+)"', card) \
                or re.search(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*job-detail-link', card)
            if not title or not job_id or job_id.group(1) in seen:
                continue
            seen.add(job_id.group(1))
            loc = re.search(r'fa-map-marker-alt[^>]*>\s*</i>(.*?)</span>', card, re.S)
            t = htmlmod.unescape(title.group(1)).strip()
            href = htmlmod.unescape(link.group(1)) if link else ""
            jobs.append(Job(company=company, title=t, location=_place_loc(_strip(loc.group(1)) if loc else "", t),
                            url=href if href.startswith("http") else "https://career.adamtotal.co.il" + href,
                            ats="adamtotal", slug=slug, job_id=job_id.group(1)))
        if not re.search(r"PagedList-skipToNext[^>]*>\s*<a[^>]*href=", text):
            break
    return jobs


def from_cellcom(company: str, slug: str) -> list[Job]:
    data = _get("https://contentepi.cellcom.co.il/jobs/Careersportal/",
                params={"expand": "*", "currentPageUrl": "/jobs/Careersportal/"},
                headers={"Accept": "application/json", "Origin": "https://cellcom.co.il", "Referer": "https://cellcom.co.il/"}).json()
    jobs = []
    for ad in (data.get("listAdsCareers") or {}).get("expandedValue") or []:
        if (ad.get("isHiddenAd") or {}).get("value"):
            continue
        title = (ad.get("name") or (ad.get("title") or {}).get("value") or "").strip()
        places = (ad.get("listOfCareerLocations") or {}).get("value") or []
        jobs.append(Job(company=company, title=title, location=_place_loc(", ".join(map(str, places)), title),
                        url="https://cellcom.co.il" + (ad.get("url") or ""), ats="cellcom", slug=slug,
                        job_id=str((ad.get("codeJob") or {}).get("value") or ad.get("url", "")),
                        updated=(ad.get("changed") or "")[:10]))
    return jobs


def from_hot(company: str, slug: str) -> list[Job]:
    response = _post("https://www.hot.net.il/HotCmsApiFront/api/MarketingJob/GetJobs",
                     headers={"Accept": "application/json, text/plain, */*", "Content-Type": "application/json",
                              "Referer": "https://www.hot.net.il/heb/careersearch/", "Origin": "https://www.hot.net.il"})
    data = json.loads(response.text)  # labelled text/plain
    if isinstance(data, str):
        data = json.loads(data)
    jobs = []
    for v in (data.get("data") or {}).get("vacanciesDetails") or []:
        title = re.sub(r"\s+", " ", v.get("jobTitle") or "").strip()
        jobs.append(Job(company=company, title=title, location=_place_loc(v.get("location") or "", title),
                        url=f"https://www.hot.net.il/heb/careersearch/#{v.get('vacancyName', '')}", ats="hot", slug=slug,
                        job_id=str(v.get("vacancyName", ""))))
    return jobs


def from_clalit(company: str, slug: str) -> list[Job]:
    response = _post("https://jobs.clalitapps.co.il/CandidateAPI/api//position/Search/9E6C0368-A39E-4D83-803E-CF2AF0BA28DD",
                     json={"KeyWords": "", "CategoryId": [], "countryId": 2, "cityId": []}, timeout=90)
    jobs = []
    for p in response.json().get("positions") or []:
        title = (p.get("jobTitleText") or "").strip()
        employer = p.get("affiliateDisplayName") or ""
        jobs.append(Job(company=f"{company} — {employer}" if employer else company, title=title,
                        location=_place_loc(p.get("displayLocation") or "", title),
                        url="https://jobs.clalitapps.co.il/clalit/redmatch-apply/redmatch.apply.html?compPositionID="
                            + str(p.get("compPositionID", "")),
                        ats="clalit", slug=slug, job_id=str(p.get("compPositionID", "")),
                        updated=(p.get("activationDate") or "")[:10]))
    return jobs


def from_maccabi(company: str, slug: str) -> list[Job]:
    jobs, seen = [], set()
    for page in range(20):
        data = _post("https://www.maccabi4u.co.il/api/maccabi/SearchJobsApi/FilterJobs",
                     json={"Areas": [], "Professions": [], "Jobs": [], "FreeText": "", "ResultsPerPage": 200,
                           "PageNumber": page, "AdvertisingDestination": "1"},
                     headers={"Referer": "https://www.maccabi4u.co.il/careers/search-job-positions/"}).json()
        results = data.get("Results") or []
        for r in results:
            url = r.get("JobUrl") or ""
            if url in seen:
                continue
            seen.add(url)
            title = (r.get("Description") or "").strip()
            areas = ", ".join(a.get("Description", "") for a in r.get("Areas") or [])
            jobs.append(Job(company=company, title=title, location=_place_loc(areas, title),
                            url=url if url.startswith("http") else "https://www.maccabi4u.co.il" + url,
                            ats="maccabi", slug=slug, job_id=str(r.get("JobId") or url)))
        if not results or len(seen) >= int(data.get("TotalResults") or 0):
            break
    return jobs


def from_sheba(company: str, slug: str) -> list[Job]:
    body = {"indexes": ["he_job_index"], "query": {"from": 0, "size": 10000, "query": {
        "bool": {"filter": [], "must": [], "should": [], "minimum_should_match": 0}}}}
    data = _post("https://www.sheba.co.il/api/Information/search", json=body,
                 headers={"Referer": "https://www.sheba.co.il/general/guides/career", "Origin": "https://www.sheba.co.il",
                          "Accept": "application/json"}).json()
    jobs = []
    for hit in (data.get("hits") or {}).get("hits") or []:
        s = hit.get("_source") or {}
        if str(s.get("audienceType", "0")) != "0":  # 1/2 include "Sheba employees only" postings
            continue
        title = (s.get("title") or "").strip()
        jobs.append(Job(company=company, title=title, location=_place_loc("", title, "רמת גן"),
                        url=f"https://www.sheba.co.il/general/guides/career?job={s.get('id')}", ats="sheba", slug=slug,
                        job_id=str(s.get("id", "")), updated=(s.get("publishDate") or "")[:10]))
    return jobs


READERS = {"comeet_city": from_comeet_city, "ness": from_ness, "max": from_max, "isracard": from_isracard,
           "cal": from_cal, "bezeq": from_bezeq, "adamtotal": from_adamtotal, "cellcom": from_cellcom,
           "hot": from_hot, "clalit": from_clalit, "maccabi": from_maccabi, "sheba": from_sheba}
DESCRIBERS = {ats: page_description for ats in
              ("ness", "max", "isracard", "bezeq", "adamtotal", "cellcom", "clalit", "maccabi", "sheba")}
