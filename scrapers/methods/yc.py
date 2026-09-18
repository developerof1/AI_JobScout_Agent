"""
Y Combinator jobs method — reads the JSON blob (Inertia `data-page`) embedded in
ycombinator.com/jobs/role/{role} pages. No login or JS rendering needed.
Filters title (keywords) and location (cities + Remote-US) at fetch time, like the
other contracting methods, and returns standard-schema jobs.
"""

import html
import json
import random
import re
import time

import requests

from scrapers.methods.common import HEADERS, title_matches_keywords

BASE_URL = "https://www.ycombinator.com"
ROLE_URL = BASE_URL + "/jobs/role/{role}"
_DATA_PAGE = re.compile(r'data-page="([^"]+)"')
_REMOTE_US = re.compile(r"remote\b.*\b(us|usa|united states)\b")


def _fetch_role(role: str) -> list[dict]:
    try:
        resp = requests.get(ROLE_URL.format(role=role), headers=HEADERS, timeout=20)
        resp.raise_for_status()
        match = _DATA_PAGE.search(resp.content.decode("utf-8", errors="replace"))
        postings = json.loads(html.unescape(match.group(1)))["props"]["jobPostings"]
        print(f"  [yc] Role '{role}': {len(postings)} jobs fetched")
        return postings
    except (requests.RequestException, AttributeError, KeyError, ValueError) as e:
        print(f"  [yc] Failed to fetch role '{role}' (page structure may have changed): {e}")
        return []


def _location_matches(location: str, cities: list[str]) -> bool:
    loc = location.lower()
    if any(city.lower() in loc for city in cities):
        return True
    segments = [s.strip() for s in loc.split(" / ")]
    if any(_REMOTE_US.match(s) for s in segments):
        return True
    return "us" in segments and "remote" in segments


def scrape(config: dict, keywords: list[str]) -> list[dict]:
    roles = config.get("roles", ["product-manager", "operations", "support"])
    cities = config.get("locations", [])
    delay = config.get("rate_limit_delay_seconds", 1)
    jobs = []
    seen_ids = set()

    for i, role in enumerate(roles):
        for posting in _fetch_role(role):
            if posting["id"] in seen_ids:
                continue
            seen_ids.add(posting["id"])
            if not title_matches_keywords(posting["title"], keywords):
                continue
            if not _location_matches(posting.get("location") or "", cities):
                continue
            jobs.append({
                # Company is prefixed because a grouped tab has no per-job company field
                "title": f"{posting['companyName']} — {posting['title']}",
                "location": posting.get("location", ""),
                "url": BASE_URL + posting["url"],
            })
        if i < len(roles) - 1:
            time.sleep(delay + random.uniform(0, 0.5))

    print(f"  [yc] Total matching jobs: {len(jobs)}")
    return jobs
