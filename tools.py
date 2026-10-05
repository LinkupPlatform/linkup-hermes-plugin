"""Tool handlers. Each returns a JSON string and never raises."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Pattern
from urllib.parse import unquote

from . import client, settings
from .client import LinkupError

logger = logging.getLogger(__name__)

SEARCH_DEPTHS = settings.SEARCH_DEPTHS
SEARCH_OUTPUT_TYPES = ("searchResults", "sourcedAnswer", "structured")
RESEARCH_MODES = ("answer", "investigate", "research")
RESEARCH_DEPTHS = settings.RESEARCH_DEPTHS
RESEARCH_OUTPUT_TYPES = ("sourcedAnswer", "structured")
TERMINAL_STATUSES = ("completed", "failed")

DEFAULT_WAIT_SECONDS = 120
MAX_WAIT_SECONDS = 300
PAGE_FILE_MIN_CHARS = 20000
PAGE_FILE_MAX_AGE_SECONDS = 86400

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _ok(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _text(value: Any) -> str:
    return html.unescape(value) if isinstance(value, str) else ""


def _guard(handler: Callable[[Dict[str, Any]], str]) -> Callable[..., str]:
    def wrapped(args: Dict[str, Any], **kwargs: Any) -> str:
        try:
            return handler(args if isinstance(args, dict) else {})
        except LinkupError as exc:
            return _err(str(exc))
        except ValueError as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001 — tool handlers must never raise
            logger.exception("Linkup tool %s failed", handler.__name__)
            return _err(f"Linkup plugin error: {type(exc).__name__}: {exc}")

    wrapped.__name__ = handler.__name__
    wrapped.__doc__ = handler.__doc__
    return wrapped


def _choice(args: Dict[str, Any], key: str, allowed: tuple, default: Optional[str]) -> Optional[str]:
    value = args.get(key) or default
    if value is not None and value not in allowed:
        raise ValueError(f"{key} must be one of {', '.join(allowed)} (got {value!r})")
    return value


def _schema_arg(value: Any, key: str) -> Optional[str]:
    """Linkup accepts the schema as a JSON string; models sometimes send either form."""
    if value in (None, "", {}):
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError(f"{key} must be a JSON Schema object") from None
    if not isinstance(value, dict) or value.get("type") != "object":
        raise ValueError(f"{key} must be a JSON Schema whose root has \"type\": \"object\"")
    return json.dumps(value)


def _filters(args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, api_key in (("include_domains", "includeDomains"), ("exclude_domains", "excludeDomains")):
        domains = args.get(key)
        if isinstance(domains, str):
            domains = [d.strip() for d in domains.split(",")]
        if domains:
            out[api_key] = [d for d in domains if isinstance(d, str) and d.strip()]
    for key, api_key in (("from_date", "fromDate"), ("to_date", "toDate")):
        value = args.get(key)
        if value:
            if not isinstance(value, str) or not _DATE_RE.match(value):
                raise ValueError(f"{key} must be a YYYY-MM-DD date (got {value!r})")
            out[api_key] = value
    return out


_TEXT_FIELDS = ("name", "content", "snippet")


def _items(items: Any) -> List[Dict[str, Any]]:
    """Every Linkup result/source with all of its fields, untruncated; HTML entities in text are decoded."""
    return [
        {**item, **{k: _text(item[k]) for k in _TEXT_FIELDS if isinstance(item.get(k), str)}}
        for item in (items or []) if isinstance(item, dict)
    ]


def _require_text(args: Dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' is required")
    return value.strip()


# --- linkup_search -------------------------------------------------------------------------------

def build_search_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    output_type = _choice(args, "output_type", SEARCH_OUTPUT_TYPES, "searchResults")
    payload: Dict[str, Any] = {
        "q": _require_text(args, "query"),
        "depth": _choice(args, "depth", SEARCH_DEPTHS, settings.get("search_depth")),
        "outputType": output_type,
        **_filters(args),
    }
    if output_type == "structured":
        schema = _schema_arg(args.get("structured_output_schema"), "structured_output_schema")
        if schema is None:
            raise ValueError("output_type 'structured' requires structured_output_schema")
        payload["structuredOutputSchema"] = schema
        payload["includeSources"] = True
    if args.get("max_results"):
        payload["maxResults"] = max(1, int(args["max_results"]))
    if args.get("include_images"):
        payload["includeImages"] = True
    return payload


def shape_search_response(payload: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"query": payload["q"], "depth": payload["depth"]}
    if payload["outputType"] == "sourcedAnswer":
        out["answer"] = data.get("answer") or ""
        out["sources"] = _items(data.get("sources"))
    elif payload["outputType"] == "structured":
        out["data"] = data.get("data")
        out["sources"] = _items(data.get("sources"))
    else:
        out["results"] = _items(data.get("results"))
        if not out["results"]:
            out["note"] = "No results. Try rephrasing the query, widening filters, or depth='deep'."
    return out


@_guard
def linkup_search(args: Dict[str, Any]) -> str:
    """Handle ``linkup_search``."""
    payload = build_search_payload(args)
    return _ok(shape_search_response(payload, client.search(payload)))


# --- linkup_fetch --------------------------------------------------------------------------------

def _secret_pattern() -> Optional[Pattern[str]]:
    try:
        from agent.redact import _PREFIX_RE
    except ImportError:
        return None
    return _PREFIX_RE


def _website_block(url: str) -> Optional[str]:
    """The operator's ``website_blocklist`` verdict for *url*; fails open on policy errors like core."""
    try:
        from tools.website_policy import check_website_access
    except ImportError:
        return None
    try:
        block = check_website_access(url)
    except Exception:  # noqa: BLE001
        return None
    return (block.get("message") or f"Blocked by website policy: {url}") if block else None


def check_url_policy(url: str) -> None:
    """The URL checks core ``web_extract`` applies before calling any provider."""
    pattern = _secret_pattern()
    if pattern is not None and any(pattern.search(candidate) for candidate in (url, unquote(url))):
        raise ValueError("Blocked: URL contains what appears to be an API key or token. "
                         "Secrets must not be sent in URLs.")
    blocked = _website_block(url)
    if blocked:
        raise ValueError(blocked)


def build_fetch_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    url = _require_text(args, "url")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("url must be an absolute http(s) URL")
    check_url_policy(url)
    render_js = args.get("render_js")
    payload: Dict[str, Any] = {
        "url": url,
        "renderJs": bool(settings.get("fetch_render_js") if render_js is None else render_js),
    }
    mode = _choice(args, "mode", ("standard", "pro"), None)
    if mode:
        payload["mode"] = mode
    if args.get("extract_images"):
        payload["extractImages"] = True
    schema = _schema_arg(args.get("schema"), "schema")
    if schema is not None:
        payload["schema"] = json.loads(schema)
        if args.get("instructions"):
            payload["instructions"] = str(args["instructions"])
    return payload


def _pages_dir() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()) / "cache" / "linkup"
    except ImportError:
        return Path(tempfile.gettempdir()) / "linkup-hermes"


def save_page(url: str, markdown: str) -> Optional[str]:
    """Write *markdown* to a real Markdown file and return its path (None if unwritable).

    Hermes moves oversized tool results to a file holding the raw JSON — the whole page on one
    line with escaped newlines, which read_file cannot page through. This copy keeps line breaks.
    """
    root = _pages_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - PAGE_FILE_MAX_AGE_SECONDS
        for old in root.glob("*.md"):
            if old.stat().st_mtime < cutoff:
                old.unlink(missing_ok=True)
        path = root / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".md")
        path.write_text(markdown, encoding="utf-8")
        return str(path)
    except OSError:
        return None


def shape_fetch_response(url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"url": url}
    markdown = data.get("markdown") or ""
    if len(markdown) >= PAGE_FILE_MIN_CHARS:
        path = save_page(url, markdown)
        if path:
            out["markdown_file"] = path
            out["total_chars"] = len(markdown)
            out["note"] = ("The full page is below and also saved with line breaks at markdown_file. "
                           "If this result was moved to a file, page through markdown_file with read_file.")
    out.update(data)
    if not out.get("markdown") and data.get("data") is None:
        out["note"] = "The page returned no content. Try render_js=true or mode='pro'."
    return out


@_guard
def linkup_fetch(args: Dict[str, Any]) -> str:
    """Handle ``linkup_fetch``."""
    payload = build_fetch_payload(args)
    data = client.fetch(payload, js_fallback=args.get("render_js") is None and "schema" not in payload)
    return _ok(shape_fetch_response(payload["url"], data))


# --- linkup_research / linkup_research_status ---------------------------------------------------

def build_research_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    output_type = _choice(args, "output_type", RESEARCH_OUTPUT_TYPES, "sourcedAnswer")
    payload: Dict[str, Any] = {
        "q": _require_text(args, "query"),
        "outputType": output_type,
        "reasoningDepth": _choice(args, "reasoning_depth", RESEARCH_DEPTHS,
                                  settings.get("research_reasoning_depth")),
        **_filters(args),
    }
    mode = _choice(args, "mode", RESEARCH_MODES, None)
    if mode:
        payload["mode"] = mode
    if output_type == "structured":
        schema = _schema_arg(args.get("structured_output_schema"), "structured_output_schema")
        if schema is None:
            raise ValueError("output_type 'structured' requires structured_output_schema")
        payload["structuredOutputSchema"] = schema
    return payload


def shape_research_task(task: Dict[str, Any]) -> Dict[str, Any]:
    status = task.get("status") or "unknown"
    out: Dict[str, Any] = {"id": task.get("id"), "status": status}
    if status == "completed":
        output = task.get("output")
        if isinstance(output, dict) and "answer" in output:
            out["answer"] = output.get("answer") or ""
            out["sources"] = _items(output.get("sources"))
        else:
            out["output"] = output
    elif status == "failed":
        out["error"] = task.get("error") or "Research task failed without an error message."
        out["next_step"] = "Report the error; offer to retry with a narrower query or lower reasoning_depth."
    else:
        out["next_step"] = (f"Still running. Call linkup_research_status with id='{task.get('id')}' again. "
                            "Do not answer from memory meanwhile.")
    return out


def _interrupted() -> bool:
    try:
        from tools.interrupt import is_interrupted
    except ImportError:
        return False
    try:
        return bool(is_interrupted())
    except Exception:  # noqa: BLE001
        return False


def wait_for_research(task_id: str, wait_seconds: float,
                      sleep: Callable[[float], None] = time.sleep,
                      clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Poll with backoff (2s → 10s, never faster than 1/s) until terminal, timeout, or interrupt."""
    deadline = clock() + wait_seconds
    interval = 2.0
    task = client.get_research(task_id)
    while task.get("status") not in TERMINAL_STATUSES and clock() < deadline:
        pause = min(interval, max(0.0, deadline - clock()))
        slept = 0.0
        while slept < pause:
            if _interrupted():
                return task
            step = min(1.0, pause - slept)
            sleep(step)
            slept += step
        task = client.get_research(task_id)
        interval = min(interval * 1.5, 10.0)
    return task


@_guard
def linkup_research(args: Dict[str, Any]) -> str:
    """Handle ``linkup_research``."""
    payload = build_research_payload(args)
    task = client.start_research(payload)
    if not task.get("id"):
        raise LinkupError(f"Linkup did not return a research task id: {json.dumps(task)[:300]}")
    out = shape_research_task(task)
    out["reasoning_depth"] = payload["reasoningDepth"]
    out["next_step"] = (f"Research started. Tell the user it takes a few minutes, then call "
                        f"linkup_research_status with id='{task['id']}'.")
    return _ok(out)


@_guard
def linkup_research_status(args: Dict[str, Any]) -> str:
    """Handle ``linkup_research_status``."""
    task_id = _require_text(args, "id")
    if not _UUID_RE.match(task_id):
        raise ValueError(f"id must be the UUID returned by linkup_research (got {task_id!r})")
    raw_wait = args.get("wait_seconds")
    wait = DEFAULT_WAIT_SECONDS if raw_wait is None else max(0, min(int(raw_wait), MAX_WAIT_SECONDS))
    return _ok(shape_research_task(wait_for_research(task_id, wait)))


def check_available() -> bool:
    return client.has_api_key()
