"""
JobFilter: applies tier-level and global filters to a list of raw jobs.

Filters applied in order: location → title → date
"""

from datetime import datetime, timezone, timedelta


# Location strings from Remotive that map to US remote
_US_LOCATION_TOKENS = [
    "usa", "united states", "us only", "remote - us", "remote us",
    "north america", "u.s.", "u.s.a.",
]

_REMOTE_TOKENS = ["remote", "anywhere", "distributed"]

_WORLDWIDE_TOKENS = ["worldwide", "global", ""]


class JobFilter:
    def __init__(self, tier_config: dict, global_filters: dict = None):
        self.tier = tier_config
        self.global_filters = global_filters or {}
        self.filters = tier_config.get("filters", {})

    # ── Public API ──────────────────────────────────────────────────────────

    def apply_all(self, jobs: list[dict]) -> list[dict]:
        jobs = self.apply_location(jobs)
        jobs = self.apply_title(jobs)
        jobs = self.apply_date(jobs)
        return jobs

    def apply_location(self, jobs: list[dict]) -> list[dict]:
        allowed = [loc.lower() for loc in self.filters.get("location", [])]
        include_worldwide = self.filters.get("include_worldwide", False)

        if not allowed:
            return jobs

        result = []
        for job in jobs:
            loc = (job.get("location") or "").lower().strip()

            if self._is_worldwide(loc):
                if include_worldwide:
                    result.append(job)
                continue

            if self._matches_us_remote(loc):
                result.append(job)
                continue

            # Check against explicitly allowed locations (e.g. "Chicago")
            for allowed_loc in allowed:
                if allowed_loc in loc or loc in allowed_loc:
                    result.append(job)
                    break

        return result

    def apply_title(self, jobs: list[dict]) -> list[dict]:
        keywords = self.tier.get("title_keywords", [])
        required_pairs = self.tier.get("title_required_pairs", [])

        if not keywords:
            return jobs

        result = []
        for job in jobs:
            title = (job.get("title") or "").lower()
            description = (job.get("description") or "").lower()

            for keyword in keywords:
                if keyword.lower() in title:
                    # Check required pair if this keyword has one
                    pair_match = self._check_required_pair(
                        keyword, title, description, required_pairs
                    )
                    if pair_match:
                        result.append(job)
                    break

        return result

    def apply_date(self, jobs: list[dict]) -> list[dict]:
        days = self.filters.get("posted_within_days")
        if not days:
            return jobs

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for job in jobs:
            posted = job.get("posted_date") or job.get("publication_date")
            if not posted:
                result.append(job)
                continue
            try:
                dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
                if dt >= cutoff:
                    result.append(job)
            except (ValueError, AttributeError):
                result.append(job)

        return result

    def tag_tier(self, jobs: list[dict], tier_name: str) -> list[dict]:
        for job in jobs:
            job["tier"] = tier_name
        return jobs

    # ── Private helpers ─────────────────────────────────────────────────────

    def _is_worldwide(self, loc: str) -> bool:
        if loc == "":
            return True
        return any(token in loc for token in _WORLDWIDE_TOKENS if token)

    def _matches_us_remote(self, loc: str) -> bool:
        for token in _US_LOCATION_TOKENS:
            if token in loc:
                return True
        for token in _REMOTE_TOKENS:
            if token in loc:
                return True
        return False

    def _check_required_pair(
        self,
        keyword: str,
        title: str,
        description: str,
        required_pairs: list,
    ) -> bool:
        for pair_keyword, pair_required in required_pairs:
            if pair_keyword.lower() == keyword.lower():
                combined = title + " " + description
                return any(req.lower() in combined for req in pair_required)
        return True
