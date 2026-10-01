"""Linkup as a Hermes web backend for the built-in ``web_search`` / ``web_extract`` tools.

Select it with ``hermes config set web.backend linkup`` (or ``web.search_backend`` /
``web.extract_backend`` to use Linkup for only one of the two).
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

from . import client, settings
from .client import LinkupError

logger = logging.getLogger(__name__)

EXTRACT_WORKERS = 5

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
        if depth not in ("flash", "fast", "standard", "deep"):
            depth = "standard"
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

    def _extract_one(self, url: str) -> Dict[str, Any]:
        try:
            data = client.fetch({"url": url, "renderJs": bool(settings.get("fetch_render_js"))}, js_fallback=True)
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
        with ThreadPoolExecutor(max_workers=min(EXTRACT_WORKERS, len(urls))) as pool:
            return list(pool.map(self._extract_one, urls))

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Linkup",
            "badge": "paid",
            "tag": "Agentic web search (fast/standard/deep) + page fetch with JS rendering and PDFs.",
            "env_vars": [{"key": client.KEY_ENV, "prompt": "Linkup API key", "url": client.SIGNUP_URL}],
        }
