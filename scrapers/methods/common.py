"""Shared helpers used by every contracting scrape method."""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def job_key(job: dict) -> str:
    """Dedup key — URL is unique per posting; title alone collapses same-title jobs in different cities."""
    return job.get("url") or job["title"].lower()


def title_matches_keywords(title: str, keywords: list[str]) -> bool:
    return any(kw.lower() in title.lower() for kw in keywords)
