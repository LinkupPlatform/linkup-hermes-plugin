"""Linkup as a Hermes web backend for the built-in ``web_search`` / ``web_extract`` tools.

Select it with ``hermes config set web.backend linkup`` (or ``web.search_backend`` /
``web.extract_backend`` to use Linkup for only one of the two).
"""

from __future__ import annotations

import contextvars
import html
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, as_completed
from typing import Any, Dict, List, Optional

from agent.web_search_provider import WebSearchProvider

from . import client, settings
from .client import LinkupError

logger = logging.getLogger(__name__)

EXTRACT_WORKERS = 5
DEFAULT_EXTRACT_TIMEOUT = 120.0
EXTRACT_DEADLINE_MARGIN = 5.0


def _extract_budget() -> Optional[float]:
    """Seconds this batch may take: Hermes' ``web.extract_timeout`` minus a margin, so finished pages
    come back before core's timeout discards the whole batch. ``None`` when the cap is disabled."""
    try:
        from hermes_cli.config import load_config_readonly
        web = (load_config_readonly() or {}).get("web") or {}
        timeout = float(web.get("extract_timeout", DEFAULT_EXTRACT_TIMEOUT))
    except Exception:  # noqa: BLE001
        timeout = DEFAULT_EXTRACT_TIMEOUT
    if timeout <= 0:
        return None
    return max(1.0, timeout - EXTRACT_DEADLINE_MARGIN)

_HEADING_RE = re.compile(r"^\s{0,3}#{1,2}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _title_from_markdown(markdown: str, fallback: str) -> str:
    match = _HEADING_RE.search(markdown[:5000])
    return match.group(1).strip() if match else fallback


class LinkupWebSearchProvider(WebSearchProvider):
    """Search via ``/v1/search`` (searchResults) and extract via ``/v1/fetch``."""

    @property
    def name(self) -> str:
        return "linkup"

    @property
    def display_name(self) -> str:
        return "Linkup"

    def is_available(self) -> bool:
        return client.has_api_key()

    def supports_extract(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        depth = settings.get("web_search_depth")
        payload = {
            "q": query,
            "depth": depth,
            "outputType": "searchResults",
            "maxResults": max(1, int(limit or 5)),
        }
        logger.info("Linkup search (%s): %r (limit=%d)", depth, query, payload["maxResults"])
        try:
            data = client.search(payload)
        except LinkupError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Linkup search error: %s", exc)
            return {"success": False, "error": f"Linkup search failed: {exc}"}
        rows = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("type", "text") == "text"]
        return {"success": True, "data": {"web": [
            {"title": html.unescape(r.get("name") or ""), "url": r.get("url") or "",
             "description": r.get("content") or "", "position": i + 1}
            for i, r in enumerate(rows)
        ]}}

    def _extract_one(self, url: str, deadline: Optional[float] = None) -> Dict[str, Any]:
        try:
            data = client.fetch({"url": url, "renderJs": bool(settings.get("fetch_render_js"))},
                                js_fallback=True, deadline=deadline)
        except LinkupError as exc:
            return {"url": url, "title": "", "content": "", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"url": url, "title": "", "content": "", "error": f"Linkup fetch failed: {exc}"}
        markdown = data.get("markdown") or ""
        title = _title_from_markdown(markdown, url)
        metadata = {"sourceURL": url, "title": title}
        if data.get("favicon"):
            metadata["favicon"] = data["favicon"]
        return {"url": url, "title": title, "content": markdown, "raw_content": markdown, "metadata": metadata}

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        urls = [u for u in urls or [] if isinstance(u, str) and u.strip()]
        if not urls:
            return []
        logger.info("Linkup extract: %d URL(s)", len(urls))
        budget = _extract_budget()
        deadline = time.monotonic() + budget if budget is not None else None
        results: Dict[int, Dict[str, Any]] = {}
        pool = ThreadPoolExecutor(max_workers=min(EXTRACT_WORKERS, len(urls)))
        try:
            # Each worker runs in a copy of the caller's context: on a multiplexed gateway the
            # active profile's secret scope and home live in ContextVars.
            futures = {pool.submit(contextvars.copy_context().run, self._extract_one, url, deadline): i
                       for i, url in enumerate(urls)}
            try:
                for future in as_completed(futures, timeout=budget):
                    results[futures[future]] = future.result()
            except FuturesTimeout:
                logger.warning("Linkup extract: %d of %d URL(s) unfinished after %gs",
                               len(urls) - len(results), len(urls), budget)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        timed_out = f"Linkup fetch did not finish within {budget or 0:g}s"
        return [results.get(i) or {"url": url, "title": "", "content": "", "error": timed_out}
                for i, url in enumerate(urls)]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Linkup",
            "badge": "paid",
            "tag": "Agentic web search (fast/standard/deep) + page fetch with JS rendering and PDFs.",
            "env_vars": [{"key": client.KEY_ENV, "prompt": "Linkup API key", "url": client.SIGNUP_URL}],
        }
