"""AllJobs + JobMaster guest scrapers (server-rendered HTML, no login)."""
import json
import re
import time
from datetime import date, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9,en;q=0.8"}


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _get(s, url, retries=3, **kw):
    """GET with retry: AllJobs occasionally drops a kept-alive connection (RemoteDisconnected)."""
    for i in range(retries):
        try:
            r = s.get(url, timeout=30, **kw)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            if i == retries - 1:
                raise
        time.sleep(3 * (i + 1))
    return r


def _rel_date(txt, today=None):
    """'לפני 5 שעות' / '3 ימים' / 'פורסם לפני 22 ימים' / '24/09/2026' -> ISO date."""
    today = today or date.today()
    txt = (txt or "").strip()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", txt)
    if m:
        d, mo, y = map(int, m.groups())
        return date(y, mo, d).isoformat()
    if re.search(r"דקות|דקה|שעות|שעה|היום", txt):
        return today.isoformat()
    m = re.search(r"(\d+)\s*ימים", txt)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    if "אתמול" in txt or re.search(r"(^|\s)יום(\s|$)", txt):
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*(שבועות|שבוע)", txt)
    if m:
        return (today - timedelta(weeks=int(m.group(1)))).isoformat()
    return ""


def _clean(t):
    t = (t or "").replace("\r", "")
    return re.sub(r"[ \t ]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


# ----------------------------------------------------------------- AllJobs
AJ_BASE = "https://www.alljobs.co.il"


def _aj_parse(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for box in soup.find_all("div", id=re.compile(r"^job-box\d+$")):
        jid = box["id"][len("job-box"):]
        top = box.find("div", class_="job-content-top")
        if not top:
            continue
        tdiv = top.find("div", class_=re.compile(r"^job-content-top-title"))
        a = tdiv.find("a", href=re.compile(r"UploadSingle\.aspx")) if tdiv else None
        h2 = a.find("h2") if a else None
        title = re.sub(r"\s+", " ", (h2 or a).get_text(" ", strip=True)) if a else ""
        # SEO prefixes AllJobs injects into some titles
        title = re.sub(r"^(דרושים|הצעות עבודה|חיפוש עבודה|משרות|עבודה)\s*\|\s*", "", title)
        comp_el = tdiv.find("div", class_="T14") if tdiv else None
        # empty T14 + class "closed-job" = confidential employer ("חברה חסויה")
        company = comp_el.get_text(" ", strip=True) if comp_el else ""
        loc_el = top.find("div", class_=re.compile(r"^job-content-top-location"))
        location = ""
        if loc_el:
            links = [x.get_text(" ", strip=True) for x in loc_el.find_all("a")]
            location = ", ".join(l for l in links if l) or re.sub(
                r"^(מיקום המשרה|Location)\s*:\s*", "", loc_el.get_text(" ", strip=True))
        date_el = top.find("div", class_="job-content-top-date")
        desc_el = top.find("div", class_=re.compile(r"job-content-top-desc"))
        text = _clean(desc_el.get_text("\n", strip=True)) if desc_el else ""
        out.append({
            "company": company, "title": title, "location": location,
            "url": f"{AJ_BASE}/Search/UploadSingle.aspx?JobID={jid}",
            "job_id": jid,
            "updated": _rel_date(date_el.get_text(" ", strip=True)) if date_el else "",
            "text": text,
        })
    return out


def scan_alljobs(keywords, pages=1, delay=2.0):
    s = _session()
    seen, res = set(), []
    for kw in keywords:
        for p in range(1, pages + 1):
            try:
                r = _get(s, f"{AJ_BASE}/SearchResultsGuest.aspx",
                         params={"page": p, "position": "", "type": "", "freetxt": kw})
                r.raise_for_status()
            except requests.RequestException as exc:
                # One slow page (2026-11-08: a 30 s read timeout) used to drop all of AllJobs.
                print(f"         AllJobs: skipped '{kw}' page {p} ({type(exc).__name__})", flush=True)
                break
            r.encoding = "utf-8"  # server declares charset=utf-8
            jobs = _aj_parse(r.text)
            for j in jobs:
                if j["job_id"] not in seen:
                    seen.add(j["job_id"])
                    j["keyword"] = kw
                    res.append(j)
            if not jobs:
                break
            time.sleep(delay)
    return res


def fetch_alljobs_description(job_id_or_url):
    m = re.search(r"(\d{5,})", str(job_id_or_url))
    jid = m.group(1)
    r = _get(_session(), f"{AJ_BASE}/Search/UploadSingle.aspx", params={"JobID": jid})
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    el = soup.find(id=f"job-content-top-acord{jid}")
    if el:
        for x in el.select('[class*="moretext"], [class*="moreimg"]'):
            x.decompose()
        txt = _clean(el.get_text("\n", strip=True))
        if txt:
            return txt
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(sc.string or "")
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return _clean(d.get("description", ""))
    return ""


# ---------------------------------------------------------------- JobMaster
JM_BASE = "https://www.jobmaster.co.il"
# Guests only get page 1 (10 jobs); ?currPage>=2 302s to account.jobmaster.co.il login.
# Extra "pages" are emulated by re-running the query restricted to a city (l-<city>).
JM_CITIES = ["תל אביב יפו", "הרצליה", "פתח תקווה", "רמת גן", "ירושלים", "חיפה",
             "ראשון לציון", "רעננה", "כפר סבא", "נתניה", "הוד השרון", "רחובות",
             "חולון", "יקנעם עילית", "באר שבע", "מודיעין מכבים רעות"]


def _jm_slug(t):
    return quote(re.sub(r"\s+", "-", t.strip()))


def _jm_parse(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for art in soup.select("article.JobItem"):
        jid = (art.get("id") or "").replace("misra", "")
        if not jid.isdigit():
            continue
        a = art.select_one("a.CardHeader")
        comp = art.select_one(".CompanyNameLink")
        loc = art.select_one("li.jobLocation")
        dt = art.select_one(".paddingTop10px .Gray")
        desc = art.select_one(".jobShortDescription")
        out.append({
            "company": comp.get_text(" ", strip=True) if comp else "",
            "title": a.get_text(" ", strip=True) if a else "",
            "location": re.sub(r"\s*,\s*", ", ", loc.get_text(" ", strip=True)) if loc else "",
            "url": f"{JM_BASE}/jobs/checknum.asp?key={jid}",
            "job_id": jid,
            "updated": _rel_date(dt.get_text(" ", strip=True)) if dt else "",
            "text": _clean(desc.get_text("\n", strip=True)) if desc else "",
        })
    return out


def scan_jobmaster(keywords, pages=1, delay=2.0):
    """pages=1 -> the 10 guest-visible jobs per keyword; pages=N -> plus N-1 city-filtered queries."""
    s = _session()
    seen, res = set(), []
    for kw in keywords:
        urls = [f"{JM_BASE}/jobs/q-{_jm_slug(kw)}/"]
        urls += [f"{JM_BASE}/jobs/q-{_jm_slug(kw)}/l-{_jm_slug(c)}/" for c in JM_CITIES[:max(0, pages - 1)]]
        for u in urls:
            try:
                r = _get(s, u)
            except requests.RequestException as exc:  # one slow page must not drop the whole source
                print(f"         JobMaster: skipped {u} ({type(exc).__name__})", flush=True)
                continue
            if "account.jobmaster.co.il" in r.url:  # login wall
                continue
            r.encoding = "utf-8"
            for j in _jm_parse(r.text):
                if j["job_id"] not in seen:
                    seen.add(j["job_id"])
                    j["keyword"] = kw
                    res.append(j)
            time.sleep(delay)
    return res


def fetch_jobmaster_description(job_id_or_url):
    jid = re.search(r"(\d{6,})", str(job_id_or_url)).group(1)
    r = _get(_session(), f"{JM_BASE}/jobs/checknum.asp", params={"key": jid})
    r.raise_for_status()
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    parts = []
    for i, label in [("jobDescriptionContent", "תיאור המשרה"), ("jobRequirementsContent", "דרישות")]:
        el = soup.find(id=i)
        if el:
            parts.append(f"{label}:\n" + _clean(el.get_text("\n", strip=True)))
    if not parts:
        m = soup.find("meta", attrs={"name": "description"})
        return (m.get("content") or "").strip() if m else ""
    return "\n\n".join(parts)


# ------------------------------------------------------- scanner integration

def as_jobs(rows, source):
    """Board dicts -> (find_jobs.Job, posting text) for market_sources."""
    from find_jobs import Job
    return [(Job(company=r["company"] or "חסוי", title=r["title"],
                 location=f"{r['location'] or 'Israel'}, Israel", url=r["url"],
                 ats=source, slug="", job_id=r["job_id"], updated=r["updated"]),
             r["text"]) for r in rows]
