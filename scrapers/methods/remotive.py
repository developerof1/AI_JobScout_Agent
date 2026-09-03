"""
Remotive API client — fetches remote jobs from remotive.com/api.
Returns all jobs in the configured categories; filtering is handled downstream
by utils/filter_engine.py.
"""

import re
import time
import random
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://remotive.com/api/remote-jobs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_category(category: str) -> list[dict]:
    try:
        resp = requests.get(
            BASE_URL,
            headers=HEADERS,
            params={"category": category},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        print(f"  [remotive] Category '{category}': {len(jobs)} jobs fetched")
        return jobs
    except requests.RequestException as e:
        print(f"  [remotive] Failed to fetch category '{category}': {e}")
        return []


def _to_standard_schema(job: dict) -> dict:
    return {
        "title": job.get("title", ""),
        "company": job.get("company_name", ""),
        "location": job.get("candidate_required_location", ""),
        "description": _strip_html(job.get("description", "")),
        "url": job.get("url", ""),
        "posted_date": job.get("publication_date", datetime.now(timezone.utc).isoformat()),
        "source": "remotive",
    }


def scrape(config: dict) -> list[dict]:
    categories = config.get("categories") or ["product", "project-management"]
    delay = config.get("rate_limit_delay_seconds", 1)
    all_raw = []
    seen_ids = set()

    for i, category in enumerate(categories):
        raw_jobs = _fetch_category(category)
        for job in raw_jobs:
            job_id = job.get("id")
            if job_id and job_id in seen_ids:
                continue
            if job_id:
                seen_ids.add(job_id)
            all_raw.append(_to_standard_schema(job))

        if i < len(categories) - 1:
            time.sleep(delay + random.uniform(0, 0.5))

    print(f"  [remotive] Total unique jobs fetched: {len(all_raw)}")
    return all_raw
