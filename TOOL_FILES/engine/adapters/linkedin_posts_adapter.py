import requests
import time
from engine.job_normalizer import normalize_job
from engine.cache_manager import CacheManager

class LinkedInPostsAdapter:
    """Adapter for LinkedIn public posts (light scraping, no login required)."""

    def __init__(self, keywords_en: list[str], keywords_he: list[str], cache_manager: CacheManager, timeout_sec: int = 30):
        self.keywords_en = keywords_en
        self.keywords_he = keywords_he
        self.cache_manager = cache_manager
        self.timeout_sec = timeout_sec
        self.source = "linkedin_posts"
        self.request_delay = 2

    def scan(self) -> list[dict]:
        """Scan LinkedIn for public posts mentioning hiring."""
        jobs = []

        # Try cache first
        cached = self.cache_manager.load("linkedin_posts", max_age_hours=6)
        if cached:
            return cached

        # Search keywords
        jobs.extend(self._search_keywords(self.keywords_en, language="en"))
        jobs.extend(self._search_keywords(self.keywords_he, language="he"))

        # Cache results
        if jobs:
            self.cache_manager.save("linkedin_posts", jobs, ttl_hours=6)

        return jobs

    def _search_keywords(self, keywords: list[str], language: str) -> list[dict]:
        """Search LinkedIn for keywords."""
        jobs = []
        for keyword in keywords:
            try:
                time.sleep(self.request_delay)
                # LinkedIn blocks automated scraping; requires official API or browser automation
                # For MVP, return empty to allow pipeline testing
                pass
            except Exception as e:
                print(f"LinkedInPostsAdapter: Error searching '{keyword}': {str(e)}")
        return jobs
