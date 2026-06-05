"""
Contracting jobs scraper — fetches job titles from staffing firm websites.
Generic strategy: finds heading tags (<h3>/<h2>/<h4>) inside <a> tags.
Falls back to Selenium for JS-heavy pages if requests returns no matches.

Config:  config/contracting_firms.json
Output:  data/contracting_jobs.json
"""

import hashlib
import json
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "contracting_firms.json"
OUTPUT_PATH = ROOT / "data" / "contracting_jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

LOCATION_HINTS = [
    "remote", "hybrid", "in office", "onsite", "on-site",
    "[", "chicago", "new york", "san francisco", "austin", "boston",
    "seattle", "dallas", "atlanta", "denver", "los angeles", "miami",
]


def _make_hash(firm_name: str, title: str) -> str:
    key = f"{firm_name.lower()}|{title.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _fetch_html_requests(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [contracting] requests failed: {e}")
        return None


def _fetch_html_selenium(url: str) -> str | None:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(30)
        driver.get(url)
        time.sleep(3)
        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        print(f"  [contracting] selenium failed: {e}")
        return None


def _scrape_with_selenium_clicks(start_url: str, keywords: list[str], max_pages: int) -> list[dict]:
    """Load page once via Selenium, then click Next to paginate — preserves JS filter state."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By

        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        base_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        all_jobs: list[dict] = []
        seen_titles: set[str] = set()

        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(30)
        driver.get(start_url)
        time.sleep(3)

        for page_num in range(1, max_pages + 1):
            page_jobs = _extract_jobs(driver.page_source, base_url, keywords)
            new_jobs = [j for j in page_jobs if j["title"].lower() not in seen_titles]
            for j in new_jobs:
                seen_titles.add(j["title"].lower())
            all_jobs.extend(new_jobs)
            print(f"    page {page_num}: {len(new_jobs)} new match(es)")

            # Try clicking Next or Load More
            try:
                next_btn = None
                for a in driver.find_elements(By.TAG_NAME, "a"):
                    txt = a.text.strip().lower().strip("›»> ")
                    if txt in ("next", "next page"):
                        next_btn = a
                        break
                if not next_btn:
                    for btn in driver.find_elements(By.TAG_NAME, "button"):
                        txt = btn.text.strip().lower()
                        if "more" in txt and ("view" in txt or "load" in txt):
                            next_btn = btn
                            break
                if not next_btn:
                    break
                next_btn.click()
                time.sleep(2)
            except Exception:
                break

        driver.quit()
        return all_jobs

    except Exception as e:
        print(f"  [contracting] selenium click-pagination failed: {e}")
        return []


def _find_next_page(soup, current_url: str) -> str | None:
    # rel="next" is most reliable
    tag = soup.find("a", rel="next") or soup.find("link", rel="next")
    if tag and tag.get("href"):
        return urljoin(current_url, tag["href"])
    # Common "Next" button text
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower().strip("›»> ")
        if text in ("next", "next page"):
            return urljoin(current_url, a["href"])
    return None


def _extract_location(heading_tag) -> str:
    for element in heading_tag.next_siblings:
        text = (
            element.get_text(strip=True)
            if hasattr(element, "get_text")
            else str(element).strip()
        )
        if not text or len(text) > 120:
            continue
        text_lower = text.lower()
        if any(hint in text_lower for hint in LOCATION_HINTS):
            return text
    return ""


def _extract_jobs(html: str, base_url: str, keywords: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_titles: set[str] = set()

    # Strategy 1: heading tags inside or adjacent to <a> tags
    for tag_name in ("h3", "h2", "h4", "h1"):
        for heading in soup.find_all(tag_name):
            title = heading.get_text(strip=True)
            if not title or title.lower() in seen_titles:
                continue
            if re.search(r'^\d+\s+.+\bjobs?\b', title.lower()):
                continue
            if not any(kw in title.lower() for kw in keywords):
                continue

            link = heading.find_parent("a") or heading.find("a")
            job_url = ""
            if link and link.get("href"):
                job_url = urljoin(base_url, link["href"])

            location = _extract_location(heading)
            seen_titles.add(title.lower())
            jobs.append({"title": title, "url": job_url, "location": location})

        if jobs:
            return jobs

    # Strategy 2: <a> tags whose class names suggest job listings
    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class", []))
        if not any(p in cls.lower() for p in ("job", "position", "title", "role", "career")):
            continue
        title = a.get_text(strip=True)
        if not title or title.lower() in seen_titles:
            continue
        if not any(kw in title.lower() for kw in keywords):
            continue
        seen_titles.add(title.lower())
        jobs.append({"title": title, "url": urljoin(base_url, a["href"]), "location": ""})

    return jobs


def scrape_firm(firm: dict, keywords: list[str]) -> list[dict]:
    name = firm["name"]
    max_pages = firm.get("max_pages", 10)
    use_js = firm.get("requires_js", False)
    url_list = firm.get("urls") or [firm["url"]]

    all_jobs: list[dict] = []
    seen_titles: set[str] = set()

    for i, start_url in enumerate(url_list):
        base_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        print(f"  [contracting] Scraping {name} @ {start_url} (js={use_js}, max_pages={max_pages}) ...")

        if use_js:
            url_jobs = _scrape_with_selenium_clicks(start_url, keywords, max_pages)
            if not url_jobs:
                print(f"  [contracting] Falling back to requests (page 1 only) ...")
                html = _fetch_html_requests(start_url)
                url_jobs = _extract_jobs(html, base_url, keywords) if html else []
        else:
            url_jobs = []
            current_url = start_url
            page_num = 1
            while current_url and page_num <= max_pages:
                html = _fetch_html_requests(current_url)
                if not html:
                    break
                soup = BeautifulSoup(html, "html.parser")
                for job in _extract_jobs(html, base_url, keywords):
                    if job["title"].lower() not in seen_titles:
                        url_jobs.append(job)
                current_url = _find_next_page(soup, current_url)
                page_num += 1
                if current_url:
                    time.sleep(random.uniform(0.5, 1.0))

        for job in url_jobs:
            if job["title"].lower() not in seen_titles:
                seen_titles.add(job["title"].lower())
                all_jobs.append(job)

        if i < len(url_list) - 1:
            time.sleep(random.uniform(1, 2))

    for job in all_jobs:
        job["firm"] = name
        job["_hash"] = _make_hash(name, job["title"])
        job["discovered_at"] = datetime.now(timezone.utc).isoformat()

    print(f"  [contracting] {name}: {len(all_jobs)} matching jobs")
    return all_jobs


def main():
    if not CONFIG_PATH.exists():
        print("[contracting] config/contracting_firms.json not found")
        return

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    keywords = [kw.lower() for kw in config.get("keywords", ["project manager", "program manager", "product manager"])]
    firms = [f for f in config.get("firms", []) if f.get("active", True)]

    if not firms:
        print("[contracting] No active firms configured")
        return

    # Preserve discovered_at for jobs seen in previous runs
    existing_hashes: dict[str, str] = {}
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH) as f:
                existing = json.load(f)
            for firm_data in existing.get("firms", []):
                for job in firm_data.get("jobs", []):
                    if job.get("_hash"):
                        existing_hashes[job["_hash"]] = job["discovered_at"]
        except Exception:
            pass

    results = []
    for i, firm in enumerate(firms):
        firm_jobs = scrape_firm(firm, keywords)
        for job in firm_jobs:
            if job["_hash"] in existing_hashes:
                job["discovered_at"] = existing_hashes[job["_hash"]]
                job["is_new"] = False
            else:
                job["is_new"] = True

        display_url = firm.get("url") or firm.get("urls", [""])[0]
        results.append({"name": firm["name"], "url": display_url, "jobs": firm_jobs})

        if i < len(firms) - 1:
            time.sleep(random.uniform(1, 2))

    output = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "firms": results,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    total = sum(len(r["jobs"]) for r in results)
    print(f"[contracting] Done. {total} jobs across {len(results)} firm(s) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
