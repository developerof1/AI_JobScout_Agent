"""
Adzuna Jobs API client — fetches US jobs by functional area keyword.
Returns all jobs across configured queries; filtering is handled downstream
by utils/filter_engine.py.

Requires env vars: ADZUNA_APP_ID, ADZUNA_APP_KEY
Register free at developer.adzuna.com

Adding new query areas:
  Edit config/tabs/scouting.json -> sources[adzuna].config.queries
  No changes to this file needed.
"""

import os
import re
import time
import random
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.adzuna.com/v1/api/jobs/us/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _fetch_page(app_id: str, app_key: str, query: str, page: int, results_per_page: int) -> list[dict]:
    try:
        resp = requests.get(
            f"{BASE_URL}/{page}",
            headers=HEADERS,
            params={
                "app_id": app_id,
                "app_key": app_key,
                "what": query,
                "results_per_page": results_per_page,
                "content-type": "application/json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])
    except requests.RequestException as e:
        print(f"  [adzuna] Failed to fetch query='{query}' page={page}: {e}")
        return []


def _to_standard_schema(job: dict) -> dict:
    company = job.get("company") or {}
    location = job.get("location") or {}
    return {
        "title": job.get("title", ""),
        "company": company.get("display_name", ""),
        "location": location.get("display_name", ""),
        "description": _strip_html(job.get("description", "")),
        "url": job.get("redirect_url", ""),
        "posted_date": job.get("created", datetime.now(timezone.utc).isoformat()),
        "source": "adzuna",
    }


def scrape(config: dict) -> list[dict]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("  [adzuna] ADZUNA_APP_ID or ADZUNA_APP_KEY not set — skipping")
        return []

    queries = config.get("queries") or [
        "product manager", "program manager", "chief of staff", "product operations"
    ]
    results_per_page = config.get("results_per_page") or 50
    max_pages = config.get("max_pages") or 1

    delay = config.get("rate_limit_delay_seconds", 1)
    all_raw = []
    seen_ids = set()

    for i, query in enumerate(queries):
        query_count = 0
        for page in range(1, max_pages + 1):
            results = _fetch_page(app_id, app_key, query, page, results_per_page)
            if not results:
                break
            for job in results:
                job_id = job.get("id")
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)
                all_raw.append(_to_standard_schema(job))
                query_count += 1

            if len(results) < results_per_page:
                break  # no more pages

        print(f"  [adzuna] Query '{query}': {query_count} jobs fetched")

        if i < len(queries) - 1:
            time.sleep(delay + random.uniform(0, 0.5))

    print(f"  [adzuna] Total unique jobs fetched: {len(all_raw)}")
    return all_raw
