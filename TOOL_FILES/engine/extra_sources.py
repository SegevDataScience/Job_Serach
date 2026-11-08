#!/usr/bin/env python3
"""
extra_sources.py — job sources that are not job boards.

    LinkedIn posts   recruiting posts ("מחפשים אנליסט/ית", "we're hiring") found
                     through Yahoo search, since LinkedIn post search needs a
                     login. Yahoo is the only engine that answered without a
                     captcha (tested 2026-10-02: DuckDuckGo, Bing, Brave,
                     Startpage, Mojeek, Google all blocked or ignored site:).
    Civil service    the נציבות שירות המדינה tender system (merkava.mrp.gov.il),
                     every open tender in one OData call.
    gov.il דרושים    the listings ministries and hospitals publish on gov.il,
                     via the public API the gov.il site itself calls.

All three need curl_cffi (Chrome TLS fingerprint) except gov.il, which only
needs the Origin/Referer headers. Each returns Job objects plus the text used
for the bank/insurance check; filtering happens in market_sources.scan_market.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
import time
import urllib.parse
from typing import Any

from find_jobs import Job, html_to_text

try:
    from curl_cffi import requests as cr
except ImportError:  # the sources below report themselves as skipped
    cr = None


def _need_curl() -> None:
    if cr is None:
        raise RuntimeError("curl_cffi is not installed (pip install curl_cffi)")


# ==========================================================================
# LinkedIn recruiting posts (via Yahoo)
# ==========================================================================

_POST_ID = re.compile(r"(?:activity|ugcPost|share)[-:](\d{16,20})")
_HEBREW = re.compile(r"[֐-׿]")


def _post_date(url: str) -> dt.datetime | None:
    """A LinkedIn post id carries its creation time: (id >> 22) = epoch ms."""
    match = _POST_ID.search(url)
    if not match:
        return None
    try:
        return dt.datetime.fromtimestamp((int(match.group(1)) >> 22) / 1000, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _yahoo(query: str, page: int) -> list[dict[str, str]]:
    from bs4 import BeautifulSoup

    params = {"p": query, "b": page * 7 + 1} if page else {"p": query}
    response = cr.get("https://search.yahoo.com/search", params=params, impersonate="chrome", timeout=20)
    if response.status_code != 200:
        raise RuntimeError(f"Yahoo HTTP {response.status_code}")
    hits = []
    for div in BeautifulSoup(response.text, "html.parser").select("div.algo"):
        link = div.find("a")
        if not link:
            continue
        href = link.get("href", "")
        real = re.search(r"/RU=([^/]+)/", href)
        url = urllib.parse.unquote(real.group(1)) if real else href
        if "linkedin.com/posts/" not in url:
            continue
        snippet = div.select_one(".compText, p")
        hits.append({
            "url": url.split("?")[0],
            "title": (div.find("h3") or link).get_text(" ", strip=True),
            "snippet": snippet.get_text(" ", strip=True) if snippet else "",
        })
    return hits


def fetch_post(url: str) -> tuple[str, str, str] | None:
    """Public post page, no login -> (author, text, ISO date) from its JSON-LD."""
    from bs4 import BeautifulSoup

    try:
        response = cr.get(url, impersonate="chrome", timeout=20)
        if response.status_code != 200 or "authwall" in response.url:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("@type") in ("SocialMediaPosting", "DiscussionForumPosting", "Article"):
                author = data.get("author") or {}
                author = author.get("name", "") if isinstance(author, dict) else str(author)
                text = (data.get("articleBody") or data.get("text") or "").strip()
                return author, text, data.get("datePublished", "")
        og = soup.find("meta", property="og:description")
        if og:
            title = soup.find("meta", property="og:title")
            return (title["content"].split("|")[-1].strip() if title else ""), og["content"].strip(), ""
    except Exception:
        pass
    return None


def _looks_israeli(text: str, locations: list[str]) -> bool:
    low = text.lower()
    return bool(_HEBREW.search(text)) or any(loc.lower() in low for loc in locations)


def scan_linkedin_posts(settings: dict[str, Any], days: int, locations: list[str],
                        title_keywords: list[str] = ()) -> list[tuple[Job, str]]:
    _need_curl()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    pages = int(settings.get("pages_per_query", 2))
    seen: set[str] = set()
    found: list[tuple[Job, str]] = []
    for query in settings.get("queries", []):
        if "linkedin.com" not in query:
            query = "site:linkedin.com/posts " + query
        for page in range(pages):
            try:
                hits = _yahoo(query, page)
            except Exception as exc:
                print(f"         LinkedIn posts: search failed ({exc})")
                break
            time.sleep(random.uniform(2.0, 3.5))
            if not hits:
                break
            for hit in hits:
                url = hit["url"]
                if url in seen:
                    continue
                seen.add(url)
                posted = _post_date(url)
                if posted and posted < cutoff:
                    continue  # too old, known from the URL without fetching it
                author = hit["title"].split("|")[-1].replace("- LinkedIn", "").strip() if "|" in hit["title"] else ""
                text = hit["snippet"]
                post = fetch_post(url)
                time.sleep(random.uniform(1.0, 2.0))
                if post:
                    author, text = post[0] or author, post[1] or text
                if not _looks_israeli(text, locations):
                    continue
                # A post has no title: the first sentence naming a role stands in
                # for one, so the normal title filter can judge it.
                sentences = [s.strip() for s in re.split(r"[\n.!?]", text) if s.strip()]
                first_line = next((s for s in sentences if any(k.lower() in f" {s.lower()} " for k in title_keywords)),
                                  sentences[0] if sentences else "")[:110]
                found.append((Job(
                    company=author or "LinkedIn post",
                    title=first_line or "(post)",
                    # A post has no location field: use the first wanted city its text names.
                    # No city named: kept (score_job lets these through), shown as "city not stated".
                    location=next((loc for loc in locations if loc.lower() in text.lower()), "Israel (LinkedIn post, city not stated)"),
                    url=url,
                    ats="linkedin_post",
                    slug="",
                    job_id=url,
                    updated=posted.date().isoformat() if posted else "",
                ), text))
    return found


# ==========================================================================
# Civil service tenders (נציבות שירות המדינה)
# ==========================================================================

MERKAVA = "https://merkava.mrp.gov.il"
TENDERS = MERKAVA + "/sap/opu/odata/ILG/GIUS_PUBLIC_AREA_SRV/TenderDataSet"


def _sap_date(value: str) -> str:
    match = re.search(r"/Date\((-?\d+)\)/", value or "")
    if not match:
        return ""
    return dt.datetime.fromtimestamp(int(match.group(1)) / 1000, dt.timezone.utc).date().isoformat()


def _merkava_session():
    session = cr.Session(impersonate="chrome")
    session.get(MERKAVA + "/giusp/index.html", timeout=30)  # firewall cookies; the API 404s without them
    return session


def _merkava_get(session, url: str) -> dict[str, Any]:
    response = session.get(url, params={"$format": "json", "sap-client": "470"},
                           headers={"sap-language": "he", "Accept": "application/json",
                                    "Referer": MERKAVA + "/giusp/index.html"}, timeout=90)
    response.raise_for_status()
    return response.json()["d"]


def scan_civil_service() -> list[tuple[Job, str]]:
    """Every open tender; the title filter in score_job does the selecting."""
    _need_curl()
    found = []
    for tender in _merkava_get(_merkava_session(), TENDERS)["results"]:
        org = " / ".join(x for x in (tender.get("OfficeName"), tender.get("OfficeUnitName")) if x)
        found.append((Job(
            company=org or "שירות המדינה",
            title=(tender.get("TenderName") or tender.get("JobName") or "").strip(),
            location=f"{tender.get('LocationName') or tender.get('Area') or ''}, Israel",
            url=f"{MERKAVA}/giusp/index.html#/position/{tender.get('RequestId')}",
            ats="civil_service",
            slug="",
            job_id=str(tender.get("RequestId") or ""),
            updated=_sap_date(tender.get("TenderPublicationDate")),
        ), ""))
    return found


# ==========================================================================
# gov.il דרושים
# ==========================================================================

GOVIL_API = "https://openapi-gc.digital.gov.il/pub/cio/govil/rest/collectors/v1/api/DataCollector/GetResults"
# Public client id, published in gov.il/CollectorsWebApi/client-config.js.
GOVIL_HEADERS = {
    "x-client-id": "9KFgciHHGDyNiqz5MdQS0eK2ApeJYMc6YnElUICpN1atirZc",
    "Origin": "https://www.gov.il",
    "Referer": "https://www.gov.il/",
    "User-Agent": "Mozilla/5.0",
}


def scan_govil(settings: dict[str, Any]) -> list[tuple[Job, str]]:
    import requests

    page_size, pages = 50, int(settings.get("pages_per_keyword", 3))
    seen: set[str] = set()
    found = []
    for keyword in settings.get("keywords", []):
        for page in range(pages):
            params = {"CollectorType": "drushim", "culture": "he", "skip": page * page_size,
                      "limit": page_size, "keywords": keyword}
            payload = requests.get(GOVIL_API, params=params, headers=GOVIL_HEADERS, timeout=30).json()
            results = payload.get("results", [])
            for item in results:
                tags = item.get("tags") or {}
                meta, promoted = tags.get("metaData") or {}, tags.get("promotedMetaData") or {}
                first = lambda d, k: (d.get(k) or [{}])[0].get("title", "")
                if first(promoted, "סטטוס") != "פעיל":
                    continue
                url = "https://www.gov.il" + item.get("url", "")
                if url in seen:
                    continue
                seen.add(url)
                published = first(meta, "תאריך פרסום")
                try:
                    published = dt.datetime.strptime(published, "%d.%m.%Y").date().isoformat()
                except ValueError:
                    published = ""
                found.append((Job(
                    company=first(meta, "משרד") or "gov.il",
                    title=(item.get("title") or "").strip(),
                    location=f"{first(meta, 'יישוב') or first(meta, 'מיקום')}, Israel",
                    url=url,
                    ats="govil",
                    slug="",
                    job_id=url,
                    updated=published,
                ), ""))
            if len(results) < page_size or page * page_size + len(results) >= payload.get("total", 0):
                break
    return found


# ==========================================================================
# Full text for --pick / tailoring
# ==========================================================================


def fetch_description(source: str, job_id: str) -> str:
    _need_curl()
    if source == "linkedin_post":
        post = fetch_post(job_id)
        if not post or not post[1]:
            raise SystemExit("ERROR: LinkedIn did not return that post without a login.")
        return post[1]
    if source == "civil_service":
        tender = _merkava_get(_merkava_session(), f"{TENDERS}('{job_id}')")
        return html_to_text(f"{tender.get('JobDes') or ''}\n\n{tender.get('JobRequirements') or ''}")
    if source == "govil":
        page = cr.get(job_id, impersonate="chrome", timeout=30).text
        return html_to_text(page)
    raise SystemExit(f"ERROR: unknown source {source!r}.")
