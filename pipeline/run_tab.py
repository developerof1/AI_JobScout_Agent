"""
Driver: one --tab-parameterized entrypoint replacing contracting_scraper.py
(contracting) and scraper_orchestrator.py + utils/deduplicator.py (scouting).

Loads config/tabs/{tab}.json, dispatches fetch through the Source Registry,
applies the Filter Engine per profile (skipping any dimension every active
source already declares "fixed" at fetch time), dedups per the tab's declared
strategy, and writes the output envelope in the same shape the tab's current
pipeline produces.

Scoring stays a separate, unchanged step (scoring/multi_resume_scorer.py) —
this driver only replaces fetch + filter + dedup.

Config:  config/tabs/{tab}.json
Output:  the tab config's "output" path (override with --output for dry runs)
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.source_registry import SOURCE_REGISTRY
from utils.filter_engine import FilterEngine

TABS_DIR = ROOT / "config" / "tabs"
SYSTEM_CONFIG_PATH = ROOT / "config" / "system_config.json"


def load_tab_config(tab: str) -> dict:
    with open(TABS_DIR / f"{tab}.json") as f:
        return json.load(f)


def _build_source_config(source: dict, scraping_config: dict) -> dict:
    return {
        **source.get("config", {}),
        "name": source["name"],
        "rate_limit_delay_seconds": scraping_config.get("rate_limit_delay_seconds", 1),
    }


def fetch_all(tab_config: dict, scraping_config: dict) -> list[tuple[dict, list[dict]]]:
    fetched = []
    for source in tab_config["sources"]:
        method = source["method"]
        fetch_fn = SOURCE_REGISTRY.get(method)
        if not fetch_fn:
            print(f"  [run_tab] unknown source method '{method}', skipping")
            continue
        jobs = fetch_fn(_build_source_config(source, scraping_config))
        fetched.append((source, jobs))
    return fetched


def _skip_dimensions(tab_config: dict, methods_used: set) -> set:
    """A dimension is skipped only when every active source already applies it
    ("fixed") at fetch time — re-running it here would be redundant, not wrong."""
    dimension_support = tab_config.get("dimension_support", {})
    all_dims = {d for p in tab_config.get("profiles", []) for d in p["dimensions"]}
    return {
        dim
        for dim in all_dims
        if methods_used and all(dimension_support.get(m, {}).get(dim) == "fixed" for m in methods_used)
    }


def apply_profiles(jobs: list[dict], tab_config: dict, methods_used: set, tag_key: str) -> list[dict]:
    skip = _skip_dimensions(tab_config, methods_used)
    final_jobs = []
    seen_keys = set()
    for profile in tab_config.get("profiles", []):
        dims = {k: v for k, v in profile["dimensions"].items() if k not in skip}
        engine = FilterEngine(dims)
        matched = engine.tag(engine.apply_all(jobs), tag_key, profile["name"])
        for job in matched:
            key = (
                (job.get("company") or job.get("firm") or "").lower(),
                (job.get("title") or "").lower(),
                job.get("url") or "",
            )
            if key not in seen_keys:
                seen_keys.add(key)
                final_jobs.append(job)
    return final_jobs


def dedup(jobs: list[dict], strategy: str) -> list[dict]:
    return FilterEngine({}, dedup_strategy=strategy).dedup(jobs)


def _make_hash(firm_name: str, title: str) -> str:
    key = f"{firm_name.lower()}|{title.lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def build_grouped_output(
    tab_config: dict, fetched: list[tuple[dict, list[dict]]], existing_output_path: Path
) -> dict:
    existing_hashes: dict[str, str] = {}
    if existing_output_path.exists():
        try:
            with open(existing_output_path) as f:
                existing = json.load(f)
            for firm_data in existing.get("firms", []):
                for job in firm_data.get("jobs", []):
                    if job.get("_hash"):
                        existing_hashes[job["_hash"]] = job["discovered_at"]
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for source, jobs in fetched:
        name = source["name"]
        firm_jobs = []
        for raw_job in jobs:
            job = dict(raw_job)
            job["firm"] = name
            job["department"] = source.get("config", {}).get("department")
            job["_hash"] = _make_hash(name, job["title"])
            if job["_hash"] in existing_hashes:
                job["discovered_at"] = existing_hashes[job["_hash"]]
                job["is_new"] = False
            else:
                job["discovered_at"] = now
                job["is_new"] = True
            firm_jobs.append(job)

        cfg = source.get("config", {})
        display_url = cfg.get("url") or (cfg.get("urls") or [""])[0] or cfg.get("api_url", "")
        results.append({"name": name, "url": display_url, "jobs": firm_jobs})

    return {"last_run": now, "firms": results}


def build_scouting_output(
    tab_config: dict, fetched: list[tuple[dict, list[dict]]], scraping_config: dict, run_number: int
) -> list[dict]:
    all_jobs = [job for _, jobs in fetched for job in jobs]
    methods_used = {source["method"] for source in tab_config["sources"]}
    filtered = apply_profiles(all_jobs, tab_config, methods_used, tag_key="tier")
    unique = dedup(filtered, tab_config.get("dedup_strategy", "hash"))

    daily_limit = scraping_config.get("daily_job_limit", 200)
    if len(unique) > daily_limit:
        unique = unique[:daily_limit]

    discovered_at = datetime.now(timezone.utc).isoformat()
    for job in unique:
        job.setdefault("metadata", {})
        job["metadata"].update({
            "run_number": run_number,
            "discovered_at": discovered_at,
            "is_new_since_last_run": True,
        })

    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tab", required=True, choices=["contracting", "scouting", "healthcare_it"])
    parser.add_argument("--run-number", type=int, default=1)
    parser.add_argument("--output", help="Override output path (for verification runs)")
    args = parser.parse_args()

    tab_config = load_tab_config(args.tab)
    with open(SYSTEM_CONFIG_PATH) as f:
        scraping_config = json.load(f)["scraping"]

    print(f"[run_tab:{args.tab}] fetching {len(tab_config['sources'])} source(s)...")
    fetched = fetch_all(tab_config, scraping_config)
    output_path = Path(args.output) if args.output else ROOT / tab_config["output"]

    if tab_config.get("display", {}).get("shape") == "grouped_by_firm":
        output = build_grouped_output(tab_config, fetched, ROOT / tab_config["output"])
        total = sum(len(r["jobs"]) for r in output["firms"])
        summary = f"{total} jobs across {len(output['firms'])} firm(s)"
    else:
        output = build_scouting_output(tab_config, fetched, scraping_config, args.run_number)
        summary = f"{len(output)} unique jobs"
        if tab_config.get("scoring", {}).get("enabled") and not args.output:
            # scoring/multi_resume_scorer.py owns tab_config["output"] (the final,
            # dashboard-facing file) — the driver's job ends at the unscored,
            # deduped list, handed off via this fixed interchange path.
            output_path = ROOT / "data" / "jobs_unique.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[run_tab:{args.tab}] {summary} -> {output_path}")


if __name__ == "__main__":
    main()
