#!/usr/bin/env python3
"""
open_career_sites.py — START.bat [5]: open, in the browser, the career pages of
the companies the scan cannot read (their own career systems or bot walls).

The list is `career_sites` in job_search_config.json.
"""

import json
import time
import webbrowser
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "job_search_config.json"


def main() -> None:
    sites = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("career_sites", [])
    if not sites:
        print("No career_sites in job_search_config.json.")
        return
    print(f"Opening {len(sites)} career pages in your browser...")
    for site in sites:
        print(f"  {site['name']}")
        webbrowser.open_new_tab(site["url"])
        time.sleep(0.4)  # a burst of 36 opens at once can drop tabs
    print("\nDone. Search each page for data / BI / analytics roles; add a find with")
    print("the tracker (applications.xlsx) or paste it into job_description.txt to tailor.")


if __name__ == "__main__":
    main()
