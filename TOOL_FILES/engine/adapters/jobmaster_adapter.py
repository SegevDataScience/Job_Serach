import requests
from bs4 import BeautifulSoup
import time
from engine.job_normalizer import normalize_job
from engine.cache_manager import CacheManager

class JobMasterAdapter:
    """Adapter for JobMaster (Israeli job board, Hebrew)."""

    def __init__(self, keywords_he: list[str], cache_manager: CacheManager, timeout_sec: int = 30):
        self.keywords_he = keywords_he
        self.cache_manager = cache_manager
        self.timeout_sec = timeout_sec
        self.source = "jobmaster"
        self.request_delay = 3
        self.base_url = "https://www.jobmaster.co.il"

    def scan(self) -> list[dict]:
        """Scan JobMaster for jobs."""
        jobs = []
        cached = self.cache_manager.load("jobmaster", max_age_hours=12)
        if cached:
            return cached

        for keyword in self.keywords_he:
            try:
                time.sleep(self.request_delay)
                jobs.extend(self._search_keyword(keyword))
            except Exception as e:
                print(f"JobMasterAdapter: Error: {str(e)}")

        if jobs:
            self.cache_manager.save("jobmaster", jobs, ttl_hours=12)
        return jobs

    def _search_keyword(self, keyword: str) -> list[dict]:
        """Search JobMaster."""
        jobs = []
        try:
            url = f"{self.base_url}/jobs"
            params = {"search": keyword}
            response = requests.get(url, params=params, timeout=self.timeout_sec)
            response.encoding = 'utf-8'
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            job_elements = soup.find_all('div', class_='job-item')

            for elem in job_elements[:20]:
                job = self._parse_element(elem)
                if job:
                    jobs.append(job)
        except Exception as e:
            print(f"JobMasterAdapter: Error: {str(e)}")
        return jobs

    def _parse_element(self, elem) -> dict | None:
        try:
            title_link = elem.find('h3', class_='job-title')
            company = elem.find('span', class_='employer')

            raw_job = {
                "title": title_link.text.strip() if title_link else "",
                "company": company.text.strip() if company else "",
                "location": "Israel",
                "description": "",
                "url": title_link.find('a').get('href') if title_link else "",
                "source": self.source
            }
            return normalize_job(raw_job, source=self.source, language="he")
        except Exception:
            return None
