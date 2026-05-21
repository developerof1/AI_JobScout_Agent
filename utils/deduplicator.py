"""
Deduplicates scraped jobs by hashing company + normalized title + description snippet.
Merges source metadata when the same job appears on multiple boards.

Input:  data/jobs_raw.json
Output: data/jobs_unique.json
"""

import json
import re
import sys
from hashlib import md5
from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUT_PATH = ROOT / "data" / "jobs_raw.json"
OUTPUT_PATH = ROOT / "data" / "jobs_unique.json"


def normalize_title(title: str) -> str:
    title = title.lower()
    # Collapse common abbreviations and variants
    title = re.sub(r"\bvp\b", "vice president", title)
    title = re.sub(r"\bsr\.?\b", "senior", title)
    title = re.sub(r"\bdir\.?\b", "director", title)
    title = re.sub(r"\bmgr\.?\b", "manager", title)
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def job_hash(job: dict) -> str:
    company = (job.get("company") or "").lower().strip()
    title = normalize_title(job.get("title") or "")
    desc_snippet = (job.get("description") or "")[:100].lower()
    key = f"{company}|{title}|{desc_snippet}"
    return md5(key.encode()).hexdigest()[:16]


def deduplicate(jobs: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}

    for job in jobs:
        h = job_hash(job)
        if h not in seen:
            seen[h] = dict(job)
            seen[h]["_hash"] = h
            # Normalize source to a list for multi-source tracking
            src = job.get("source", "unknown")
            seen[h]["sources"] = [src]
        else:
            # Merge: add new source, prefer longer description
            src = job.get("source", "unknown")
            if src not in seen[h]["sources"]:
                seen[h]["sources"].append(src)
            if len(job.get("description", "")) > len(seen[h].get("description", "")):
                seen[h]["description"] = job["description"]

    unique = list(seen.values())
    return unique


def main():
    if not INPUT_PATH.exists():
        print(f"Input file not found: {INPUT_PATH}")
        sys.exit(1)

    with open(INPUT_PATH) as f:
        raw_jobs = json.load(f)

    print(f"Deduplicating {len(raw_jobs)} raw jobs...")
    unique_jobs = deduplicate(raw_jobs)
    removed = len(raw_jobs) - len(unique_jobs)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(unique_jobs, f, indent=2)

    print(f"Removed {removed} duplicates")
    print(f"Unique jobs: {len(unique_jobs)}")
    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
