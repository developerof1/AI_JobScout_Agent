"""Registry of contracting scrape strategies. Firms declare their method in
config/contracting_firms.json via the "method" field (default "html"); new
strategies are added here without touching the orchestrator (contracting_scraper.py).
"""

from . import html_pages, matador_api

METHOD_REGISTRY = {
    "html": html_pages.scrape,
    "matador_api": matador_api.scrape,
}
