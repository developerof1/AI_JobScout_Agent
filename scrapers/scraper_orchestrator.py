"""
Scraper orchestrator: loads active_sources from search_config.json,
runs each source, applies tier filters, saves to data/jobs_raw.json.

Adding a new source:
  1. Create scrapers/<name>_scraper.py with scrape(config) -> list[dict]
  2. Add "<name>" to config/search_config.json -> sources
  3. Add "<name>" to config/search_config.json -> active_sources

Adding a new tier:
  1. Add tier definition to config/search_config.json -> tiers
  2. Add tier name to config/search_config.json -> active_tiers

No changes to this file needed.
"""

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OUTPUT_PATH = ROOT / "data" / "jobs_raw.json"
SYSTEM_CONFIG_PATH = ROOT / "config" / "system_config.json"
SEARCH_CONFIG_PATH = ROOT / "config" / "search_config.json"


def load_configs() -> tuple[dict, dict]:
    with open(SYSTEM_CONFIG_PATH) as f:
        system_config = json.load(f)
    with open(SEARCH_CONFIG_PATH) as f:
        search_config = json.load(f)
    return system_config, search_config


def run_source(source_name: str, config: dict) -> list[dict]:
    module_name = f"scrapers.{source_name}_scraper"
    try:
        module = importlib.import_module(module_name)
        jobs = module.scrape(config)
        return jobs if isinstance(jobs, list) else []
    except ModuleNotFoundError:
        print(f"  [orchestrator] Source module not found: {module_name}")
        return []
    except Exception as e:
        print(f"  [orchestrator] Error in {source_name}: {e}")
        return []


def apply_tiers(all_jobs: list[dict], search_config: dict) -> list[dict]:
    from utils.job_filter import JobFilter

    active_tiers = search_config.get("active_tiers", [])
    tiers = search_config.get("tiers", {})

    final_jobs = []
    seen_hashes = {}

    for tier_name in active_tiers:
        tier = tiers.get(tier_name)
        if not tier:
            print(f"  [orchestrator] Tier '{tier_name}' not found in search_config.json")
            continue

        f = JobFilter(tier)
        matched = f.apply_all(all_jobs)
        matched = f.tag_tier(matched, tier_name)

        for job in matched:
            # Dedup across tiers — keep first (highest priority) tier match
            key = (
                (job.get("company") or "").lower(),
                (job.get("title") or "").lower(),
                (job.get("url") or ""),
            )
            if key not in seen_hashes:
                seen_hashes[key] = True
                final_jobs.append(job)

        print(f"  [orchestrator] Tier '{tier_name}' ({tier['name']}): {len(matched)} jobs matched")

    return final_jobs


def main(run_number: int = 1):
    system_config, search_config = load_configs()
    scraping_config = system_config["scraping"]
    active_sources = search_config.get("active_sources", [])

    print(f"\n{'='*60}")
    print(f"Job Scout — Run {run_number}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Active sources: {', '.join(active_sources)}")
    print(f"Active tiers:   {', '.join(search_config.get('active_tiers', []))}")
    print(f"{'='*60}\n")

    # Step 1: Fetch all raw jobs from active sources
    all_raw_jobs = []
    source_counts = {}

    for source in active_sources:
        print(f"\nRunning {source}...")
        jobs = run_source(source, scraping_config)
        source_counts[source] = len(jobs)
        all_raw_jobs.extend(jobs)

    print(f"\n  Total raw jobs fetched: {len(all_raw_jobs)}")

    # Step 2: Apply tier filters — keep only jobs matching active tiers
    print(f"\nApplying tier filters...")
    all_jobs = apply_tiers(all_raw_jobs, search_config)

    # Step 3: Enforce daily job limit
    daily_limit = scraping_config.get("daily_job_limit", 200)
    if len(all_jobs) > daily_limit:
        all_jobs = all_jobs[:daily_limit]

    # Step 4: Attach run metadata
    discovered_at = datetime.now(timezone.utc).isoformat()
    for job in all_jobs:
        job.setdefault("metadata", {})
        job["metadata"].update({
            "run_number": run_number,
            "discovered_at": discovered_at,
            "is_new_since_last_run": True,
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_jobs, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Scraping complete")
    print(f"  Raw fetched:    {len(all_raw_jobs)}")
    for source, count in source_counts.items():
        print(f"    {source}: {count}")
    print(f"  After tier filter: {len(all_jobs)}")
    print(f"  Saved to: {OUTPUT_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-number", type=int, default=1)
    args = parser.parse_args()
    main(run_number=args.run_number)
