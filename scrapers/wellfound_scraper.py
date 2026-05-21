"""
Wellfound (AngelList Talent) scraper using requests + BeautifulSoup.
Targets PM, TPM, and Product Operations roles at startups.
"""

import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent

BASE_URL = "https://wellfound.com/jobs"

SEARCH_ROLES = [
    "product-manager",
    "technical-program-manager",
    "head-of-product",
]

HEADERS_POOL = [
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"},
    {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"},
    {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36"},
]


def _get(url: str, params: dict = None) -> BeautifulSoup | None:
    headers = random.choice(HEADERS_POOL)
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [wellfound] Request failed: {e}")
        return None


def _parse_job_cards(soup: BeautifulSoup, source_role: str) -> list[dict]:
    jobs = []
    # Wellfound job cards — selector may need updating if site structure changes
    cards = soup.select("div[data-test='StartupResult'], div.job-listing, article.job-card")

    for card in cards:
        try:
            title_el = card.select_one("a.job-title, h2.title, span[data-test='job-title']")
            company_el = card.select_one("a.startup-link, span.company-name, h3.name")
            location_el = card.select_one("span.location, div.location")
            link_el = card.select_one("a[href*='/jobs/'], a.job-title")
            desc_el = card.select_one("div.description, p.description, div.job-description")

            if not title_el or not company_el:
                continue

            href = link_el.get("href", "") if link_el else ""
            url = f"https://wellfound.com{href}" if href.startswith("/") else href

            jobs.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True),
                "location": location_el.get_text(strip=True) if location_el else "Remote",
                "description": desc_el.get_text(strip=True)[:500] if desc_el else "",
                "url": url,
                "posted_date": datetime.now(timezone.utc).isoformat(),
                "source": "wellfound",
            })
        except Exception:
            continue

    return jobs


def scrape(config: dict) -> list[dict]:
    max_results = config.get("wellfound_max_results", 50)
    delay = config.get("rate_limit_delay_seconds", 2)
    all_jobs = []

    for role in SEARCH_ROLES:
        if len(all_jobs) >= max_results:
            break

        url = f"{BASE_URL}?role={role}&remote=true&seniority[]=sr_mid&seniority[]=director&seniority[]=vp&seniority[]=c_level"
        print(f"  [wellfound] Scraping role: {role}")
        soup = _get(url)

        if soup:
            jobs = _parse_job_cards(soup, role)
            all_jobs.extend(jobs)
            print(f"  [wellfound] Found {len(jobs)} jobs for {role}")

        time.sleep(delay + random.uniform(0, 1))

    result = all_jobs[:max_results]
    print(f"  [wellfound] Total: {len(result)} jobs")
    return result
