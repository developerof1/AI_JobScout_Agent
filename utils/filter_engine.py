"""
FilterEngine: applies named, pluggable filter dimensions to a list of raw jobs,
plus a selectable dedup strategy.

Dimensions (location, title, date) carry the same matching logic as the old
JobFilter, now addressable by name so a Tab Config can declare which dimensions
a tab uses. Per-source support state (composable / fixed / unsupported) is
plumbing for the Tab Config / Source Registry to declare against — e.g. the
contracting html/matador_api methods already filter title inline at fetch time
("fixed"), while an API source that accepts a location query param is
"composable". Nothing here enforces support state yet.
"""

import re
from datetime import datetime, timezone, timedelta
from hashlib import md5

from scrapers.methods.common import job_key, title_matches_keywords

SUPPORT_STATES = ("composable", "fixed", "unsupported")

# ── Location ──────────────────────────────────────────────────────────────

_US_LOCATION_TOKENS = [
    "usa", "united states", "us only", "remote - us", "remote us",
    "north america", "u.s.", "u.s.a.",
]

_REMOTE_TOKENS = ["remote", "anywhere", "distributed"]

_WORLDWIDE_TOKENS = ["worldwide", "global", ""]

_US_STATES_ABBR = [
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc", "pr", "vi",
]

_US_STATES_FULL = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "district of columbia", "puerto rico", "virgin islands",
]


def _is_worldwide(loc: str) -> bool:
    if loc == "":
        return True
    return any(token in loc for token in _WORLDWIDE_TOKENS if token)


def _matches_us_remote(loc: str) -> bool:
    return any(token in loc for token in _US_LOCATION_TOKENS) or any(
        token in loc for token in _REMOTE_TOKENS
    )


def _is_us_location(loc: str) -> bool:
    words_lower = [word.rstrip(",").lower() for word in loc.split()]
    if any(word in _US_STATES_ABBR for word in words_lower):
        return True
    loc_lower = loc.lower()
    return any(state in loc_lower for state in _US_STATES_FULL)


def _dim_location(jobs: list[dict], config: dict) -> list[dict]:
    allowed = [loc.lower() for loc in config.get("allowed", [])]
    include_worldwide = config.get("include_worldwide", False)

    if not allowed:
        return jobs

    result = []
    for job in jobs:
        loc = (job.get("location") or "").lower().strip()

        if _is_worldwide(loc):
            if include_worldwide:
                result.append(job)
            continue

        if _matches_us_remote(loc) or _is_us_location(loc):
            result.append(job)
            continue

        for allowed_loc in allowed:
            if allowed_loc in loc or loc in allowed_loc:
                result.append(job)
                break

    return result


# ── Title ─────────────────────────────────────────────────────────────────


def _check_required_pair(
    keyword: str, title_lower: str, description_lower: str, required_pairs: list
) -> bool:
    for pair in required_pairs:
        pair_keyword, pair_required = pair[0], pair[1]
        title_only = pair[2] if len(pair) > 2 else False
        if pair_keyword.lower() == keyword.lower():
            text = title_lower if title_only else (title_lower + " " + description_lower)
            return any(req.lower() in text for req in pair_required)
    return True


def _dim_title(jobs: list[dict], config: dict) -> list[dict]:
    keywords = config.get("keywords", [])
    required_pairs = config.get("required_pairs", [])

    if not keywords:
        return jobs

    result = []
    for job in jobs:
        title = job.get("title") or ""
        if not title_matches_keywords(title, keywords):
            continue

        title_lower = title.lower()
        description_lower = (job.get("description") or "").lower()
        matched_keyword = next(
            (kw for kw in keywords if kw.lower() in title_lower), title
        )
        if _check_required_pair(matched_keyword, title_lower, description_lower, required_pairs):
            result.append(job)

    return result


# ── Date ──────────────────────────────────────────────────────────────────


def _dim_date(jobs: list[dict], config: dict) -> list[dict]:
    days = config.get("posted_within_days")
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


DIMENSIONS = {
    "location": _dim_location,
    "title": _dim_title,
    "date": _dim_date,
}

# ── Dedup ─────────────────────────────────────────────────────────────────


def _dedup_by_url(jobs: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for job in jobs:
        key = job_key(job)
        if key not in seen:
            seen.add(key)
            result.append(job)
    return result


def _normalize_title(title: str) -> str:
    title = title.lower()
    # Collapse common abbreviations and variants
    title = re.sub(r"\bvp\b", "vice president", title)
    title = re.sub(r"\bsr\.?\b", "senior", title)
    title = re.sub(r"\bdir\.?\b", "director", title)
    title = re.sub(r"\bmgr\.?\b", "manager", title)
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def _job_hash(job: dict) -> str:
    company = (job.get("company") or "").lower().strip()
    title = _normalize_title(job.get("title") or "")
    desc_snippet = (job.get("description") or "")[:100].lower()
    key = f"{company}|{title}|{desc_snippet}"
    return md5(key.encode()).hexdigest()[:16]


def _dedup_by_hash(jobs: list[dict]) -> list[dict]:
    """Hashes company + normalized title + description snippet. Merges source
    metadata when the same job appears on multiple boards."""
    seen: dict[str, dict] = {}
    for job in jobs:
        h = _job_hash(job)
        if h not in seen:
            seen[h] = dict(job)
            seen[h]["_hash"] = h
            seen[h]["sources"] = [job.get("source", "unknown")]
        else:
            src = job.get("source", "unknown")
            if src not in seen[h]["sources"]:
                seen[h]["sources"].append(src)
            if len(job.get("description", "")) > len(seen[h].get("description", "")):
                seen[h]["description"] = job["description"]
    return list(seen.values())


DEDUP_STRATEGIES = {
    "url": _dedup_by_url,
    "hash": _dedup_by_hash,
}


# ── Engine ────────────────────────────────────────────────────────────────


class FilterEngine:
    def __init__(self, dimension_configs: dict, dedup_strategy: str = "hash"):
        self.dimension_configs = dimension_configs
        self.dedup_strategy = dedup_strategy

    def apply_dimension(self, name: str, jobs: list[dict]) -> list[dict]:
        matcher = DIMENSIONS.get(name)
        if not matcher:
            raise ValueError(f"Unknown filter dimension: {name}")
        config = self.dimension_configs.get(name)
        if not config:
            return jobs
        return matcher(jobs, config)

    def apply_all(self, jobs: list[dict], order: tuple = ("location", "title", "date")) -> list[dict]:
        for name in order:
            jobs = self.apply_dimension(name, jobs)
        return jobs

    def dedup(self, jobs: list[dict]) -> list[dict]:
        strategy = DEDUP_STRATEGIES.get(self.dedup_strategy)
        if not strategy:
            raise ValueError(f"Unknown dedup strategy: {self.dedup_strategy}")
        return strategy(jobs)

    def tag(self, jobs: list[dict], key: str, value: str) -> list[dict]:
        result = []
        for job in jobs:
            tagged = dict(job)
            tagged[key] = value
            result.append(tagged)
        return result

    @classmethod
    def from_tier_config(cls, tier_config: dict, dedup_strategy: str = "hash") -> "FilterEngine":
        """Adapter for search_config.json's existing tier shape (title_keywords/
        title_required_pairs at the top level, location/date under `filters`) —
        translates it into named dimension configs without touching the config file."""
        filters = tier_config.get("filters", {})
        dimension_configs = {
            "location": {
                "allowed": filters.get("location", []),
                "include_worldwide": filters.get("include_worldwide", False),
            },
            "title": {
                "keywords": tier_config.get("title_keywords", []),
                "required_pairs": tier_config.get("title_required_pairs", []),
            },
            "date": {
                "posted_within_days": filters.get("posted_within_days"),
            },
        }
        return cls(dimension_configs, dedup_strategy=dedup_strategy)
