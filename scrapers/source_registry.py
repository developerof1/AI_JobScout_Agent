"""
Source Registry: uniform name -> fetch(source_config) -> list[dict] dispatch,
wrapping the existing scrape entrypoints in scrapers/methods/ unchanged.

Two call shapes exist today among the wrapped modules:
  - api sources (remotive, adzuna): scrape(scraping_config) -> full standard-schema jobs
  - contracting sources (html, matador_api): scrape(firm_config, keywords) -> partial jobs,
    firm/company fields stamped by the caller afterward (see pipeline/run_tab.py)
The wrappers below normalize both to the same call shape: fetch(source_config) -> list[dict],
where source_config is whatever config dict the wrapped module already expects (system
scraping config, or a firm config with a "keywords" list folded in).

Adding a new source: write one wrapper function and add it to SOURCE_REGISTRY.
No driver changes needed.
"""

from scrapers.methods import adzuna, html_pages, matador_api, remotive


def _fetch_html(source_config: dict) -> list[dict]:
    return html_pages.scrape(source_config, source_config.get("keywords", []))


def _fetch_matador_api(source_config: dict) -> list[dict]:
    return matador_api.scrape(source_config, source_config.get("keywords", []))


def _fetch_remotive(source_config: dict) -> list[dict]:
    return remotive.scrape(source_config)


def _fetch_adzuna(source_config: dict) -> list[dict]:
    return adzuna.scrape(source_config)


SOURCE_REGISTRY = {
    "html": _fetch_html,
    "matador_api": _fetch_matador_api,
    "remotive": _fetch_remotive,
    "adzuna": _fetch_adzuna,
}
