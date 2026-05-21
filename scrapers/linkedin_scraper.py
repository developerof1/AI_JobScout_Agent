"""
LinkedIn scraper using undetected-chromedriver for stealth browsing.
Searches broadly across all target job titles to find relevant roles.
"""

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).parent.parent

# All target titles combined into one broad search
SEARCH_TITLES = [
    "Senior Technical Program Manager",
    "Director Technical Program Management",
    "Staff Technical Program Manager",
    "Senior Product Manager",
    "Staff Product Manager",
    "Principal Product Manager",
    "Director Product Management",
    "VP Product Operations",
    "Director Product Operations",
    "Head of Product Delivery",
    "VP Product",
    "Head of Product",
    "Founding Product Manager",
    "CPO",
]

SEARCH_KEYWORDS = " OR ".join(f'"{t}"' for t in SEARCH_TITLES)
LOCATION = "United States"


def _random_delay(min_sec: float = 2.0, max_sec: float = 4.0):
    time.sleep(random.uniform(min_sec, max_sec))


def scrape(config: dict) -> list[dict]:
    """
    Scrape LinkedIn jobs using undetected-chromedriver.
    Returns list of job dicts with standard schema.
    """
    max_results = config.get("linkedin_max_results", 100)
    jobs = []

    try:
        import undetected_chromedriver as uc
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("  [linkedin] undetected-chromedriver not installed. Run: pip install undetected-chromedriver selenium")
        return []

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")

    driver = None
    try:
        driver = uc.Chrome(options=options, version_main=None)
        driver.implicitly_wait(5)

        keywords_encoded = quote_plus(SEARCH_KEYWORDS)
        location_encoded = quote_plus(LOCATION)
        # f_TPR=r86400 = past 24 hours; f_E=4,5 = Director + Executive
        url = (
            f"https://www.linkedin.com/jobs/search/"
            f"?keywords={keywords_encoded}"
            f"&location={location_encoded}"
            f"&f_TPR=r86400"
            f"&f_WT=2"  # remote
            f"&sortBy=DD"  # date descending
        )

        print(f"  [linkedin] Loading jobs page...")
        driver.get(url)
        _random_delay(3, 5)

        seen_ids = set()
        scroll_attempts = 0
        max_scrolls = 15

        while len(jobs) < max_results and scroll_attempts < max_scrolls:
            job_cards = driver.find_elements(By.CSS_SELECTOR, "div.job-search-card, li.jobs-search-results__list-item")

            for card in job_cards:
                if len(jobs) >= max_results:
                    break
                try:
                    job_id = card.get_attribute("data-job-id") or card.get_attribute("data-entity-urn") or ""
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)

                    title_el = card.find_element(By.CSS_SELECTOR, "h3.base-search-card__title, .job-card-list__title, span.sr-only")
                    company_el = card.find_element(By.CSS_SELECTOR, "h4.base-search-card__subtitle, .job-card-container__primary-description")
                    location_el = card.find_element(By.CSS_SELECTOR, "span.job-search-card__location, .job-card-container__metadata-item")
                    link_el = card.find_element(By.CSS_SELECTOR, "a.base-card__full-link, a.job-card-list__title")

                    title = title_el.text.strip()
                    company = company_el.text.strip()
                    location = location_el.text.strip()
                    url_job = link_el.get_attribute("href").split("?")[0]

                    if not title or not company:
                        continue

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "description": "",  # filled by detail page fetch if needed
                        "url": url_job,
                        "posted_date": datetime.now(timezone.utc).isoformat(),
                        "source": "linkedin",
                    })
                except Exception:
                    continue

            # Scroll down to load more
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            _random_delay(2, 3)
            scroll_attempts += 1

            # Click "See more jobs" if present
            try:
                see_more = driver.find_element(By.CSS_SELECTOR, "button.infinite-scroller__show-more-button")
                driver.execute_script("arguments[0].click();", see_more)
                _random_delay(2, 3)
            except Exception:
                pass

        print(f"  [linkedin] Found {len(jobs)} jobs")

    except Exception as e:
        print(f"  [linkedin] Error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return jobs


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    from config_loader import load_config
    cfg = load_config()
    results = scrape(cfg["scraping"])
    output = ROOT / "data" / "jobs_raw_linkedin.json"
    with open(output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Saved {len(results)} jobs to {output}")
