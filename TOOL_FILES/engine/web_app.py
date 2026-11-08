#!/usr/bin/env python3
"""
web_app.py — START.bat's browser UI.

A small local server (127.0.0.1 only, standard library) that:
- starts a fresh scan on launch (`--scan`), showing progress in the page;
- serves the ranked jobs from jobs_found.json with derived fields the page
  filters on: city, region, posting age, source, tracker state;
- writes to applications.xlsx when you click "add to list" / "submitted";
- opens the tracker, the career sites and the manual-tailor file on request.

The server exits by itself a few minutes after the browser tab is closed
(the page pings it), unless a scan is still running.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import tracker  # noqa: E402
from find_jobs import Job, _text_key, fetch_description, job_state, tracker_index  # noqa: E402
from personalized_ranking import explain, load_candidate_profile, score_job_personalized  # noqa: E402
import skill_match  # noqa: E402

DATA_ROOT = ENGINE_DIR.parent.parent  # next to START.bat
JOBS_FILE = DATA_ROOT / "jobs_found.json"
INDEX_HTML = ENGINE_DIR / "web" / "index.html"
SCAN_SCRIPT = ENGINE_DIR / "find_jobs_combined.py"
LAST_DURATION = ENGINE_DIR / ".last_scan_seconds"
MANUAL_FILE = ENGINE_DIR / "job_description.txt"

HOST, PORT = "127.0.0.1", 8765  # fixed, so the page's saved filters/hidden jobs survive restarts
# If another program holds 8765 (2026-11-08: someone's `python -m http.server 8765`), the next free
# port is used instead of failing silently (there is no console window to show an error).
PORTS = [8765, 8766, 8767, 8768, 8769, 8770]
IDLE_EXIT_SECONDS = 180

SOURCE_LABELS = {
    "linkedin": "LinkedIn", "linkedin_post": "פוסט LinkedIn", "drushim": "דרושים",
    "alljobs": "AllJobs", "jobmaster": "JobMaster", "civil_service": "נציבות שירות המדינה",
    "govil": "gov.il", "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby",
    "comeet": "Comeet", "workday": "Workday", "smartrecruiters": "SmartRecruiters",
    "successfactors": "SuccessFactors", "manual_post": "פוסט (הוספת)",
    **{ats: "אתר החברה" for ats in ("hibob", "eightfold", "elbit", "matrix", "malam", "ness", "max", "isracard", "cal",
                                    "bezeq", "adamtotal", "cellcom", "hot", "clalit", "maccabi", "sheba", "redmatch",
                                    "hadassah", "mekorot", "strauss", "osem", "tnuva", "shufersal", "comeet_api",
                                    "google")},
}

# (city, district, patterns). Patterns are matched on the lowercased location
# after look-alikes (EXCLUDE) are cut out. Districts are his grouping for the
# filter (asked 2026-11-07), not the official ones; each city sits in exactly one.
JLM, DAN, HOLON, RISHON, MOD, OTHER = ("מחוז ירושלים", "מחוז תל אביב", "מחוז חולון", 'מחוז ראשל"צ',
                                      "מחוז מודיעין", "אחר")
DISTRICT_ORDER = [DAN, JLM, HOLON, RISHON, MOD, OTHER]
CITIES: list[tuple[str, str, list[str]]] = [
    ("תל אביב", DAN, ["tel aviv", "tel-aviv", "tlv", "jaffa", "תל אביב", "תל-אביב"]),
    ("ירושלים", JLM, ["jerusalem", "ירושלים"]),
    ("מבשרת ציון", JLM, ["mevaseret", "מבשרת"]),
    ("מודיעין", MOD, ["modiin", "modi'in", "מודיעין"]),
    ("שוהם", MOD, ["shoham", "שוהם"]),
    ("רמת גן", DAN, ["ramat gan", "ramat-gan", "רמת גן", "רמת-גן"]),
    ("גבעתיים", DAN, ["givatayim", "giv'atayim", "גבעתיים"]),
    ("בני ברק", DAN, ["bnei brak", "bnei-brak", "בני ברק"]),
    ("פתח תקווה", DAN, ["petah tikva", "petach tikva", "petah-tikva", "petach-tikva", "petah tiqva", "פתח תקווה", "פתח תקוה"]),
    ("הרצליה", DAN, ["herzliya", "herzliyya", "הרצליה"]),
    ("רמת השרון", DAN, ["ramat hasharon", "רמת השרון"]),
    ("חולון", HOLON, ["holon", "חולון"]),
    ("בת ים", HOLON, ["bat yam", "bat-yam", "בת ים"]),
    ("ראשון לציון", RISHON, ["rishon", "ראשון לציון"]),
    ("קריית אונו", DAN, ["kiryat ono", "kiryat-ono", "קרית אונו", "קריית אונו"]),
    ("אור יהודה", DAN, ["or yehuda", "אור יהודה"]),
    ("יהוד", DAN, ["yehud", "יהוד"]),
    ("גבעת שמואל", DAN, ["givat shmuel", "גבעת שמואל"]),
    ("ראש העין", DAN, ["rosh haayin", "rosh ha'ayin", "ראש העין"]),
    ("איירפורט סיטי", MOD, ["airport city", "ben gurion airport", "איירפורט", "קרית שדה התעופה", "נמל תעופה בן גוריון"]),
    ("אזור", HOLON, ["azor"]),
    ("גוש דן (בלי עיר)", DAN, ["גוש דן"]),
    ("פוסט בלי עיר", OTHER, ["city not stated"]),  # Matrix / Malam list regions, not cities  # the Hebrew name is also the word "area"
    ("רעננה", OTHER, ["raanana", "ra'anana", "רעננה"]),
    ("כפר סבא", OTHER, ["kfar saba", "kefar sava", "כפר סבא"]),
    ("הוד השרון", OTHER, ["hod hasharon", "הוד השרון"]),
    ("נתניה", OTHER, ["netanya", "נתניה"]),
    ("רחובות", RISHON, ["rehovot", "רחובות"]),
    ("נס ציונה", RISHON, ["ness ziona", "nes ziona", "נס ציונה"]),
    ("לוד", MOD, ["lod", "לוד"]),
    ("רמלה", MOD, ["ramla", "רמלה"]),
    ("חיפה", OTHER, ["haifa", "חיפה"]),
    ("יקנעם", OTHER, ["yokneam", "יקנעם"]),
    ("באר שבע", OTHER, ["beer sheva", "be'er sheva", "באר שבע"]),
    ("קיסריה", OTHER, ["caesarea", "קיסריה"]),
    ("בית שמש", JLM, ["beit shemesh", "בית שמש"]),
]
EXCLUDE = ["modiin ilit", "modiin illit", "modi'in illit", "מודיעין עילית", "even yehuda", "אבן יהודה",
           "tel mond", "תל מונד", "beit yehoshua", "בית יהושע"]
DISTRICTS = [("tel aviv district", "תל אביב והסביבה (בלי עיר)", DAN),
             ("jerusalem district", "ירושלים והסביבה (בלי עיר)", JLM),
             ("center district", "מרכז (בלי עיר)", OTHER)]


def place(location: str) -> tuple[list[str], list[str]]:
    """Cities and regions named in a free-text location."""
    text = (location or "").lower()
    for bad in EXCLUDE:
        text = text.replace(bad, " ")
    # "Ramat Gan, Tel Aviv District" names Ramat Gan, not Tel Aviv.
    districts = [d for d in DISTRICTS if d[0] in text]
    for key, *_ in districts:
        text = text.replace(key, " ")
    cities, regions = [], []
    for city, region, patterns in CITIES:
        # Hebrew allows a one-letter prefix: "בירושלים", "לתל אביב".
        if any(re.search(rf"(?<![a-zא-ת]){'[בלמוה]?' if p[0] >= 'א' else ''}{re.escape(p)}(?![a-zא-ת])", text)
               for p in patterns):
            cities.append(city)
            if region not in regions:
                regions.append(region)
    if not cities and districts:
        _, name, region = districts[0]
        cities, regions = [name], [region]
    return cities or ["לא צוין"], regions or [OTHER]


MANUAL_FILE_JOBS = ENGINE_DIR / "manual_jobs.json"  # posts you pasted in; survive rescans
RAW: list[dict] = []          # id -> the job as scanned/added (for the details panel)
DESCRIPTIONS: dict[int, str] = {}


def load_manual() -> list[dict]:
    try:
        return json.loads(MANUAL_FILE_JOBS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


FIRST_SEEN_FILE = ENGINE_DIR / "first_seen.json"  # url -> when a scan first returned it (for "new since last visit")


def _first_seen(urls: list[str]) -> dict:
    try:
        seen = json.loads(FIRST_SEEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = None
    if seen is None:  # first run: everything already on the list counts as old
        seen = {u: "2000-01-01T00:00:00" for u in urls}
    now = datetime.now().isoformat(timespec="seconds")
    changed = False
    for u in urls:
        if u and u not in seen:
            seen[u] = now
            changed = True
    if changed or not FIRST_SEEN_FILE.exists():
        try:
            FIRST_SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return seen


def load_jobs() -> dict:
    raw = json.loads(JOBS_FILE.read_text(encoding="utf-8")) if JOBS_FILE.exists() else []
    urls = {j.get("url") for j in raw}
    candidate = load_candidate_profile()
    for job in load_manual():
        if job.get("url") not in urls:
            job = dict(job, personalized_score=score_job_personalized(job, candidate))
            raw.append(job)
    RAW[:] = raw
    DESCRIPTIONS.clear()
    by_url, by_pair = tracker_index()
    seen = _first_seen([j.get("url", "") for j in raw])
    today = date.today()
    jobs = []
    for i, job in enumerate(raw):
        cities, regions = place(job.get("location", ""))
        updated = (job.get("updated") or "")[:10]
        try:
            age = (today - date.fromisoformat(updated)).days
        except ValueError:
            age = None
        ns = SimpleNamespace(url=job.get("url", ""), company=job.get("company", ""), title=job.get("title", ""))
        ats = job.get("ats", "")
        jobs.append({
            "id": i,
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "cities": cities,
            "regions": regions,
            "url": job.get("url", ""),
            "source": SOURCE_LABELS.get(ats, ats),
            "updated": updated,
            "age": age,
            "score": round(job.get("personalized_score", 0)),
            "leadership": bool(job.get("leadership")),
            **_fit_fields(job),
            "state": job_state(ns, by_url, by_pair),  # "", "listed" or "sent"
            "first_seen": seen.get(job.get("url", ""), ""),
        })
    scanned = datetime.fromtimestamp(JOBS_FILE.stat().st_mtime).strftime("%d/%m/%Y %H:%M") if JOBS_FILE.exists() else None
    city_district = {c: d for c, d, _ in CITIES}
    city_district.update({name: d for _, name, d in DISTRICTS})
    return {"scanned_at": scanned, "jobs": jobs, "districts": DISTRICT_ORDER, "city_district": city_district}


# ---------------------------------------------------------------- skill fit

SKILL_CACHE_FILE = ENGINE_DIR / "skill_cache.json"  # url -> skill_match.match() result; kept across scans
SKILL_LOCK = threading.Lock()
ENRICH = {"running": False, "done": 0, "total": 0}
ENRICH_LIMIT = None  # every job with a relevant title (score > 0), most relevant first; ~2.4 s each


def _load_skill_cache() -> dict:
    try:
        return json.loads(SKILL_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


SKILL_CACHE: dict = _load_skill_cache()


def _save_skill_cache() -> None:
    with SKILL_LOCK:
        data = json.dumps(SKILL_CACHE, ensure_ascii=False)
    try:
        SKILL_CACHE_FILE.write_text(data, encoding="utf-8")
    except OSError:
        pass


def _fit_fields(job: dict) -> dict:
    m = SKILL_CACHE.get(job.get("url", "")) or {}
    skill = m.get("score")
    fit = skill_match.overall(job.get("personalized_score", 0), skill)
    return {"skill": skill, "fit": fit, "fit_level": skill_match.level(fit), "years": m.get("years")}


def _skill_for(i: int) -> dict:
    """Fetch the description (via job_details) and score it against the CV."""
    job = RAW[i]
    details = job_details(i, with_skills=False)
    if details.get("error"):
        result = {"score": None, "have": [], "missing": [], "years": None, "error": True}
    else:
        result = skill_match.match(details.get("description", ""))
    with SKILL_LOCK:
        SKILL_CACHE[job.get("url", "")] = result
    return result


def enrich() -> None:
    """Background pass after a scan / on start: score the most relevant jobs
    whose descriptions were never scored. Sequential, so no site gets bursts."""
    if ENRICH["running"]:
        return
    ENRICH["running"] = True
    try:
        if not RAW:
            load_jobs()
        todo = [i for i in sorted(range(len(RAW)), key=lambda i: -RAW[i].get("personalized_score", 0))
                if RAW[i].get("personalized_score", 0) > 0 and RAW[i].get("url", "") not in SKILL_CACHE][:ENRICH_LIMIT]
        # A job whose description could not be fetched is cached with error=True and never retried in the
        # same pass; jobs from sources with no description at all (Cal, HOT) end up there too.
        ENRICH.update(done=0, total=len(todo))
        for n, i in enumerate(todo, 1):
            if SCAN.running:  # a new scan replaces RAW; start over when it ends
                break
            try:
                _skill_for(i)
            except Exception as exc:  # noqa: BLE001
                print(f"skill fit failed for {RAW[i].get('url')}: {exc}", flush=True)
            ENRICH["done"] = n
            if n % 5 == 0:
                _save_skill_cache()
            time.sleep(0.7)
        _save_skill_cache()
    finally:
        ENRICH["running"] = False


def start_enrich() -> None:
    threading.Thread(target=enrich, daemon=True).start()


def job_details(i: int, with_skills: bool = True) -> dict:
    """Score breakdown + the full posting text (fetched once, then cached)."""
    job = RAW[i]
    if with_skills:
        result = job_details(i, with_skills=False)
        if not result.get("error"):
            m = skill_match.match(result.get("description", ""))
            with SKILL_LOCK:
                SKILL_CACHE[job.get("url", "")] = m
            _save_skill_cache()
            result["skills"] = m
            result.update(_fit_fields(job))
        return result
    base = {"reasons": explain(job), "matched": job.get("matched", [])}
    if i not in DESCRIPTIONS:
        if job.get("text"):
            DESCRIPTIONS[i] = job["text"]
        else:
            try:
                fields = {k: job.get(k, "") for k in ("company", "title", "location", "url", "ats", "slug", "job_id", "updated")}
                try:
                    DESCRIPTIONS[i] = fetch_description(Job(**fields)) or ""
                except Exception as exc:  # LinkedIn answers 429 to quick repeats: wait once, retry
                    if "429" not in str(exc):
                        raise
                    time.sleep(3)
                    DESCRIPTIONS[i] = fetch_description(Job(**fields)) or ""
            except (Exception, SystemExit) as exc:  # fetchers raise SystemExit on a dead posting
                return dict(base, description="", error=f"לא הצלחתי להביא את תיאור המשרה ({exc}). פתח את הקישור.")
    return dict(base, description=DESCRIPTIONS[i][:20000])


# ---------------------------------------------------------------- career sites

HITECH, DEFENSE, FINANCE, TELECOM, HEALTH, INFRA, FOOD = (
    "הייטק", "ביטחוני", "כלכלי", "תקשורת ומדיה", "בריאות", "תשתיות ואנרגיה", "מזון וקמעונאות")
CATEGORY_ORDER = [HITECH, DEFENSE, FINANCE, TELECOM, HEALTH, INFRA, FOOD]
# English name in config -> (Hebrew name, category)
CAREER_HE = {
    "Amdocs": ("אמדוקס", HITECH), "Check Point": ("צ'ק פוינט", HITECH), "Cellebrite": ("סלברייט", HITECH),
    "Verint": ("ורינט", HITECH), "HiBob": ("HiBob", HITECH), "Sapiens": ("סאפיינס", HITECH),
    "Verbit": ("ורביט", HITECH), "Matrix": ("מטריקס", HITECH), "Malam Team": ("מלם תים", HITECH),
    "Ness": ("נס טכנולוגיות", HITECH),
    "Elbit Systems": ("אלביט מערכות", DEFENSE), "Rafael": ("רפאל", DEFENSE), "IAI": ("התעשייה האווירית", DEFENSE),
    "Max": ("מקס", FINANCE), "Isracard": ("ישראכרט", FINANCE), "Cal": ("כאל", FINANCE),
    "Bezeq": ("בזק", TELECOM), "Partner": ("פרטנר", TELECOM), "Cellcom": ("סלקום", TELECOM),
    "HOT": ("הוט", TELECOM), "Keshet": ("קשת מדיה", TELECOM),
    "Clalit": ("כללית", HEALTH), "Maccabi": ("מכבי", HEALTH), "Sheba": ("שיבא", HEALTH),
    "Hadassah": ("הדסה", HEALTH), "Ichilov": ("איכילוב", HEALTH),
    "Israel Electric (IEC)": ("חברת החשמל", INFRA), "Mekorot": ("מקורות", INFRA), "Israel Post": ("דואר ישראל", INFRA),
    "ZIM": ("צים", INFRA), "Bazan": ("בזן", INFRA),
    "Strauss": ("שטראוס", FOOD), "Osem-Nestle": ("אסם-נסטלה", FOOD), "Tnuva": ("תנובה", FOOD),
    "Shufersal": ("שופרסל", FOOD), "Super-Pharm": ("סופר-פארם", FOOD),
    "SAP Labs Israel": ("SAP Labs ישראל", HITECH), "Optibus": ("אופטיבוס", HITECH), "mavens by Zynga": ("mavens by Zynga", HITECH),
}


def career_sites() -> list[dict]:
    sites = []
    for site in _config().get("career_sites", []):
        he, category = CAREER_HE.get(site["name"], (site["name"], site.get("category", "אחר")))
        sites.append({"name": site["name"], "name_he": site.get("name_he", he),
                      "category": site.get("category", category), "url": site["url"]})
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(sites, key=lambda s: (order.get(s["category"], 99), s["name_he"]))


# ---------------------------------------------------------------- LinkedIn posts

# Searches opened in YOUR browser, where you are logged in to LinkedIn. Override
# with "linkedin_post_searches": [...] in job_search_config.json.
POST_SEARCHES = [
    '"data analyst" hiring israel', '"analytics engineer" hiring israel', '"data engineer" hiring "tel aviv"',
    '"data scientist" hiring israel', '"BI developer" hiring israel', '"team lead" data hiring israel',
    '"analytics manager" hiring israel', 'hiring data jerusalem',
    'מחפשים "אנליסט נתונים"', 'מגייסים דאטה', '"ראש צוות" דאטה מגייסים', '"מהנדס/ת נתונים" מחפשים',
]


def _config() -> dict:
    try:
        return json.loads((ENGINE_DIR / "job_search_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def post_searches() -> list[dict]:
    from urllib.parse import quote

    queries = _config().get("linkedin_post_searches") or POST_SEARCHES
    return [{"query": q, "url": "https://www.linkedin.com/search/results/content/?keywords=" + quote(q)
             + "&datePosted=%22past-week%22&sortBy=%22date_posted%22"} for q in queries]


def parse_post(url: str, text: str) -> dict:
    """Best guess at company / role / city / date for a post you pasted."""
    import extra_sources

    url, text = (url or "").strip(), (text or "").strip()
    author, posted = "", ""
    if url and not text:
        got = extra_sources.fetch_post(url)  # public post page, no login
        if got:
            author, text, posted = got[0], got[1], (got[2] or "")[:10]
    if url and not posted:
        when = extra_sources._post_date(url)
        posted = when.date().isoformat() if when else ""
    if not author:
        slug = re.search(r"linkedin\.com/posts/([^_/?]+)", url)
        author = slug.group(1).replace("-", " ").title() if slug else ""
    keywords = _config().get("title_keywords") or ["data", "analyst", "engineer"]
    sentences = [x.strip() for x in re.split(r"[\n.!?]", text) if x.strip()]
    title = next((x for x in sentences if any(k.lower() in f" {x.lower()} " for k in keywords)),
                 sentences[0] if sentences else "")[:110]
    cities, _ = place(text)
    return {"url": url, "company": author, "title": title, "updated": posted or date.today().isoformat(),
            "location": ", ".join(c for c in cities if c != "לא צוין"), "text": text, "fetched": bool(text)}


def add_post(entry: dict) -> None:
    url = (entry.get("url") or "").strip()
    jobs = [j for j in load_manual() if j.get("url") != url]
    title = (entry.get("title") or "").strip() or "(post)"
    jobs.append({
        "company": (entry.get("company") or "").strip() or "LinkedIn post",
        "title": title,
        # ", Israel" like every scanned source; the ranking docks points without it.
        "location": ((entry.get("location") or "").strip().rstrip(",") + ", Israel").lstrip(", ")
        if "israel" not in (entry.get("location") or "").lower() else entry["location"].strip(),
        "url": url, "ats": "manual_post", "slug": "", "job_id": url,
        "updated": entry.get("updated") or date.today().isoformat(),
        "text": entry.get("text", ""),
        "leadership": bool(re.search(r"lead|manager|head of|ראש צוות|מנהל", title, re.I)),
        "matched": [],
    })
    MANUAL_FILE_JOBS.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- tracker

def track(job: dict, submitted: bool) -> str:
    """Add the job to applications.xlsx (status לא), or mark it submitted (כן).
    Returns the new state: "listed" or "sent"."""
    workbook, sheet = tracker.load()
    url_key = (job.get("url") or "").strip().rstrip("/").lower()
    pair = (_text_key(job.get("company", "")), _text_key(job.get("title", "")))
    for row in sheet.iter_rows(min_row=2):
        cell = row[tracker.URL_COL - 1]
        url = str((cell.hyperlink.target if cell.hyperlink else cell.value) or "").strip().rstrip("/").lower()
        if (url_key and url == url_key) or (_text_key(row[1].value), _text_key(row[2].value)) == pair:
            if submitted:
                row[tracker.STATUS_COL - 1].value = tracker.SUBMITTED
                if not row[6].value:
                    row[6].value = date.today().isoformat()
                tracker.save(workbook)
                return "sent"
            return "sent" if str(row[tracker.STATUS_COL - 1].value or "").strip() == tracker.SUBMITTED else "listed"
    entry = {"company": job.get("company", ""), "title": job.get("title", ""),
             "location": job.get("location", ""), "url": job.get("url", "")}
    if submitted:
        entry.update(status=tracker.SUBMITTED, submitted_on=date.today().isoformat())
    tracker.add_rows([entry])
    return "sent" if submitted else "listed"


def applications() -> list[dict]:
    if not tracker.TRACKER_PATH.exists():
        return []
    _, sheet = tracker.load()

    def text(v):
        if isinstance(v, str) and re.fullmatch(r"=\$?([A-H])\$?(\d+)", v.strip()):
            v = sheet[v.strip().lstrip("=").replace("$", "")].value  # e.g. "=A2" in older rows
        return v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v or "").strip()

    rows = []
    for row in sheet.iter_rows(min_row=2, max_col=8):
        values = [c.value for c in row] + [None] * (8 - len(row))
        if not any(values):
            continue
        cell = row[tracker.URL_COL - 1]
        url = (cell.hyperlink.target if cell.hyperlink else cell.value) or ""
        rows.append({"row": row[0].row, "created": text(values[0]), "company": text(values[1]),
                     "title": text(values[2]), "location": text(values[3]), "url": str(url).strip(),
                     "status": text(values[5]) or tracker.NOT_SUBMITTED, "submitted_on": text(values[6]),
                     "note": text(values[7])})
    return rows


def update_application(body: dict) -> dict:
    """Change one row's status / note. The row must still hold the same company+role
    (you may have sorted or edited the sheet in Excel since the page loaded)."""
    workbook, sheet = tracker.load()
    r = int(body["row"])
    if (_text_key(sheet.cell(r, 2).value), _text_key(sheet.cell(r, 3).value)) != \
            (_text_key(body.get("company")), _text_key(body.get("title"))):
        raise ValueError("הקובץ השתנה מאז שהדף נטען. רענן את הלשונית ונסה שוב.")
    if "status" in body:
        sheet.cell(r, tracker.STATUS_COL).value = body["status"]
        if body["status"] == tracker.SUBMITTED and not sheet.cell(r, 7).value:
            sheet.cell(r, 7).value = date.today().isoformat()
    if "note" in body:
        sheet.cell(r, 8).value = body["note"]
    tracker.save(workbook)
    v = sheet.cell(r, 7).value
    return {"submitted_on": v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v or "")}


# ---------------------------------------------------------------- scan

class Scan:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.started = 0.0
        self.finished_at = ""
        self.rc: int | None = None
        self.log: deque[str] = deque(maxlen=300)

    def expected(self) -> float:
        try:
            return float(LAST_DURATION.read_text())
        except (OSError, ValueError):
            return 570.0

    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.rc, self.started = True, None, time.time()
            self.log.clear()
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        try:
            # Under pythonw.exe the scan runs with python.exe, without a console window.
            exe = Path(sys.executable)
            if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
                exe = exe.parent / "python.exe"
            proc = subprocess.Popen([str(exe), "-u", str(SCAN_SCRIPT)], cwd=str(DATA_ROOT), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip()
                self.log.append(line)
                try:
                    print(line, flush=True)
                except UnicodeEncodeError:
                    pass
            rc = proc.wait()
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR: {exc}")
            rc = 1
        with self.lock:
            self.running, self.rc = False, rc
            self.finished_at = datetime.now().strftime("%H:%M")
        if rc == 0:
            RAW.clear()
            start_enrich()  # score the new jobs against the CV in the background

    def status(self) -> dict:
        return {
            "running": self.running,
            "elapsed": round(time.time() - self.started) if self.started else 0,
            "expected": round(self.expected()),
            "rc": self.rc,
            "finished_at": self.finished_at,
            "log": list(self.log)[-80:],
        }


SCAN = Scan()
LAST_PING = [time.time()]


# ---------------------------------------------------------------- actions

def open_action(what: str) -> str:
    if what == "tracker":
        if not tracker.TRACKER_PATH.exists():
            tracker.save(tracker.load()[0])
        os.startfile(str(tracker.TRACKER_PATH))
        return "applications.xlsx נפתח"
    if what == "manual":
        MANUAL_FILE.touch(exist_ok=True)
        subprocess.Popen(["notepad", str(MANUAL_FILE)])
        return f"הדבק את תיאור המשרה ושמור. ההתאמה: find_jobs.py --manual"
    raise ValueError(what)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # keep the console for scan output
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        LAST_PING[0] = time.time()
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/jobs":
            try:
                self._json(load_jobs())
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)
        elif path == "/api/job":
            try:
                self._json(job_details(int(self.path.split("id=")[-1])))
            except (ValueError, IndexError):
                self._json({"error": "רענן את הדף"}, 404)
        elif path == "/api/applications":
            try:
                self._json({"rows": applications()})
            except Exception as exc:  # noqa: BLE001
                self._json({"error": str(exc)}, 500)
        elif path == "/api/career-sites":
            self._json({"sites": career_sites()})
        elif path == "/api/post-searches":
            self._json({"searches": post_searches()})
        elif path == "/api/skills":
            self._json(dict(ENRICH, cv=sorted(skill_match.cv_skills())))
        elif path == "/api/status":
            self._json(SCAN.status())
        elif path == "/api/ping":
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        LAST_PING[0] = time.time()
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        path = self.path.split("?")[0]
        try:
            if path == "/api/scan":
                self._json({"started": SCAN.start()})
            elif path == "/api/track":
                self._json({"state": track(body.get("job") or {}, bool(body.get("submitted")))})
            elif path == "/api/publish":
                import publish_github
                self._json({"message": publish_github.publish()})
            elif path == "/api/cover-letter":
                i = int(body.get("id", -1))
                details = job_details(i, with_skills=False)
                if not details.get("description"):
                    raise ValueError("אין תיאור משרה, אז אי אפשר לכתוב מכתב מותאם. פתח את המשרה והדבק את התיאור בלשונית הפוסטים.")
                import cover_letter
                self._json(cover_letter.generate(RAW[i], details["description"]))
            elif path == "/api/application":
                self._json(update_application(body))
            elif path == "/api/post/parse":
                self._json(parse_post(body.get("url", ""), body.get("text", "")))
            elif path == "/api/post/add":
                add_post(body)
                result = {"ok": True}
                if body.get("track"):
                    result["state"] = track(body, False)
                self._json(result)
            elif path == "/api/open":
                self._json({"message": open_action(body.get("what", ""))})
            else:
                self._send(404, b"not found", "text/plain")
        except SystemExit as exc:  # tracker.save() raises this when Excel holds the file
            self._json({"error": "applications.xlsx פתוח באקסל — סגור אותו ונסה שוב." if "open in Excel" in str(exc) else str(exc)}, 409)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)


class ExclusiveServer(ThreadingHTTPServer):
    """HTTPServer sets SO_REUSEADDR, which on Windows lets a second program bind a port that is
    already in use — two servers on one port, either may answer. Bind exclusively instead, so a
    taken port fails and the next one in PORTS is tried."""

    allow_reuse_address = False

    def server_bind(self):
        import socket

        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def ours(port: int) -> bool:
    """True when this job-search server (not some other program) answers on the port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/ping", timeout=2) as resp:
            return json.loads(resp.read() or b"{}").get("ok") is True
    except (OSError, ValueError):
        return False


def main() -> int:
    if sys.stdout is None:  # pythonw.exe: no console, so keep a log file for errors
        log = open(ENGINE_DIR / "web_app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    global PORT
    want_scan = "--scan" in sys.argv
    pinned = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else None

    for port in ([pinned] if pinned else PORTS):
        if ours(port):
            url = f"http://{HOST}:{port}/"
            if want_scan:
                urllib.request.urlopen(urllib.request.Request(url + "api/scan", data=b"{}", method="POST"), timeout=5)
            if "--no-browser" not in sys.argv:
                webbrowser.open_new_tab(url)
            print("The job-search page is already running — opened it in the browser.")
            return 0

    server = None
    if pinned:  # a self-restart: the old process may still hold its port for a moment
        for _ in range(40):
            try:
                server = ExclusiveServer((HOST, pinned), Handler)
                break
            except OSError:
                time.sleep(0.25)
    else:
        for port in PORTS:
            try:
                server = ExclusiveServer((HOST, port), Handler)
                break
            except OSError:
                print(f"port {port} is taken by another program, trying the next one", flush=True)
    if server is None:
        raise SystemExit(f"no free port among {PORTS}")
    PORT = server.server_address[1]
    url = f"http://{HOST}:{PORT}/"
    if want_scan:
        SCAN.start()
    else:
        start_enrich()
    if "--no-browser" not in sys.argv:
        webbrowser.open_new_tab(url)
    print("=" * 60)
    print(f"  Job search is open in your browser: {url}")
    print("  Keep this window open. It closes by itself a few minutes")
    print("  after you close the browser tab.")
    print("=" * 60, flush=True)

    # A server left running keeps serving old code while the page (read from
    # disk) is new — endpoints go missing. So when any engine .py changes, the
    # server restarts itself (no new tab, no scan) as soon as no scan is running.
    def code_mtime() -> float:
        return max(f.stat().st_mtime for f in ENGINE_DIR.glob("*.py"))

    started_code = code_mtime()
    restart = [False]

    def watchdog() -> None:
        while True:
            time.sleep(5)
            if SCAN.running:
                continue
            if time.time() - LAST_PING[0] > IDLE_EXIT_SECONDS:
                server.shutdown()
                return
            if code_mtime() > started_code:
                restart[0] = True
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    if restart[0]:
        print("Engine code changed — restarting the server.", flush=True)
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--no-browser", "--port", str(PORT)], cwd=str(DATA_ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
