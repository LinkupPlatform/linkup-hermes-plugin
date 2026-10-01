"""Plugin settings (``plugins.entries.linkup.settings.*`` in config.yaml), read at call time."""

from __future__ import annotations

from typing import Any, Optional

DEFAULTS = {
    "search_depth": "standard",
    "web_search_depth": "standard",
    "fetch_render_js": True,
    "research_reasoning_depth": "M",
}

_ctx: Optional[Any] = None


def bind(ctx: Any) -> None:
    global _ctx
    _ctx = ctx


def get(key: str) -> Any:
    default = DEFAULTS[key]
    if _ctx is None:
        return default
    try:
        value = _ctx.get_config(key, default)
    except Exception:  # noqa: BLE001 — a bad config must not break a tool call
        return default
    if value is None or (isinstance(default, bool) and not isinstance(value, bool)):
        return default
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return value
