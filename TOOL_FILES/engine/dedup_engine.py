from difflib import SequenceMatcher
from typing import Optional

class DedupEngine:
    def __init__(self):
        self.jobs = {}
        self.urls_seen = set()
        self.hashes_seen = set()

    def add_job(self, job: dict, fuzzy_threshold: float = 0.90) -> bool:
        """
        Add job if not a duplicate. Returns True if added, False if duplicate.

        Dedup strategy:
        1. Check by URL
        2. Check by content hash (id)
        3. Check by fuzzy match (90%+ similarity)
        """
        url = job.get("url", "").strip()
        job_id = job.get("id", "")

        # Level 1: URL dedup
        if url and url in self.urls_seen:
            # Find existing job with this URL and merge
            for existing_id, existing_job in self.jobs.items():
                if existing_job.get("url") == url:
                    self._merge_urls(existing_id, url)
                    break
            return False

        # Level 2: Content hash dedup
        if job_id and job_id in self.hashes_seen:
            if job_id in self.jobs:
                self._merge_urls(job_id, url)
            return False

        # Level 3: Fuzzy match dedup
        similar = self.find_duplicates(job, threshold=fuzzy_threshold)
        if similar:
            # Merge into first similar job found
            self._merge_urls(similar[0].get("id"), url)
            return False

        # Not a duplicate, add it
        self.jobs[job_id] = job
        if url:
            self.urls_seen.add(url)
        if job_id:
            self.hashes_seen.add(job_id)

        return True

    def find_duplicates(self, job: dict, threshold: float = 0.90) -> list[dict]:
        """Find jobs similar to this one via fuzzy string matching."""
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")

        search_str = f"{title} {company} {location}".lower()
        duplicates = []

        for existing_id, existing_job in self.jobs.items():
            existing_title = existing_job.get("title", "")
            existing_company = existing_job.get("company", "")
            existing_location = existing_job.get("location", "")

            existing_str = f"{existing_title} {existing_company} {existing_location}".lower()

            similarity = SequenceMatcher(None, search_str, existing_str).ratio()

            if similarity >= threshold:
                duplicates.append(existing_job)

        return duplicates

    def get_unique_jobs(self) -> list[dict]:
        """Return all unique jobs."""
        return list(self.jobs.values())

    def _merge_urls(self, job_id: str, url: str):
        """Merge a duplicate job's URL into existing job's source_urls."""
        if job_id in self.jobs and url:
            if "source_urls" not in self.jobs[job_id]:
                self.jobs[job_id]["source_urls"] = []
            if url not in self.jobs[job_id]["source_urls"]:
                self.jobs[job_id]["source_urls"].append(url)
