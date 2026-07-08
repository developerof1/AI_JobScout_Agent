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
import subprocess
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode

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


def _job_key(job: dict) -> str:
    """Dedup key — URL is unique per posting; title alone collapses same-title jobs in different cities."""
    return job.get("url") or job["title"].lower()


def _make_hash(firm_name: str, title: str) -> str:
    key = f"{firm_name.lower()}|{title.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _get_chrome_major_version() -> int | None:
    for cmd in (["google-chrome", "--version"], ["google-chrome-stable", "--version"], ["chromium-browser", "--version"]):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()
            match = re.search(r'(\d+)\.', out)
            if match:
                return int(match.group(1))
        except Exception:
            continue
    return None


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
        import undetected_chromedriver as uc

        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        driver = uc.Chrome(options=opts, headless=True, version_main=_get_chrome_major_version())
        driver.set_page_load_timeout(30)
        driver.get(url)
        time.sleep(5)
        html = driver.page_source
        driver.quit()
        return html
    except Exception as e:
        print(f"  [contracting] selenium failed: {e}")
        return None


def _scrape_with_selenium_clicks(start_url: str, keywords: list[str], max_pages: int, skip_keyword_filter: bool = False) -> list[dict]:
    """Load page once via Selenium, then click Next to paginate — preserves JS filter state."""
    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By

        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        base_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        all_jobs: list[dict] = []
        seen_keys: set[str] = set()

        driver = uc.Chrome(options=opts, headless=True, version_main=_get_chrome_major_version())
        driver.set_page_load_timeout(30)
        driver.get(start_url)
        time.sleep(5)

        for page_num in range(1, max_pages + 1):
            page_jobs = _extract_jobs(driver.page_source, base_url, keywords, skip_keyword_filter)
            new_jobs = [j for j in page_jobs if _job_key(j) not in seen_keys]
            for j in new_jobs:
                seen_keys.add(_job_key(j))
            all_jobs.extend(new_jobs)
            print(f"    page {page_num}: {len(new_jobs)} new match(es)")

            # Try clicking Next or Load More (a or button tags)
            try:
                next_btn = None
                for el in driver.find_elements(By.CSS_SELECTOR, "a, button"):
                    txt = el.text.strip().lower().strip("›»> ")
                    if txt in ("next", "next page"):
                        next_btn = el
                        break
                    if "more" in txt and ("view" in txt or "load" in txt):
                        next_btn = el
                        break
                    if txt.isdigit() and int(txt) == page_num + 1:
                        next_btn = el
                        break
                if not next_btn:
                    print(f"    page {page_num}: no next/more button found, stopping")
                    break
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(0.3)
                try:
                    next_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", next_btn)
                time.sleep(3)
            except Exception as e:
                print(f"    page {page_num}: pagination click failed: {e}")
                break

        driver.quit()
        return all_jobs

    except Exception as e:
        print(f"  [contracting] selenium click-pagination failed: {e}")
        return []


def _scrape_with_selenium_urls(start_url: str, keywords: list[str], max_pages: int, skip_keyword_filter: bool = False) -> list[dict]:
    """Navigate directly to each page via its `page` query param — more reliable than
    hunting for a clickable next/more element when the site already exposes real page URLs."""
    try:
        import undetected_chromedriver as uc

        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument(f"user-agent={HEADERS['User-Agent']}")

        base_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        all_jobs: list[dict] = []
        seen_keys: set[str] = set()

        driver = uc.Chrome(options=opts, headless=True, version_main=_get_chrome_major_version())
        driver.set_page_load_timeout(30)

        parsed = urlparse(start_url)
        query = dict(parse_qsl(parsed.query))

        for page_num in range(1, max_pages + 1):
            query["page"] = str(page_num)
            page_url = parsed._replace(query=urlencode(query)).geturl()
            driver.get(page_url)
            time.sleep(5 if page_num == 1 else 3)

            page_jobs = _extract_jobs(driver.page_source, base_url, keywords, skip_keyword_filter)
            new_jobs = [j for j in page_jobs if _job_key(j) not in seen_keys]
            for j in new_jobs:
                seen_keys.add(_job_key(j))
            all_jobs.extend(new_jobs)
            print(f"    page {page_num}: {len(new_jobs)} new match(es)")

        driver.quit()
        return all_jobs

    except Exception as e:
        print(f"  [contracting] selenium URL-pagination failed: {e}")
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


LOCATION_PATTERN = re.compile(r',\s*[A-Z]{2}\b(?:,?\s*\d{5})?\s*$')


def _extract_location(heading_tag) -> str:
    candidates = list(heading_tag.next_siblings)
    parent = heading_tag.parent
    if parent and parent.name == "a":
        # heading is the sole content of a wrapping <a> — location is likely
        # a sibling of the <a> tag itself, not of the heading (e.g. Mondo)
        candidates += list(parent.next_siblings)

    for element in candidates:
        text = (
            element.get_text(strip=True)
            if hasattr(element, "get_text")
            else str(element).strip()
        )
        if not text or len(text) > 120:
            continue
        text_lower = text.lower()
        if any(hint in text_lower for hint in LOCATION_HINTS) or LOCATION_PATTERN.search(text):
            return text
    return ""


def _extract_jobs(html: str, base_url: str, keywords: list[str], skip_keyword_filter: bool = False) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_keys: set[str] = set()

    # Strategy 1: heading tags inside or adjacent to <a> tags
    for tag_name in ("h3", "h2", "h4", "h1"):
        for heading in soup.find_all(tag_name):
            title = heading.get_text(strip=True)
            if not title:
                continue
            if re.search(r'^\d+\s+.+\bjobs?\b', title.lower()):
                continue
            if not skip_keyword_filter and not any(kw in title.lower() for kw in keywords):
                continue

            link = heading.find_parent("a") or heading.find("a")
            job_url = ""
            if link and link.get("href"):
                job_url = urljoin(base_url, link["href"])

            key = job_url or title.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)

            location = _extract_location(heading)
            jobs.append({"title": title, "url": job_url, "location": location})

        if jobs:
            return jobs

    # Strategy 2: <a> tags whose class names suggest job listings
    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class", []))
        if not any(p in cls.lower() for p in ("job", "position", "title", "role", "career")):
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        if not any(kw in title.lower() for kw in keywords):
            continue
        job_url = urljoin(base_url, a["href"])
        key = job_url or title.lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        jobs.append({"title": title, "url": job_url, "location": ""})

    return jobs


def scrape_firm(firm: dict, keywords: list[str]) -> list[dict]:
    name = firm["name"]
    max_pages = firm.get("max_pages", 10)
    use_js = firm.get("requires_js", False)
    skip_kw = firm.get("skip_keyword_filter", False)
    url_list = firm.get("urls") or [firm["url"]]

    all_jobs: list[dict] = []
    seen_keys: set[str] = set()

    for i, start_url in enumerate(url_list):
        base_url = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
        print(f"  [contracting] Scraping {name} @ {start_url} (js={use_js}, max_pages={max_pages}) ...")

        if use_js:
            has_page_param = "page" in dict(parse_qsl(urlparse(start_url).query))
            if has_page_param:
                url_jobs = _scrape_with_selenium_urls(start_url, keywords, max_pages, skip_kw)
            else:
                url_jobs = _scrape_with_selenium_clicks(start_url, keywords, max_pages, skip_kw)
            if not url_jobs:
                print(f"  [contracting] Falling back to requests (page 1 only) ...")
                html = _fetch_html_requests(start_url)
                url_jobs = _extract_jobs(html, base_url, keywords, skip_kw) if html else []
        else:
            url_jobs = []
            current_url = start_url
            page_num = 1
            while current_url and page_num <= max_pages:
                html = _fetch_html_requests(current_url)
                if not html:
                    break
                soup = BeautifulSoup(html, "html.parser")
                for job in _extract_jobs(html, base_url, keywords, skip_kw):
                    if _job_key(job) not in seen_keys:
                        url_jobs.append(job)
                current_url = _find_next_page(soup, current_url)
                page_num += 1
                if current_url:
                    time.sleep(random.uniform(0.5, 1.0))

        for job in url_jobs:
            key = _job_key(job)
            if key not in seen_keys:
                seen_keys.add(key)
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
