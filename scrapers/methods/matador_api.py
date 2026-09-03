"""Matador Jobs Pro REST API method — no HTML parsing or JS rendering needed.
Used for firms whose careers site runs the Matador Jobs Pro WordPress plugin, which
exposes a public `matador/v1/jobs/job-listings` REST endpoint supporting a `s=` keyword
search. Results are capped at 10 per query server-side with no working pagination
parameter (page/paged/per_page/posts_per_page/number all confirmed no-ops), so this
queries once per configured keyword and merges/dedupes results, same as the multi-URL
firms under the html method.
"""

import html
import random
import time

import requests

from .common import HEADERS, job_key, title_matches_keywords


def scrape(firm: dict, keywords: list[str]) -> list[dict]:
    name = firm["name"]
    api_url = firm["api_url"]
    skip_kw = firm.get("skip_keyword_filter", False)

    all_jobs: list[dict] = []
    seen_keys: set[str] = set()

    for kw in keywords:
        try:
            resp = requests.get(
                api_url,
                params={"fields": "id,title,location,link", "s": kw},
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            items = resp.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  [contracting] {name}: API query failed for '{kw}': {e}")
            continue

        for item in items:
            title = html.unescape(item.get("title", ""))
            if not title or (not skip_kw and not title_matches_keywords(title, keywords)):
                continue
            location = ", ".join(item.get("location", [])) if item.get("location") else ""
            job = {"title": title, "url": item.get("link", ""), "location": location}
            key = job_key(job)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_jobs.append(job)

        time.sleep(random.uniform(0.3, 0.7))

    print(f"  [contracting] {name}: {len(all_jobs)} matching jobs")
    return all_jobs
