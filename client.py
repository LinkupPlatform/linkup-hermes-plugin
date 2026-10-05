"""Minimal Linkup REST client (standard library only).

Every public function returns a parsed JSON ``dict`` or raises :class:`LinkupError`
with a message that is safe to hand back to the model.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from . import __version__

API_BASE = "https://api.linkup.so/v1"
KEY_ENV = "LINKUP_API_KEY"
SIGNUP_URL = "https://app.linkup.so"
USER_AGENT = f"linkup-hermes-plugin/{__version__}"

DEFAULT_TIMEOUT = 60
DEEP_SEARCH_TIMEOUT = 300
FETCH_TIMEOUT = 120
BROKEN_RENDER_MAX_CHARS = 200
NOSCRIPT_CHECK_MAX_CHARS = 2000
FALLBACK_MIN_SECONDS = 10
_NOSCRIPT_MARKERS = ("enable javascript", "javascript is required", "javascript is disabled",
                     "requires javascript", "turn on javascript")


class LinkupError(Exception):
    """A Linkup request failed; ``str(exc)`` is a user-presentable message."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def get_api_key() -> str:
    """``LINKUP_API_KEY`` via Hermes' config-aware lookup (``~/.hermes/.env``, profile
    scopes), falling back to the process environment outside Hermes."""
    try:
        from agent.web_search_provider import get_provider_env
    except ImportError:
        return os.environ.get(KEY_ENV, "").strip()
    return get_provider_env(KEY_ENV)


def has_api_key() -> bool:
    try:
        return bool(get_api_key())
    except Exception:  # noqa: BLE001 — availability checks must never raise
        return False


def _base_url() -> str:
    return (os.environ.get("LINKUP_API_BASE_URL") or API_BASE).rstrip("/")


def _error_message(status: int, body: str) -> str:
    try:
        err = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        err = {}
    message = err.get("message") if isinstance(err, dict) else None
    details = err.get("details") if isinstance(err, dict) else None
    if details:
        parts = [f"{d.get('field')}: {d.get('message')}" for d in details if isinstance(d, dict)]
        message = f"{message or 'Validation failed'} ({'; '.join(parts)})"
    if status == 401:
        return f"Linkup rejected the API key (401). Check {KEY_ENV} — keys are at {SIGNUP_URL}."
    if status == 402:
        return f"Linkup account is out of credits (402). Top up at {SIGNUP_URL}."
    if status == 429:
        return "Linkup rate limit reached (429). Wait a moment and retry."
    return f"Linkup API error {status}: {message or body.strip()[:500] or 'no details'}"


def request(method: str, path: str, payload: Optional[Dict[str, Any]] = None,
            timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    api_key = get_api_key()
    if not api_key:
        raise LinkupError(f"{KEY_ENV} is not set. Get a free key at {SIGNUP_URL}, then run "
                          f"`hermes config set {KEY_ENV} <key>` or add it to ~/.hermes/.env.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        _base_url() + path, data=data, method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise LinkupError(_error_message(exc.code, body), status=exc.code) from None
    except (socket.timeout, TimeoutError):
        raise LinkupError(f"Linkup request timed out after {int(timeout)}s.") from None
    except urllib.error.URLError as exc:
        raise LinkupError(f"Could not reach Linkup API: {exc.reason}") from None
    try:
        return json.loads(body) if body else {}
    except ValueError:
        raise LinkupError(f"Linkup returned a non-JSON response: {body[:200]}") from None


def search(payload: Dict[str, Any]) -> Dict[str, Any]:
    timeout = DEEP_SEARCH_TIMEOUT if payload.get("depth") == "deep" else DEFAULT_TIMEOUT
    return request("POST", "/search", payload, timeout=timeout)


def looks_like_broken_render(markdown: str) -> bool:
    """A JS render that produced next to nothing, or a "please enable JavaScript" wall."""
    text = markdown.strip()
    if len(text) < BROKEN_RENDER_MAX_CHARS:
        return True
    return len(text) < NOSCRIPT_CHECK_MAX_CHARS and any(m in text.lower() for m in _NOSCRIPT_MARKERS)


def _remaining(deadline: Optional[float]) -> float:
    if deadline is None:
        return FETCH_TIMEOUT
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LinkupError("Linkup fetch ran out of time before it could start.")
    return min(FETCH_TIMEOUT, remaining)


def fetch(payload: Dict[str, Any], js_fallback: bool = False, deadline: Optional[float] = None) -> Dict[str, Any]:
    """``js_fallback``: when a JS-rendered page looks broken (sites whose client bundle crashes in a
    headless browser), refetch without rendering and keep the longer one. ``deadline`` is a
    ``time.monotonic()`` bound for both requests; the fallback is skipped when little time is left."""
    data = request("POST", "/fetch", payload, timeout=_remaining(deadline))
    markdown = data.get("markdown") or ""
    if not (js_fallback and payload.get("renderJs")) or not looks_like_broken_render(markdown):
        return data
    if deadline is not None and deadline - time.monotonic() < FALLBACK_MIN_SECONDS:
        return data
    try:
        static = request("POST", "/fetch", {**payload, "renderJs": False}, timeout=_remaining(deadline))
    except LinkupError:
        return data
    return static if len(static.get("markdown") or "") > len(markdown) else data


def start_research(payload: Dict[str, Any]) -> Dict[str, Any]:
    return request("POST", "/research", payload)


def get_research(task_id: str) -> Dict[str, Any]:
    return request("GET", f"/research/{task_id}")


def balance() -> Dict[str, Any]:
    return request("GET", "/credits/balance", timeout=15)
