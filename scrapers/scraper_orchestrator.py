"""
Scraper orchestrator: reads enabled_sources from system_config.json,
dynamically imports each scraper, merges results, saves to data/jobs_raw.json.

Adding a new scraper:
  1. Create scrapers/<name>_scraper.py with a scrape(config) -> list[dict] function
  2. Add "<name>" to config/system_config.json -> scraping.enabled_sources

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


def load_config() -> dict:
    with open(ROOT / "config" / "system_config.json") as f:
        return json.load(f)


def run_scraper(source_name: str, config: dict) -> list[dict]:
    module_name = f"scrapers.{source_name}_scraper"
    try:
        module = importlib.import_module(module_name)
        jobs = module.scrape(config)
        return jobs if isinstance(jobs, list) else []
    except ModuleNotFoundError:
        print(f"  [orchestrator] Scraper not found: {module_name}")
        return []
    except Exception as e:
        print(f"  [orchestrator] Error in {source_name} scraper: {e}")
        return []


def main(run_number: int = 1):
    config = load_config()
    scraping_config = config["scraping"]
    enabled_sources = scraping_config.get("enabled_sources", [])

    print(f"\n{'='*60}")
    print(f"Job Scout Scraper — Run {run_number}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Enabled sources: {', '.join(enabled_sources)}")
    print(f"{'='*60}\n")

    all_jobs = []
    source_counts = {}

    for source in enabled_sources:
        print(f"\nRunning {source} scraper...")
        jobs = run_scraper(source, scraping_config)
        source_counts[source] = len(jobs)
        all_jobs.extend(jobs)

    # Enforce daily job limit
    daily_limit = scraping_config.get("daily_job_limit", 200)
    if len(all_jobs) > daily_limit:
        all_jobs = all_jobs[:daily_limit]

    # Attach run metadata to every job
    discovered_at = datetime.now(timezone.utc).isoformat()
    for job in all_jobs:
        job["metadata"] = {
            "run_number": run_number,
            "discovered_at": discovered_at,
            "is_new_since_last_run": True,
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(all_jobs, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Scraping complete")
    print(f"  Total jobs: {len(all_jobs)}")
    for source, count in source_counts.items():
        print(f"  {source}: {count}")
    print(f"  Saved to: {OUTPUT_PATH}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-number", type=int, default=1)
    args = parser.parse_args()
    main(run_number=args.run_number)
