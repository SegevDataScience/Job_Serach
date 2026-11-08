#!/usr/bin/env python3
"""
skill_match.py — how well a posting's required skills match the master CV.

The CV side is not hard-coded: the master CV (RESUME_INPUT in .env) is read
and every skill in SKILLS that appears in it counts as "have". A posting's
text is scanned with the same patterns; score = weighted share of the skills
the posting asks for that the CV shows. So updating the CV updates the scoring.

This complements personalized_ranking.py, which judges the title only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
CV_CACHE = ENGINE_DIR / ".cv_skills.json"

# (label, weight, patterns). Patterns are case-insensitive regexes; English ones
# get word boundaries. Weight 2 = core of the role, 1 = everything else.
SKILLS: list[tuple[str, int, list[str]]] = [
    # core languages / querying
    ("SQL", 2, [r"sql", r"t-sql", r"pl/sql"]),
    ("Python", 2, [r"python"]),
    ("R", 1, [r"r(?= programming| language|,? python|/python| or python| and python)", r"(?<=python,) r\b", r"(?<=python and) r\b", r"(?<=python or) r\b", r"(?<=python/)r\b", r"(?<=[,(] )r(?=[,)])"]),
    ("Pandas / Polars", 1, [r"pandas", r"polars"]),
    ("Scikit-learn", 1, [r"scikit-learn", r"sklearn"]),
    # data platforms
    ("Vertica", 1, [r"vertica"]),
    ("GCP / BigQuery", 1, [r"gcp", r"google cloud", r"bigquery", r"big query"]),
    ("AWS", 1, [r"aws", r"amazon web services", r"redshift", r"athena", r"s3"]),
    ("Oracle", 1, [r"oracle"]),
    ("Snowflake", 1, [r"snowflake"]),
    ("Databricks", 1, [r"databricks"]),
    ("Spark", 1, [r"spark", r"pyspark"]),
    ("Airflow", 1, [r"airflow"]),
    ("dbt", 1, [r"dbt"]),
    ("Kafka / streaming", 1, [r"kafka", r"kinesis", r"flink"]),
    ("Docker / Kubernetes", 1, [r"docker", r"kubernetes", r"k8s"]),
    ("Java / Scala", 1, [r"java", r"scala"]),
    # BI
    ("Tableau", 1, [r"tableau"]),
    ("Power BI", 1, [r"power ?bi"]),
    ("Looker", 1, [r"looker"]),
    ("Excel", 1, [r"excel", r"אקסל"]),
    ("Dashboards / BI", 1, [r"dashboards?", r"business intelligence", r"\bbi\b", r"דשבורד", r"בינה עסקית"]),
    # modelling / engineering
    ("Data modeling", 2, [r"data model(?:l)?ing", r"dimensional", r"star schema", r"data warehouse", r"dwh", r"מידול נתונים"]),
    ("ETL / pipelines", 1, [r"etl", r"elt", r"data pipelines?", r"pipelines?"]),
    ("Data quality", 1, [r"data quality", r"data profiling", r"data integrity", r"איכות נתונים"]),
    ("Query optimization", 1, [r"query optimi[sz]ation", r"query tuning", r"performance tuning"]),
    ("REST API", 1, [r"rest api", r"\bapis?\b"]),
    # analytics / science
    ("Statistics", 1, [r"statistic(?:s|al)", r"סטטיסטיק"]),
    ("Machine learning", 2, [r"machine learning", r"\bml\b", r"predictive model", r"למידת מכונה"]),
    ("Anomaly detection", 1, [r"anomaly detection", r"anomal(?:y|ies)", r"outlier"]),
    ("Time series", 1, [r"time[- ]series"]),
    ("Network analysis (SNA)", 1, [r"social network analysis", r"\bsna\b", r"graph analytics", r"network analysis"]),
    ("A/B testing", 1, [r"a/b test", r"ab test", r"experimentation"]),
    ("Deep learning", 1, [r"deep learning", r"pytorch", r"tensorflow", r"neural network"]),
    ("NLP / LLM", 1, [r"\bnlp\b", r"\bllms?\b", r"generative ai", r"genai", r"large language model"]),
    # product / domain
    ("KPIs / metrics", 1, [r"kpis?", r"metrics"]),
    ("Data products / B2B", 1, [r"data products?", r"\bb2b\b", r"\bdaas\b"]),
    ("Fintech / payments", 1, [r"fintech", r"payments?", r"transactions?", r"credit card", r"תשלומים"]),
    ("Fraud / risk / compliance", 1, [r"fraud", r"\baml\b", r"anti[- ]money", r"surveillance", r"compliance", r"regulat", r"risk"]),
    ("Capital markets", 1, [r"capital markets?", r"trading", r"securities", r"שוק ההון"]),
    # people
    ("Stakeholder management", 1, [r"stakeholders?", r"cross[- ]functional"]),
    ("Leadership / mentoring", 1, [r"mentor", r"team lead", r"leadership", r"lead(?:ing)? a team", r"ניהול צוות"]),
]

_COMPILED = [
    (label, weight, [re.compile(p if (p.startswith(r"\b") or p.startswith("(?") or not p[:1].isascii())
                                else rf"(?<![a-z0-9]){p}(?![a-z0-9])", re.I) for p in patterns])
    for label, weight, patterns in SKILLS
]
# Only "N+ years of experience"-style phrasing ("detects risk 10 years in advance" is not a requirement).
_YEARS = [re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs)\s+(?:of\s+)?(?:[\w/&-]+\s+){0,4}?experience", re.I),
          re.compile(r"(?:minimum|at least)\s+(?:of\s+)?(\d{1,2})\s*\+?\s*years?", re.I),
          re.compile(r"(\d{1,2})\s*\+?\s*שנות\s+(?:ניסיון|נסיון)"),
          re.compile(r"(?:ניסיון|נסיון)\s+(?:של\s+)?(?:לפחות\s+)?(\d{1,2})\s*\+?\s*(?:שנים|שנות)")]


def found_skills(text: str) -> set[str]:
    text = text or ""
    return {label for label, _, patterns in _COMPILED if any(p.search(text) for p in patterns)}


def cv_text() -> str:
    import master_cv

    path = master_cv.resolve_master_path(master_cv.configured_master_path())
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        return " ".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if path.suffix.lower() == ".docx":
        import docx

        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return path.read_text(encoding="utf-8", errors="replace")


def cv_skills() -> set[str]:
    """Skills the master CV shows. Cached; re-read when the CV file changes."""
    import master_cv

    try:
        path = master_cv.resolve_master_path(master_cv.configured_master_path())
        import hashlib

        rules = hashlib.md5(json.dumps(SKILLS).encode()).hexdigest()[:10]  # new patterns -> re-read the CV
        stamp = f"{path}|{path.stat().st_mtime}|{rules}"
    except SystemExit:
        stamp = ""
    try:
        cached = json.loads(CV_CACHE.read_text(encoding="utf-8"))
        if stamp and cached.get("stamp") == stamp:
            return set(cached["skills"])
    except (OSError, ValueError, KeyError):
        pass
    skills = found_skills(cv_text())
    try:
        CV_CACHE.write_text(json.dumps({"stamp": stamp, "skills": sorted(skills)}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return skills


def match(text: str, have: set[str] | None = None) -> dict:
    """{"score": 0-100 or None, "have": [...], "missing": [...], "years": N or None}."""
    have = cv_skills() if have is None else have
    wanted = found_skills(text)
    weight = {label: w for label, w, _ in SKILLS}
    years = [int(n) for rx in _YEARS for n in rx.findall(text or "") if 1 <= int(n) <= 15]
    if not wanted:
        return {"score": None, "have": [], "missing": [], "years": max(years) if years else None}
    got = sorted(wanted & have, key=lambda s: -weight[s])
    missing = sorted(wanted - have, key=lambda s: -weight[s])
    score = 100 * sum(weight[s] for s in got) / sum(weight[s] for s in wanted)
    return {"score": round(score), "have": got, "missing": missing, "years": max(years) if years else None}


def overall(title_score: float, skill_score: int | None) -> int:
    """One number for sorting: title fit and skill fit, half and half.
    Title scores top out around 85, so they are stretched to 0-100 first."""
    title = min(100.0, title_score * 100 / 85)
    if skill_score is None:
        return round(title)
    return round(0.5 * title + 0.5 * skill_score)


def level(score: int) -> str:
    return "מצוינת" if score >= 75 else "טובה מאוד" if score >= 65 else "טובה" if score >= 50 else "חלקית"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print("From your CV:", ", ".join(sorted(cv_skills())))
