import requests
from bs4 import BeautifulSoup
import time
from engine.job_normalizer import normalize_job
from engine.cache_manager import CacheManager

class AllJobsAdapter:
    """Adapter for AllJobs.co.il (Israeli job board, Hebrew)."""

    def __init__(self, keywords_he: list[str], cache_manager: CacheManager, timeout_sec: int = 30):
        self.keywords_he = keywords_he
        self.cache_manager = cache_manager
        self.timeout_sec = timeout_sec
        self.source = "alljobs"
        self.request_delay = 3
        self.base_url = "https://www.alljobs.co.il"

    def scan(self) -> list[dict]:
        """Scan AllJobs for jobs."""
        jobs = []
        cached = self.cache_manager.load("alljobs", max_age_hours=12)
        if cached:
            return cached

        for keyword in self.keywords_he:
            try:
                time.sleep(self.request_delay)
                jobs.extend(self._search_keyword(keyword))
            except Exception as e:
                print(f"AllJobsAdapter: Error searching '{keyword}': {str(e)}")

        if jobs:
            self.cache_manager.save("alljobs", jobs, ttl_hours=12)
        return jobs

    def _search_keyword(self, keyword: str) -> list[dict]:
        """Search AllJobs."""
        jobs = []
        try:
            url = f"{self.base_url}/search"
            params = {"q": keyword}
            response = requests.get(url, params=params, timeout=self.timeout_sec)
            response.encoding = 'utf-8'
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            job_elements = soup.find_all('div', class_='job-card')

            for elem in job_elements[:20]:
                job = self._parse_element(elem)
                if job:
                    jobs.append(job)
        except Exception as e:
            print(f"AllJobsAdapter: Error: {str(e)}")
        return jobs

    def _parse_element(self, elem) -> dict | None:
        try:
            title_link = elem.find('a', class_='job-title')
            company = elem.find('span', class_='company')
            location = elem.find('span', class_='location')

            raw_job = {
                "title": title_link.text.strip() if title_link else "",
                "company": company.text.strip() if company else "",
                "location": location.text.strip() if location else "Israel",
                "description": "",
                "url": title_link.get('href') if title_link else "",
                "source": self.source
            }
            return normalize_job(raw_job, source=self.source, language="he")
        except Exception:
            return None
