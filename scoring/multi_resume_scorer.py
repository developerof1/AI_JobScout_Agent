"""
Multi-resume scorer: evaluates each job against all 6 resume profiles simultaneously.
Claude picks the best-fit primary resume, a backup, and scores 0-100.

Pipeline:
  data/jobs_unique.json  (or jobs_filtered.json if applied tracking is active)
  + config/resume_profiles.json
  -> data/jobs_scored.json  (sorted by score descending)
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PROFILES_PATH = ROOT / "config" / "resume_profiles.json"
RULES_PATH = ROOT / "config" / "scoring_rules.json"
SCORED_OUTPUT = ROOT / "data" / "jobs_scored.json"

SCORING_PROMPT = """\
You are evaluating a job posting for Satwik Bardhan. He has {num_resumes} specialized resumes.
Your task: determine which resume is the BEST fit and score the job using that resume.

RESUME PROFILES:
{resume_profiles_text}

JOB POSTING:
Title: {title}
Company: {company}
Location: {location}
Description:
{description}

EVALUATION PROCESS:

Step 1: RESUME SELECTION
- Evaluate this job against ALL {num_resumes} resumes
- Consider: title match, seniority level, domain alignment, required experience
- Pick PRIMARY resume (best overall fit)
- Pick BACKUP resume (second-best, if primary feels too aggressive or conservative)

Step 2: SCORE WITH PRIMARY RESUME (Total 100 points)

1. Title Match (40 points):
   - Exact match to primary resume's target titles: 40
   - Close variant (e.g., "Sr Director" vs "Director"): 30-35
   - Related but different (e.g., "VP Product" vs "VP Product Ops"): 20-25
   - Weak match: 10-15
   - No match: 0

2. Seniority Match (20 points):
   - Matches primary resume's seniority exactly: 20
   - One level off: 15
   - Two levels off: 10
   - Misaligned: 0

3. Domain Match (20 points):
   - Primary domain match: 20
   - Adjacent domain: 15
   - Transferable domain: 10
   - Unrelated: 0

4. Experience Match (20 points):
   - JD requires 3+ of resume's key experiences: 20
   - JD requires 2 of resume's key experiences: 15
   - JD requires 1: 10
   - No clear match: 5

ADJUSTMENTS (see scoring_rules.json):
- Red flags reduce score 5-20 points
- Bonus criteria add 5-10 points

Step 3: RETURN JSON

Return ONLY valid JSON (no markdown, no preamble):
{{
  "primary_resume": <1-{num_resumes}>,
  "primary_resume_name": "<Resume name>",
  "primary_resume_file": "<filename.pdf>",
  "score": <0-100>,
  "reasoning": "<2-3 sentence explanation of primary resume choice and score>",
  "backup_resume": <1-{num_resumes}>,
  "backup_resume_name": "<Backup resume name>",
  "backup_resume_file": "<filename.pdf>",
  "backup_reasoning": "<1-2 sentence explanation of why backup could work>",
  "breakdown": {{
    "title_match": <0-40>,
    "seniority_match": <0-20>,
    "domain_match": <0-20>,
    "experience_match": <0-20>,
    "adjustments": <-20 to +10>
  }},
  "highlights": ["<positive aspect 1>", "<positive aspect 2>", "<positive aspect 3>"],
  "red_flags": ["<concern 1>"],
  "confidence": "<high|medium|low>"
}}
"""


def build_resume_profiles_text(profiles: list[dict]) -> str:
    parts = []
    for p in profiles:
        lines = [
            f"Resume {p['id']} - {p['name']} ({p['positioning']}):",
            f"  Target titles: {', '.join(p.get('target_criteria', {}).get('titles', [])[:4])}",
            f"  Domains: {', '.join(p.get('target_criteria', {}).get('domains', [])[:4])}",
            f"  Seniority: {', '.join(p.get('target_criteria', {}).get('seniority', []))}",
            f"  Key experiences: {'; '.join(p.get('key_experiences', [])[:4])}",
            f"  Key metrics: {'; '.join(p.get('key_metrics', [])[:4])}",
            f"  Differentiators: {'; '.join(p.get('differentiators', [])[:3])}",
        ]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def should_auto_reject(job: dict, rules: dict) -> bool:
    description = (job.get("description") or "").lower()
    title = (job.get("title") or "").lower()
    combined = f"{title} {description}"

    for keyword in rules.get("red_flags", {}).get("auto_reject", []):
        if keyword.lower() in combined:
            return True
    return False


def parse_score_response(response_text: str) -> dict | None:
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


def score_job(job: dict, profiles: list[dict], rules: dict, ai) -> dict | None:
    resume_text = build_resume_profiles_text(profiles)
    description = (job.get("description") or "")[:2000]  # cap description length

    prompt = SCORING_PROMPT.format(
        num_resumes=len(profiles),
        resume_profiles_text=resume_text,
        title=job.get("title", ""),
        company=job.get("company", ""),
        location=job.get("location", ""),
        description=description,
    )

    try:
        response = ai.score_job(prompt)
        score_data = parse_score_response(response)
        return score_data
    except Exception as e:
        print(f"    Error scoring job '{job.get('title')}' at '{job.get('company')}': {e}")
        return None


def load_jobs() -> list[dict]:
    # Prefer filtered (applied jobs removed) over unique
    filtered_path = ROOT / "data" / "jobs_filtered.json"
    unique_path = ROOT / "data" / "jobs_unique.json"

    if filtered_path.exists():
        with open(filtered_path) as f:
            return json.load(f)
    elif unique_path.exists():
        with open(unique_path) as f:
            return json.load(f)
    else:
        print("No jobs file found. Run scraper_orchestrator.py and deduplicator.py first.")
        sys.exit(1)


def main(run_number: int = 1):
    from scoring.ai_provider import AIProvider

    if not PROFILES_PATH.exists():
        print(f"Resume profiles not found at {PROFILES_PATH}")
        print("Run: python utils/resume_embedder.py")
        sys.exit(1)

    with open(PROFILES_PATH) as f:
        profiles_data = json.load(f)
    profiles = profiles_data.get("resumes", [])

    with open(RULES_PATH) as f:
        rules = json.load(f)

    config_path = ROOT / "config" / "system_config.json"
    with open(config_path) as f:
        config = json.load(f)
    scoring_config = config.get("scoring", {})
    min_score = scoring_config.get("min_score_to_display", 70)
    batch_size = scoring_config.get("batch_size", 10)
    batch_delay = scoring_config.get("batch_delay_seconds", 1)

    jobs = load_jobs()
    ai = AIProvider()

    print(f"\n{'='*60}")
    print(f"Multi-Resume Scorer — Run {run_number}")
    print(f"Provider: {ai.get_provider_info()['provider']} / {ai.get_provider_info()['model']}")
    print(f"Resumes: {len(profiles)} profiles loaded")
    print(f"Jobs to score: {len(jobs)}")
    print(f"{'='*60}\n")

    # Load existing scored jobs to merge (keep previously scored jobs not in today's batch)
    existing_scored = []
    if SCORED_OUTPUT.exists():
        with open(SCORED_OUTPUT) as f:
            existing_scored = json.load(f)

    existing_hashes = {j.get("_hash") for j in existing_scored if j.get("_hash")}

    scored_jobs = []
    rejected_count = 0
    error_count = 0
    now = datetime.now(timezone.utc)

    for i, job in enumerate(jobs):
        job_hash = job.get("_hash", "")

        # Skip if already scored in a previous run
        if job_hash and job_hash in existing_hashes:
            continue

        # Auto-reject on hard red flags (saves API cost)
        if should_auto_reject(job, rules):
            rejected_count += 1
            continue

        print(f"  [{i+1}/{len(jobs)}] Scoring: {job.get('title')} @ {job.get('company')}")
        score_data = score_job(job, profiles, rules, ai)

        if score_data is None:
            error_count += 1
            continue

        # Compute age in hours from discovery time
        discovered_at = job.get("metadata", {}).get("discovered_at") or now.isoformat()
        try:
            disc_dt = datetime.fromisoformat(discovered_at.replace("Z", "+00:00"))
            age_hours = (now - disc_dt).total_seconds() / 3600
        except Exception:
            age_hours = 0

        scored_job = {
            **job,
            "score": score_data.get("score", 0),
            "primary_resume": score_data.get("primary_resume"),
            "primary_resume_name": score_data.get("primary_resume_name"),
            "primary_resume_file": score_data.get("primary_resume_file"),
            "reasoning": score_data.get("reasoning"),
            "backup_resume": score_data.get("backup_resume"),
            "backup_resume_name": score_data.get("backup_resume_name"),
            "backup_resume_file": score_data.get("backup_resume_file"),
            "backup_reasoning": score_data.get("backup_reasoning"),
            "breakdown": score_data.get("breakdown", {}),
            "highlights": score_data.get("highlights", []),
            "red_flags": score_data.get("red_flags", []),
            "confidence": score_data.get("confidence", "medium"),
            "metadata": {
                **job.get("metadata", {}),
                "run_number": run_number,
                "age_hours": round(age_hours, 1),
                "is_new_since_last_run": True,
                "scored_at": now.isoformat(),
            },
        }
        scored_jobs.append(scored_job)

        # Batch delay to avoid rate limits
        if (i + 1) % batch_size == 0:
            print(f"  Batch complete ({i+1} jobs). Pausing {batch_delay}s...")
            time.sleep(batch_delay)

    # Merge new scored jobs with previously-scored ones (mark old as not new)
    for j in existing_scored:
        j["metadata"]["is_new_since_last_run"] = False
    merged = scored_jobs + existing_scored

    # Sort by score descending, then by freshness
    merged.sort(key=lambda j: (-j.get("score", 0), j.get("metadata", {}).get("age_hours", 999)))

    SCORED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "_metadata": {
            "last_run": now.isoformat(),
            "run_number": run_number,
            "total_jobs": len(merged),
            "scored_this_run": len(scored_jobs),
        },
        "jobs": merged,
    }
    with open(SCORED_OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    high_priority = [j for j in scored_jobs if j.get("score", 0) >= 85]
    review_needed = [j for j in scored_jobs if 70 <= j.get("score", 0) < 85]

    print(f"\n{'='*60}")
    print(f"Scoring complete")
    print(f"  Scored this run: {len(scored_jobs)}")
    print(f"  Auto-rejected:   {rejected_count}")
    print(f"  Errors:          {error_count}")
    print(f"  High priority (>=85): {len(high_priority)}")
    print(f"  Review needed (70-84): {len(review_needed)}")
    print(f"  Total in dashboard: {len(merged)}")
    print(f"  Saved to: {SCORED_OUTPUT}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-number", type=int, default=1)
    args = parser.parse_args()
    main(run_number=args.run_number)
