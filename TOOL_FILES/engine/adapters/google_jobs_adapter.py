import requests
from engine.job_normalizer import normalize_job


class GoogleJobsAdapter:
    """Adapter for Google Jobs API (free, structured data)."""

    def __init__(self, keywords_en: list[str], keywords_he: list[str], location: str, timeout_sec: int = 30):
        self.keywords_en = keywords_en
        self.keywords_he = keywords_he
        self.location = location
        self.timeout_sec = timeout_sec
        self.source = "google_jobs"

    def scan(self) -> list[dict]:
        """Fetch jobs from Google Jobs API."""
        jobs = []
        jobs.extend(self._search_keywords(self.keywords_en, language="en"))
        jobs.extend(self._search_keywords(self.keywords_he, language="he"))
        return jobs

    def _search_keywords(self, keywords: list[str], language: str) -> list[dict]:
        """Search jobs for a set of keywords."""
        jobs = []
        for keyword in keywords:
            try:
                # Google Jobs doesn't expose a free public API
                # This adapter would use SerpAPI or similar in production
                # For MVP, return empty to allow pipeline testing
                pass
            except Exception as e:
                print(f"GoogleJobsAdapter: Error searching '{keyword}': {str(e)}")
        return jobs
