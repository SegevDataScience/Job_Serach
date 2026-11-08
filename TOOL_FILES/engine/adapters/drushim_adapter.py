import requests
from bs4 import BeautifulSoup
import time
from engine.job_normalizer import normalize_job
from engine.cache_manager import CacheManager

class DrushimAdapter:
    """Adapter for Drushim.co.il (Israeli job board, Hebrew)."""

    def __init__(self, keywords_he: list[str], cache_manager: CacheManager, timeout_sec: int = 30):
        self.keywords_he = keywords_he
        self.cache_manager = cache_manager
        self.timeout_sec = timeout_sec
        self.source = "drushim"
        self.request_delay = 3
        self.base_url = "https://www.drushim.co.il"

    def scan(self) -> list[dict]:
        """Scan Drushim for jobs."""
        jobs = []

        # Try cache first
        cached = self.cache_manager.load("drushim", max_age_hours=12)
        if cached:
            return cached

        for keyword in self.keywords_he:
            try:
                time.sleep(self.request_delay)
                jobs.extend(self._search_keyword(keyword))
            except Exception as e:
                print(f"DrushimAdapter: Error searching '{keyword}': {str(e)}")

        # Cache results
        if jobs:
            self.cache_manager.save("drushim", jobs, ttl_hours=12)

        return jobs

    def _search_keyword(self, keyword: str) -> list[dict]:
        """Search for keyword on Drushim."""
        jobs = []
        try:
            search_url = f"{self.base_url}/jobs/search"
            params = {"q": keyword, "l": "כל הארץ"}

            response = requests.get(search_url, params=params, timeout=self.timeout_sec)
            response.encoding = 'utf-8'
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')
            job_elements = soup.find_all('div', class_='job-listing')

            for elem in job_elements[:20]:
                job = self._parse_job_element(elem)
                if job:
                    jobs.append(job)
        except Exception as e:
            print(f"DrushimAdapter: Error scraping: {str(e)}")

        return jobs

    def _parse_job_element(self, elem) -> dict | None:
        """Parse HTML element to job object."""
        try:
            title_elem = elem.find('a', class_='job-title')
            company_elem = elem.find('span', class_='company-name')
            location_elem = elem.find('span', class_='location')
            description_elem = elem.find('div', class_='job-description')

            title = title_elem.text.strip() if title_elem else ""
            company = company_elem.text.strip() if company_elem else ""
            location = location_elem.text.strip() if location_elem else "Israel"
            description = description_elem.text.strip() if description_elem else ""
            url = title_elem.get('href') if title_elem else ""

            if url and not url.startswith('http'):
                url = self.base_url + url

            raw_job = {
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": url,
                "source": self.source
            }

            return normalize_job(raw_job, source=self.source, language="he")
        except Exception:
            return None
