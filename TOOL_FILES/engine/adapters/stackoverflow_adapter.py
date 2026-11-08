import feedparser
from engine.job_normalizer import normalize_job


class StackOverflowAdapter:
    """Adapter for Stack Overflow Jobs RSS feed."""

    def __init__(self, keywords_en: list[str], timeout_sec: int = 30):
        self.keywords_en = keywords_en
        self.timeout_sec = timeout_sec
        self.source = "stackoverflow"

    def scan(self) -> list[dict]:
        """Fetch jobs from Stack Overflow RSS feed."""
        jobs = []
        try:
            rss_url = "https://stackoverflow.com/jobs/feed?location=Israel&days=30"
            feed = feedparser.parse(rss_url)

            for entry in feed.entries:
                title = entry.get("title", "")
                if any(kw.lower() in title.lower() for kw in self.keywords_en):
                    job = self._parse_entry(entry)
                    if job:
                        jobs.append(job)
        except Exception as e:
            print(f"StackOverflowAdapter: Error fetching feed: {str(e)}")
        return jobs

    def _parse_entry(self, entry) -> dict | None:
        """Convert RSS entry to normalized job."""
        try:
            raw_job = {
                "title": entry.get("title", ""),
                "company": entry.get("summary", "").split("<br")[0].strip() if entry.get("summary") else "",
                "location": "Israel",
                "description": entry.get("summary", ""),
                "url": entry.get("link", ""),
                "posted_date": entry.get("published", ""),
                "source": self.source
            }
            return normalize_job(raw_job, source=self.source, language="en")
        except Exception:
            return None
