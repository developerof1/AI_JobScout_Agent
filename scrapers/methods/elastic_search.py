"""Direct Elasticsearch REST API method — no HTML parsing or JS rendering needed.
Used for firms whose careers site queries Elastic Cloud straight from the browser using a
public, client-facing API key embedded in the page (e.g. Aquent's `aqJobsOptions` config).
Not tied to any one firm — any site exposing the same pattern (host + index + api_key)
plugs in via config alone, same as matador_api.
"""

import requests

from .common import HEADERS, job_key, title_matches_keywords

PAGE_SIZE = 100
MAX_RESULTS = 1000


def _build_query(firm: dict) -> dict:
    filters = []

    region = firm.get("region")
    if region:
        filters.append({"term": {"region.keyword": region}})

    cities = firm.get("cities_any_onsite", [])
    location_should = [{"term": {"offsite_preference.keyword": "Remote"}}]
    for city in cities:
        location_should.append({
            "bool": {
                "filter": [
                    {"term": {"city.keyword": city}},
                    {"terms": {"offsite_preference.keyword": ["Onsite", "Hybrid"]}},
                ]
            }
        })
    filters.append({"bool": {"should": location_should, "minimum_should_match": 1}})

    return {"bool": {"filter": filters}}


def scrape(firm: dict, keywords: list[str]) -> list[dict]:
    name = firm["name"]
    host = firm["elastic_host"].rstrip("/")
    index = firm["index"]
    api_key = firm["api_key"]
    listing_url = firm["listing_url"].rstrip("/")
    skip_kw = firm.get("skip_keyword_filter", False)

    headers = {
        **HEADERS,
        "Authorization": f"ApiKey {api_key}",
        "Content-Type": "application/json",
    }
    query = _build_query(firm)

    all_jobs: list[dict] = []
    seen_keys: set[str] = set()
    from_ = 0

    while from_ < MAX_RESULTS:
        body = {
            "query": query,
            "sort": [{"posted_date": "desc"}],
            "from": from_,
            "size": PAGE_SIZE,
        }
        try:
            resp = requests.post(f"{host}/{index}/_search", headers=headers, json=body, timeout=20)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except (requests.RequestException, ValueError) as e:
            print(f"  [contracting] {name}: Elasticsearch query failed: {e}")
            break

        if not hits:
            break

        for hit in hits:
            src = hit.get("_source", {})
            title = src.get("job_title", "")
            if not title or (not skip_kw and not title_matches_keywords(title, keywords)):
                continue
            city = src.get("city", "")
            state = src.get("state", "")
            location = f"{city}, {state}" if city and state else (city or src.get("location", ""))
            job_id = src.get("job_id", "")
            url = f"{listing_url}/{job_id}" if job_id else ""
            job = {"title": title, "url": url, "location": location}
            key = job_key(job)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_jobs.append(job)

        if len(hits) < PAGE_SIZE:
            break
        from_ += PAGE_SIZE

    print(f"  [contracting] {name}: {len(all_jobs)} matching jobs")
    return all_jobs
