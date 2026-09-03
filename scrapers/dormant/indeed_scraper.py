"""
Indeed job board scraper using requests + BeautifulSoup.
Uses Indeed's public job search with remote filter.
"""

import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent

BASE_URL = "https://www.indeed.com/jobs"

SEARCH_QUERIES = [
    "VP Product Operations remote",
    "Director Technical Program Manager remote",
    "Head of Product remote",
    "Senior Product Manager healthcare OR fintech remote",
    "Staff Product Manager remote",
    "Principal Product Manager remote",
]

HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9",
    },
]


def _search(query: str) -> BeautifulSoup | None:
    headers = random.choice(HEADERS_POOL)
    params = {"q": query, "l": "Remote", "sort": "date", "fromage": "3"}
    try:
        resp = requests.get(BASE_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [indeed] Request failed for '{query}': {e}")
        return None


def _parse_jobs(soup: BeautifulSoup) -> list[dict]:
    jobs = []
    # Indeed job card selectors
    cards = soup.select("div.job_seen_beacon, div.tapItem, li.css-5lfssm")

    for card in cards:
        try:
            title_el = card.select_one("h2.jobTitle span, h2 a span, .jobTitle a")
            company_el = card.select_one("span.companyName, div.companyName, span[data-testid='company-name']")
            location_el = card.select_one("div.companyLocation, span[data-testid='text-location']")
            snippet_el = card.select_one("div.job-snippet, div[data-testid='jobDescriptionSnippet']")
            link_el = card.select_one("h2.jobTitle a, a[data-jk]")

            if not title_el or not company_el:
                continue

            job_key = link_el.get("data-jk", "") if link_el else ""
            url = f"https://www.indeed.com/viewjob?jk={job_key}" if job_key else ""

            jobs.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True),
                "location": location_el.get_text(strip=True) if location_el else "Remote",
                "description": snippet_el.get_text(strip=True)[:500] if snippet_el else "",
                "url": url,
                "posted_date": datetime.now(timezone.utc).isoformat(),
                "source": "indeed",
            })
        except Exception:
            continue

    return jobs


def scrape(config: dict) -> list[dict]:
    max_results = config.get("indeed_max_results", 50)
    delay = config.get("rate_limit_delay_seconds", 2)
    all_jobs = []

    for query in SEARCH_QUERIES:
        if len(all_jobs) >= max_results:
            break

        print(f"  [indeed] Searching: {query}")
        soup = _search(query)

        if soup:
            jobs = _parse_jobs(soup)
            all_jobs.extend(jobs)
            print(f"  [indeed] Found {len(jobs)} jobs")

        time.sleep(delay + random.uniform(0.5, 2))

    result = all_jobs[:max_results]
    print(f"  [indeed] Total: {len(result)} jobs")
    return result
