import requests
from engine.job_normalizer import normalize_job


class GitHubJobsAdapter:
    """Adapter for GitHub Jobs (public JSON API)."""

    def __init__(self, keywords_en: list[str], timeout_sec: int = 30):
        self.keywords_en = keywords_en
        self.timeout_sec = timeout_sec
        self.source = "github_jobs"

    def scan(self) -> list[dict]:
        """Fetch jobs from GitHub Jobs API."""
        jobs = []
        try:
            url = "https://jobs.github.com/positions.json"
            params = {"location": "Israel"}
            response = requests.get(url, params=params, timeout=self.timeout_sec)
            response.raise_for_status()
            data = response.json()

            for job_data in data:
                if any(kw.lower() in job_data.get("title", "").lower() for kw in self.keywords_en):
                    job = self._parse_github_job(job_data)
                    if job:
                        jobs.append(job)
        except Exception as e:
            print(f"GitHubJobsAdapter: Error fetching jobs: {str(e)}")
        return jobs

    def _parse_github_job(self, github_job: dict) -> dict | None:
        """Convert GitHub job to normalized format."""
        try:
            raw_job = {
                "title": github_job.get("title", ""),
                "company": github_job.get("company", ""),
                "location": github_job.get("location", "Israel"),
                "description": github_job.get("description", ""),
                "url": github_job.get("url", ""),
                "posted_date": github_job.get("created_at", ""),
                "source": self.source
            }
            return normalize_job(raw_job, source=self.source, language="en")
        except Exception:
            return None
