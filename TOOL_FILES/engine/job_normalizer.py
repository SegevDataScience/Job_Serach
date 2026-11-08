import hashlib
from datetime import datetime
import re

def normalize_job(raw_job: dict, source: str, language: str = "en") -> dict:
    """
    Normalize a job from any source to standard schema.

    Args:
        raw_job: Raw job data from adapter
        source: Source name (linkedin_posts, google_jobs, drushim, etc.)
        language: Language code (en, he, mixed)

    Returns:
        Normalized job dict with standard fields
    """
    title = raw_job.get("title", "").strip()
    company = raw_job.get("company", "").strip()
    location = raw_job.get("location", "Unknown").strip() if raw_job.get("location") else "Unknown"
    description = raw_job.get("description", "").strip()
    url = raw_job.get("url", "").strip()
    salary = raw_job.get("salary", "").strip()
    posted_date = raw_job.get("posted_date", "").strip()

    # Auto-detect language if not specified
    if language == "auto":
        language = _detect_language(title + " " + description)

    # Generate content hash for deduplication
    content_hash = _generate_content_hash(title, company, location, description[:500])

    normalized = {
        "id": content_hash,
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "url": url,
        "salary": salary if salary else None,
        "source": source,
        "posted_date": posted_date,
        "language": language,
        "relevance_score": 50,
        "applied": False,
        "source_urls": [url] if url else []
    }

    return normalized

def _generate_content_hash(title: str, company: str, location: str, description: str) -> str:
    """Generate SHA256 hash from job content for dedup."""
    content = f"{title}|{company}|{location}|{description}".lower()
    return hashlib.sha256(content.encode()).hexdigest()

def _detect_language(text: str) -> str:
    """Detect if text contains Hebrew or English."""
    hebrew_count = len(re.findall(r'[֐-׿]', text))
    english_count = len(re.findall(r'[a-zA-Z]', text))

    if hebrew_count > english_count:
        return "he"
    elif english_count > hebrew_count:
        return "en"
    else:
        return "mixed"

def merge_duplicate_jobs(job1: dict, job2: dict) -> dict:
    """Merge two jobs found on different sources."""
    merged = job1.copy()

    # Preserve both URLs
    urls = set(job1.get("source_urls", [job1.get("url", "")]))
    urls.update(job2.get("source_urls", [job2.get("url", "")]))
    merged["source_urls"] = list(urls)

    # Prefer the one with longer description
    if len(job2.get("description", "")) > len(job1.get("description", "")):
        merged["description"] = job2["description"]

    # Combine sources
    sources = [job1["source"], job2["source"]]
    merged["source"] = " + ".join(sources)

    return merged
