"""
Contracting jobs scraper — fetches job titles from staffing firm websites.
Each firm declares a `method` in config (default "html"); scrape_firm() dispatches
to the matching strategy in contracting_methods/ and stamps the shared job fields.

Config:  config/contracting_firms.json
Output:  data/contracting_jobs.json
"""

import hashlib
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from contracting_methods import METHOD_REGISTRY

ROOT = Path(__file__).parent.parent
CONFIG_PATH = ROOT / "config" / "contracting_firms.json"
OUTPUT_PATH = ROOT / "data" / "contracting_jobs.json"


def _make_hash(firm_name: str, title: str) -> str:
    key = f"{firm_name.lower()}|{title.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def scrape_firm(firm: dict, keywords: list[str]) -> list[dict]:
    name = firm["name"]
    method_name = firm.get("method", "html")
    scrape_fn = METHOD_REGISTRY.get(method_name)
    if not scrape_fn:
        print(f"  [contracting] {name}: unknown method '{method_name}', skipping")
        return []

    jobs = scrape_fn(firm, keywords)

    for job in jobs:
        job["firm"] = name
        job["_hash"] = _make_hash(name, job["title"])
        job["discovered_at"] = datetime.now(timezone.utc).isoformat()

    return jobs


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

        display_url = firm.get("url") or firm.get("urls", [""])[0] or firm.get("api_url", "")
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
