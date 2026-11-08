#!/usr/bin/env python3
"""
personalized_ranking.py — Score jobs based on candidate profile.

Uses candidate_memory.json to create personalized relevance scores that account for:
- Role type alignment (leadership > IC)
- Domain match (fintech/data platforms > security/AI-first)
- Skill requirements (SQL/Python/data modeling > AI frameworks/streaming)
- Seniority level appropriateness
- Company size and growth stage
"""

import json
import re
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENGINE_DIR.parent
CANDIDATE_PROFILE = ENGINE_DIR / "candidate_memory.json"


def load_candidate_profile() -> dict[str, Any]:
    """Load candidate profile and preferences."""
    if CANDIDATE_PROFILE.exists():
        with open(CANDIDATE_PROFILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


# Drushim titles are Hebrew ("אנליסט/ית נתונים בכיר/ה"). Rewriting the common
# terms into English lets the rules below score them like any other posting.
# Order matters: two-word phrases before their single words.
_HEBREW_TERMS = [
    (r"ראש(?:/ת)? צוות", "team lead"),
    (r"ר\"צ", "team lead"),
    (r"אנליסט(?:/ית|ית)? (?:נתונים|דאטה)", "data analyst"),
    (r"מהנדס(?:/ת|ת)? (?:נתונים|דאטה)", "data engineer"),
    (r"מדען(?:/ית|ית)? (?:נתונים|דאטה)", "data scientist"),
    (r"אנליסט(?:/ית|ית)? bi", "data analyst"),
    (r"אנליסט(?:/ית|ית)? עסקי(?:/ת|ת)?", "business analyst"),
    (r"מנהל(?:/ת|ת)?", "manager"),
    (r"בכיר(?:/ה|ה)?", "senior"),
    (r"ג'וניור", "junior"),
    (r"נתונים|דאטה", "data"),
    (r"אנליטיק[הא]", "analytics"),
    (r"אנליסט(?:/ית|ית)?", "analyst"),
]


def _english_title(title: str) -> str:
    for pattern, english in _HEBREW_TERMS:
        title = re.sub(pattern, english, title)
    # Hebrew word order puts "senior" last: "data analyst senior".
    if "senior" in title and "senior data analyst" not in title and "data analyst" in title:
        title = title.replace("senior", "").replace("data analyst", "senior data analyst")
    return title


def score_job_personalized(job: dict[str, Any], candidate: dict[str, Any],
                           reasons: list | None = None) -> float:
    """
    Compute personalized relevance score for a job.

    Candidate profile: Segev Ohana
    - 4+ years Senior Data Analyst (SQL/Python/Tableau/BI)
    - NOT a backend engineer, data engineer, or infrastructure specialist
    - NOT ML/AI researcher (no LLM, transformers, Spark, Kubernetes)
    - PERFECT FIT: Data Analyst, Analytics Engineer, Big Data Analyst
    - STRONG: Data-focused Team Lead, Analytics Manager, Data Product Manager
    - NO: Staff Engineer, ML roles requiring advanced frameworks, pure backend

    Scoring factors (0-100 scale):
    - Role fit: 40 points (must be analyst/analytics/data product focused)
    - Domain fit: 25 points (fintech, analytics, data products)
    - Skill match: 20 points (SQL, Python, Tableau, data modeling)
    - Seniority fit: 15 points (Senior Analyst is perfect, Team Lead is stretch)

    Args:
        job: Job dict with company, title, location, url
        candidate: Candidate profile dict

    Returns:
        Relevance score 0-100
    """
    score = 0.0
    # reasons (optional) collects (section, points) so the UI can explain a score.
    last = [0.0]

    def mark(label: str) -> None:
        if reasons is not None and score != last[0]:
            reasons.append((label, round(score - last[0])))
        last[0] = score

    def stop(label: str, value: float) -> float:
        if reasons is not None:
            reasons.append((label, None))
        return value

    # Extract job information
    title = _english_title((job.get("title", "") or "").lower())
    company = (job.get("company", "") or "").lower()

    # HARD DISQUALIFIERS - return 0 immediately
    disqualifiers = {
        "staff engineer": -999,
        "principal engineer": -999,
        "infrastructure": -999,
        "devops": -999,
        "sre": -999,
        "backend engineer": -999,
        "security engineer": -999,
        "machine learning engineer": -999,
        "ml engineer": -999,
        "transformer": -999,
        "llm": -999,
        "spark": -999,
        "kafka": -999,
        "flink": -999,
    }

    for disq in disqualifiers:
        if disq in title:
            return stop(f"פסילה: {disq}", 0.0)  # Automatic disqualify

    # Staff-level data roles are penalized (too senior)
    if "staff" in title and any(w in title for w in ["data", "analyst", "scientist"]):
        return stop("Staff — בכיר מדי", 15.0)  # Penalize heavily but don't auto-disqualify

    # Penalize "Expert" and similar vague senior titles
    if "expert" in title and "data" not in title.lower():
        return stop("Expert לא-דאטה", 10.0)

    # Extract candidate preferences
    core_skills = set(s.lower() for s in candidate.get("candidate_profile", {}).get("core_skills", []))
    tools_tech = set(s.lower() for s in candidate.get("candidate_profile", {}).get("tools_and_tech", []))
    domains = set(s.lower() for s in candidate.get("candidate_profile", {}).get("domains", []))

    # === ROLE TYPE FIT (40 points max) ===
    # PERFECT: Data/Analytics Analyst (Senior preferred, any level OK)
    # STRONG: Analytics Engineer, Big Data Analyst, Data Scientist (no ML frameworks required)
    # STRETCH: Data-specific Team Lead/Manager, Data Product Manager
    # AVOID: Staff/Principal/Director (unless data-specific), anything generic (backend, infrastructure)

    # Perfect fit roles (40 points)
    if "senior data analyst" in title or "senior analytics analyst" in title:
        score += 40  # PERFECT: Exactly the current level
    elif "data analyst" in title or "analytics analyst" in title:
        score += 38  # Excellent: Core role, can grow into it
    elif "analytics engineer" in title or "analytics engineering" in title:
        score += 39  # Excellent: Natural next step after Senior Analyst
    elif "big data analyst" in title:
        score += 38  # Excellent: SQL/Python/BI focus at scale

    # Strong fit roles (30-35 points)
    elif "data scientist" in title:
        # But only if it's NOT requiring ML frameworks
        if any(fw in title.lower() for fw in ["transformer", "llm", "deep learning", "pytorch", "tensorflow", "ml engineer"]):
            score += 0  # ML heavy role, minimal points
        else:
            score += 32  # Good: Data Science with analytics focus
    elif "data product" in title or "product analyst" in title:
        score += 35  # Strong: Data product is great fit
    elif "business analyst" in title or "business data analyst" in title:
        score += 33  # Good: Analytics-focused business role

    # Stretch but acceptable (20-28 points)
    elif "team lead" in title and ("data" in title.lower() or "analytics" in title.lower()):
        score += 28  # Stretch: Team lead is growth opportunity
    elif "manager" in title and ("data" in title.lower() or "analytics" in title.lower()):
        score += 26  # Stretch: Analytics manager role
    elif "director" in title and "data" in title.lower():
        score += 18  # Stretch: Data-focused director might be IC-oriented

    # Disqualified (but kept here for clarity, already caught by disqualifiers)
    else:
        score += 5  # Generic role, minimal points

    mark("התאמת תפקיד")

    # === DOMAIN FIT (25 points) ===
    # Candidate is fintech/analytics/data-first, NOT security/backend/infrastructure
    excellent_domains = {"fintech", "data", "analytics", "payments", "financial", "marketplace", "product"}
    good_domains = {"b2b", "b2b saas", "saas"}
    avoid_domains = {"security", "cybersecurity", "devops", "infrastructure", "sre", "edge", "network", "threat", "backend infrastructure"}

    # Score excellent domains
    for domain in excellent_domains:
        if domain in title or domain in company:
            score += 12
            break  # Only count once

    # Score good but secondary domains
    if not any(d in title or d in company for d in excellent_domains):
        for domain in good_domains:
            if domain in title or domain in company:
                score += 6
                break

    # Hard penalty for avoid domains
    for domain in avoid_domains:
        if domain in title or domain in company:
            score -= 45  # Hard penalty — not a good fit
            mark(f"תחום לא מתאים: {domain}")
            return max(0, score)  # Short-circuit

    mark("תחום")

    # === SKILL MATCH (20 points) ===
    # Candidate: SQL+Python+Tableau — excellent. Spark/Hadoop/Kubernetes/LLM — bad fit
    excellent_skills = {"sql", "python", "tableau", "analytics", "data modeling", "warehouse"}
    good_skills = {"data engineering", "data pipeline", "etl", "elt", "aws", "reporting", "dashboard", "kpi"}
    bad_skills = {"spark", "hadoop", "pyspark", "kubernetes", "flink", "kafka", "jvm", "scala", "java", "llm", "transformer", "gpt", "hugging face", "threat", "security engineer", "c++"}

    matched_excellent = sum(1 for skill in excellent_skills if skill in title)
    matched_good = sum(1 for skill in good_skills if skill in title)
    matched_bad = sum(1 for skill in bad_skills if skill in title)

    # Excellent skills are heavily weighted
    if matched_excellent >= 2:
        score += 18
    elif matched_excellent >= 1:
        score += 12

    # Good skills add on top
    if matched_good >= 2:
        score += 8
    elif matched_good >= 1:
        score += 4

    # Bad skills = hard penalty (missing required skills)
    if matched_bad >= 2:
        score -= 50  # Multiple hard-miss skills — skip entirely
        mark("כישורים שחסרים לך")
        return max(0, score)
    elif matched_bad >= 1:
        score -= 25  # One hard-miss skill — steep penalty but not automatic disqualify

    mark("כישורים בכותרת")

    # === SENIORITY FIT (15 points max) ===
    # Candidate: 4+ years = perfect for Senior Analyst, can stretch to Team Lead
    if "senior" in title and not "director" in title and not "principal" in title and not "staff" in title:
        score += 15  # PERFECT: Senior role matches exactly
    elif "lead" in title:
        if "data" in title.lower() or "analytics" in title.lower():
            score += 12  # STRETCH: Team lead is a growth opportunity
        else:
            score -= 10  # NO: Non-data lead doesn't fit
    elif "manager" in title:
        if "data" in title.lower() or "analytics" in title.lower():
            score += 11  # STRETCH: Analytics manager
        else:
            score -= 10  # NO: Non-data manager doesn't fit
    elif "junior" in title or "associate" in title or "entry" in title:
        score -= 20  # HARD NO: Overqualified
    elif "director" in title or "principal" in title or "vp" in title or "expert" in title:
        score -= 25  # HARD NO: Too senior
    elif "expert" in title or "specialist" in title:
        score -= 15  # NO: Vague senior title without analytics focus

    mark("בכירות")

    # === COMPANY REPUTATION BOOST ===
    great_companies = {"taboola", "similarweb", "jfrog", "forter", "riskified", "payoneer", "cyera"}
    if any(co in company for co in great_companies):
        score += 5

    mark("חברה מועדפת")

    # === LOCATION PREFERENCE ===
    # Only score jobs in Israel (already filtered by config, but check anyway)
    location = (job.get("location", "") or "").lower()
    israel_locations = {"tel aviv", "tlv", "ramat gan", "herzliya", "israel", "petah tikva", "givatayim", "netanya"}
    if not any(loc in location for loc in israel_locations):
        score -= 20
    mark("מיקום")

    return max(0, min(100, score))  # Clamp to 0-100


def rank_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Rank jobs by personalized relevance score.

    Args:
        jobs: List of job dicts

    Returns:
        Jobs sorted by relevance_score (descending), with score added to each
    """
    candidate = load_candidate_profile()

    # Add personalized score to each job
    for job in jobs:
        job["personalized_score"] = score_job_personalized(job, candidate)

    # Sort by personalized score, then by company name
    return sorted(jobs, key=lambda j: (-j["personalized_score"], j.get("company", "")))


def explain(job: dict[str, Any]) -> list:
    """[(section, points | None)] behind a job's score; None marks a hard stop."""
    reasons: list = []
    score_job_personalized(job, load_candidate_profile(), reasons)
    return reasons


def get_top_jobs(jobs: list[dict[str, Any]], n: int = 15) -> list[dict[str, Any]]:
    """Get top N jobs ranked by personalized relevance."""
    ranked = rank_jobs(jobs)
    return ranked[:n]


def print_ranked_jobs(jobs: list[dict[str, Any]], n: int = 15) -> None:
    """Print ranked jobs in table format."""
    ranked = rank_jobs(jobs)
    print("\n" + "=" * 110)
    print(f"TOP {n} PERSONALIZED JOBS (ranked by relevance to your profile)")
    print("=" * 110)
    print(f"{'#':<3} {'Score':<8} {'Fit':<14} {'Company':<20} {'Role':<55}")
    print("-" * 110)

    for idx, job in enumerate(ranked[:n], 1):
        score = job.get("personalized_score", 0)
        company = (job.get("company", "") or "Unknown")[:19]
        title = (job.get("title", "") or "Unknown")[:53]
        fit_level = _score_to_fit(score)

        print(f"{idx:<3} {score:>6.1f}  {fit_level:<14} {company:<20} {title:<55}")

    print("=" * 110 + "\n")


def _score_to_fit(score: float) -> str:
    """Convert numeric score to fit level description."""
    if score >= 85:
        return "PERFECT"
    elif score >= 75:
        return "EXCELLENT"
    elif score >= 60:
        return "VERY GOOD"
    elif score >= 45:
        return "GOOD"
    elif score >= 30:
        return "MODERATE"
    else:
        return "WEAK"


if __name__ == "__main__":
    # Test: load jobs and rank them
    jobs_file = PROJECT_ROOT / "jobs_found.json"
    if jobs_file.exists():
        with open(jobs_file, 'r', encoding='utf-8') as f:
            jobs = json.load(f)

        print(f"Ranking {len(jobs)} jobs...")
        print_ranked_jobs(jobs, n=15)
    else:
        print(f"Jobs file not found: {jobs_file}")
