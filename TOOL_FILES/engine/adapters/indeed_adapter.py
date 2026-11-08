import feedparser
from urllib.parse import quote
from engine.job_normalizer import normalize_job


class IndeedAdapter:
    """Adapter for Indeed job listings via RSS feed."""

    def __init__(self, keywords_en: list[str], keywords_he: list[str], timeout_sec: int = 30):
        self.keywords_en = keywords_en
        self.keywords_he = keywords_he
        self.timeout_sec = timeout_sec
        self.source = "indeed"

    def scan(self) -> list[dict]:
        """Fetch jobs from Indeed RSS feed (Hebrew + English)."""
        jobs = []
        jobs.extend(self._search_feed(self.keywords_he, base_url="https://www.indeed.co.il", language="he"))
        jobs.extend(self._search_feed(self.keywords_en, base_url="https://www.indeed.com", language="en"))
        return jobs

    def _search_feed(self, keywords: list[str], base_url: str, language: str) -> list[dict]:
        """Parse RSS feed for keywords."""
        jobs = []
        for keyword in keywords:
            try:
                encoded_keyword = quote(keyword)
                rss_url = f"{base_url}/jobs?q={encoded_keyword}&l=Israel&format=rss"
                feed = feedparser.parse(rss_url)
                for entry in feed.entries:
                    job = self._parse_rss_entry(entry, language)
                    if job:
                        jobs.append(job)
            except Exception as e:
                print(f"IndeedAdapter: Error parsing RSS for '{keyword}': {str(e)}")
        return jobs

    def _parse_rss_entry(self, entry, language: str) -> dict | None:
        """Convert RSS entry to normalized job."""
        try:
            title = entry.get("title", "")
            link = entry.get("link", "")
            description = entry.get("description", "")
            published = entry.get("published", "")

            company = ""
            location = "Israel"
            if " - " in description:
                parts = description.split(" - ")
                if len(parts) >= 2:
                    company = parts[0].strip()
                    location = parts[1].strip()

            raw_job = {
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": link,
                "posted_date": published,
                "source": self.source
            }
            return normalize_job(raw_job, source=self.source, language=language)
        except Exception:
            return None
