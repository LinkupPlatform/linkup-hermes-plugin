"""``/linkup`` slash command and ``hermes linkup`` CLI."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

from . import __version__, client, tools
from .client import LinkupError

SLASH_USAGE = (
    "Usage: /linkup [status | balance | search <query> | help]\n"
    "  status          API key, credit balance, and which web backend Hermes uses\n"
    "  balance         Remaining Linkup credits\n"
    "  search <query>  Quick cited answer (standard depth)"
)


def _web_backends() -> Dict[str, Optional[str]]:
    try:
        from hermes_cli.config import load_config_readonly
        web = (load_config_readonly() or {}).get("web") or {}
    except Exception:  # noqa: BLE001
        web = {}
    if not isinstance(web, dict):
        web = {}
    return {k: web.get(k) for k in ("backend", "search_backend", "extract_backend")}


def status_lines() -> List[str]:
    lines = [f"Linkup plugin v{__version__}"]
    if not client.has_api_key():
        lines.append(f"  API key : NOT SET — get one at {client.SIGNUP_URL}, then "
                     f"`hermes config set {client.KEY_ENV} <key>`")
        return lines
    lines.append(f"  API key : set ({client.KEY_ENV})")
    try:
        lines.append(f"  Balance : {client.balance().get('balance')} credits")
    except LinkupError as exc:
        lines.append(f"  Balance : unavailable — {exc}")
    backends = _web_backends()
    search = backends["search_backend"] or backends["backend"]
    extract = backends["extract_backend"] or backends["backend"]
    lines.append(f"  web_search backend  : {search or 'auto'}")
    lines.append(f"  web_extract backend : {extract or 'auto'}")
    if "linkup" not in (search, extract):
        lines.append("  Tip: `hermes linkup use-as-web-backend` routes Hermes' built-in web tools through Linkup.")
    return lines


def quick_answer(query: str) -> str:
    raw = json.loads(tools.linkup_search({"query": query, "output_type": "sourcedAnswer"}))
    if "error" in raw:
        return f"Linkup error: {raw['error']}"
    parts = [raw.get("answer") or "(no answer)"]
    sources = raw.get("sources") or []
    if sources:
        parts.append("\nSources:")
        parts.extend(f"- {s.get('name') or s.get('url')} — {s.get('url')}" for s in sources)
    return "\n".join(parts)


def slash_command(raw_args: str) -> str:
    text = (raw_args or "").strip()
    sub, _, rest = text.partition(" ")
    sub = sub.lower()
    try:
        if sub in ("", "status"):
            return "\n".join(status_lines())
        if sub == "balance":
            return f"Linkup balance: {client.balance().get('balance')} credits"
        if sub == "search":
            return quick_answer(rest) if rest.strip() else "Usage: /linkup search <query>"
        if sub == "help":
            return SLASH_USAGE
        return f"Unknown subcommand '{sub}'.\n{SLASH_USAGE}"
    except LinkupError as exc:
        return f"Linkup error: {exc}"


# --- hermes linkup ... ---------------------------------------------------------------------------

def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="linkup_command")
    subs.add_parser("status", help="Show API key, credit balance, and web backend selection")
    p_search = subs.add_parser("search", help="Run a Linkup search from the terminal")
    p_search.add_argument("query", nargs="+", help="Search query")
    p_search.add_argument("--depth", choices=tools.SEARCH_DEPTHS, default=None)
    p_search.add_argument("--output-type", choices=tools.SEARCH_OUTPUT_TYPES[:2], default="sourcedAnswer")
    p_search.add_argument("--json", action="store_true", help="Print the raw tool JSON")
    p_use = subs.add_parser("use-as-web-backend",
                            help="Route Hermes' built-in web_search/web_extract through Linkup")
    scope = p_use.add_mutually_exclusive_group()
    scope.add_argument("--search-only", action="store_true", help="Only web.search_backend")
    scope.add_argument("--extract-only", action="store_true", help="Only web.extract_backend")
    subparser.set_defaults(func=cli_command)


def _set_config(key: str, value: str) -> None:
    from hermes_cli.config import set_config_value
    set_config_value(key, value)


def cli_command(args: argparse.Namespace) -> int:
    sub = getattr(args, "linkup_command", None)
    if sub in (None, "status"):
        print("\n".join(status_lines()))
        return 0 if client.has_api_key() else 1
    if sub == "search":
        payload: Dict[str, Any] = {"query": " ".join(args.query), "output_type": args.output_type}
        if args.depth:
            payload["depth"] = args.depth
        if args.json:
            print(tools.linkup_search(payload))
            return 0
        if args.output_type == "sourcedAnswer" and not args.depth:
            print(quick_answer(payload["query"]))
            return 0
        raw = json.loads(tools.linkup_search(payload))
        if "error" in raw:
            print(f"Linkup error: {raw['error']}")
            return 1
        if "answer" in raw:
            print(raw["answer"])
        for i, r in enumerate(raw.get("results") or raw.get("sources") or [], 1):
            print(f"{i}. {r.get('name') or r.get('url')}\n   {r.get('url')}")
        return 0
    if sub == "use-as-web-backend":
        keys = (["web.search_backend"] if args.search_only else
                ["web.extract_backend"] if args.extract_only else ["web.backend"])
        for key in keys:
            _set_config(key, "linkup")
        if not client.has_api_key():
            print(f"Note: {client.KEY_ENV} is not set yet — run `hermes config set {client.KEY_ENV} <key>`.")
        return 0
    print("usage: hermes linkup {status,search,use-as-web-backend}")
    return 2
