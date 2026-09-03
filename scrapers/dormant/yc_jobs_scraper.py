"""
Y Combinator / Work at a Startup job board scraper.
Targets PM, Head of Product, and founding product roles at YC-backed companies.
"""

import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent

BASE_URL = "https://www.workatastartup.com/jobs"

SEARCH_PARAMS_LIST = [
    {"q": "product manager", "remote": "true", "role": "product"},
    {"q": "head of product", "remote": "true"},
    {"q": "technical program manager", "remote": "true"},
    {"q": "founding product", "remote": "true"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.workatastartup.com/",
}


def _fetch(params: dict) -> BeautifulSoup | None:
    try:
        resp = requests.get(BASE_URL, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [yc_jobs] Request failed: {e}")
        return None


def _parse_jobs(soup: BeautifulSoup) -> list[dict]:
    jobs = []
    # Work at a Startup job listing selectors
    cards = soup.select(
        "div.job-name, div[class*='JobResult'], li[class*='job'], div.listing"
    )

    # Fallback: look for any links that look like job listings
    if not cards:
        cards = soup.select("a[href*='/jobs/']")

    for card in cards:
        try:
            # Handle both card divs and anchor tags
            if card.name == "a":
                title = card.get_text(strip=True)
                href = card.get("href", "")
                company = ""
                location = "Remote"
                description = ""
            else:
                title_el = card.select_one("a.job-name, h3, h2, .title")
                company_el = card.select_one("span.company, a.company-name, .company")
                location_el = card.select_one("span.location, .remote")
                desc_el = card.select_one("div.description, p")
                link_el = card.select_one("a[href*='/jobs/']")

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else ""
                location = location_el.get_text(strip=True) if location_el else "Remote"
                description = desc_el.get_text(strip=True)[:500] if desc_el else ""
                href = link_el.get("href", "") if link_el else ""

            if not title:
                continue

            url = f"https://www.workatastartup.com{href}" if href.startswith("/") else href

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "description": description,
                "url": url,
                "posted_date": datetime.now(timezone.utc).isoformat(),
                "source": "yc_jobs",
            })
        except Exception:
            continue

    return jobs


def scrape(config: dict) -> list[dict]:
    max_results = config.get("yc_jobs_max_results", 25)
    delay = config.get("rate_limit_delay_seconds", 2)
    all_jobs = []

    for params in SEARCH_PARAMS_LIST:
        if len(all_jobs) >= max_results:
            break

        print(f"  [yc_jobs] Searching: {params.get('q', '')}")
        soup = _fetch(params)

        if soup:
            jobs = _parse_jobs(soup)
            all_jobs.extend(jobs)
            print(f"  [yc_jobs] Found {len(jobs)} jobs")

        time.sleep(delay + random.uniform(0, 1))

    result = all_jobs[:max_results]
    print(f"  [yc_jobs] Total: {len(result)} jobs")
    return result
