"""
Builtin.com job board scraper using requests + BeautifulSoup.
Searches Product Management and TPM categories.
"""

import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent

BASE_URL = "https://builtin.com/jobs"

SEARCH_QUERIES = [
    {"title": "VP Product Operations", "remote": True},
    {"title": "Director Product Management", "remote": True},
    {"title": "Head of Product", "remote": True},
    {"title": "Technical Program Manager", "remote": True},
    {"title": "Senior Product Manager", "remote": True},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _search(query: str, remote: bool = True) -> BeautifulSoup | None:
    params = {"q": query}
    if remote:
        params["remote"] = "true"
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [builtin] Request failed for '{query}': {e}")
        return None


def _parse_jobs(soup: BeautifulSoup) -> list[dict]:
    jobs = []
    # Builtin job card selectors — adjust if site structure changes
    cards = soup.select("article.job-card, div[data-id], li.job-result")

    for card in cards:
        try:
            title_el = card.select_one("h2 a, h3 a, a.job-title, span.job-name")
            company_el = card.select_one("span.company-name, a.company-link, div.company")
            location_el = card.select_one("span.location, div.location-text")
            desc_el = card.select_one("div.description, p.job-description")

            if not title_el or not company_el:
                continue

            href = title_el.get("href", "")
            url = f"https://builtin.com{href}" if href.startswith("/") else href

            jobs.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True),
                "location": location_el.get_text(strip=True) if location_el else "Remote",
                "description": desc_el.get_text(strip=True)[:500] if desc_el else "",
                "url": url,
                "posted_date": datetime.now(timezone.utc).isoformat(),
                "source": "builtin",
            })
        except Exception:
            continue

    return jobs


def scrape(config: dict) -> list[dict]:
    max_results = config.get("builtin_max_results", 30)
    delay = config.get("rate_limit_delay_seconds", 2)
    all_jobs = []

    for search in SEARCH_QUERIES:
        if len(all_jobs) >= max_results:
            break

        title = search["title"]
        print(f"  [builtin] Searching: {title}")
        soup = _search(title, remote=search.get("remote", True))

        if soup:
            jobs = _parse_jobs(soup)
            all_jobs.extend(jobs)
            print(f"  [builtin] Found {len(jobs)} jobs for '{title}'")

        time.sleep(delay + random.uniform(0, 1))

    result = all_jobs[:max_results]
    print(f"  [builtin] Total: {len(result)} jobs")
    return result
