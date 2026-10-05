"""Linkup plugin for Hermes Agent — live web search, page fetch, and deep research.

Registers four tools (``linkup_search``, ``linkup_fetch``, ``linkup_research``,
``linkup_research_status``), a ``linkup`` web backend for the built-in ``web_search`` /
``web_extract`` tools, the ``/linkup`` slash command, the ``hermes linkup`` CLI, and
bundled skills.
"""

from __future__ import annotations

__version__ = "1.0.1"

import logging
from pathlib import Path

from . import commands, schemas, settings, tools

logger = logging.getLogger(__name__)

TOOLSET = "linkup"
EMOJI = "🔗"

_TOOLS = (
    (schemas.LINKUP_SEARCH, tools.linkup_search, "Live web search with citations (Linkup)."),
    (schemas.LINKUP_FETCH, tools.linkup_fetch, "Fetch a URL as clean Markdown (Linkup)."),
    (schemas.LINKUP_RESEARCH, tools.linkup_research, "Start a multi-minute deep-research task (Linkup)."),
    (schemas.LINKUP_RESEARCH_STATUS, tools.linkup_research_status, "Poll a Linkup research task."),
)


def _register_web_provider(ctx) -> None:
    try:
        from .provider import LinkupWebSearchProvider
    except ImportError as exc:  # Hermes without the web provider ABC: tools still work
        logger.debug("Linkup web backend unavailable on this Hermes: %s", exc)
        return
    ctx.register_web_search_provider(LinkupWebSearchProvider())


def _register_skills(ctx) -> None:
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.is_dir():
        return
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            ctx.register_skill(child.name, skill_md)


def register(ctx) -> None:
    settings.bind(ctx)
    for schema, handler, description in _TOOLS:
        ctx.register_tool(
            name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler,
            check_fn=tools.check_available, requires_env=["LINKUP_API_KEY"],
            description=description, emoji=EMOJI,
        )
    _register_web_provider(ctx)
    ctx.register_command("linkup", commands.slash_command,
                         description="Linkup status, balance, and quick search",
                         args_hint="[status|balance|search <query>]")
    ctx.register_cli_command(
        name="linkup", help="Linkup web search: status, search, and web-backend setup",
        setup_fn=commands.register_cli, handler_fn=commands.cli_command,
        description="Check your Linkup key and credits, run searches, and route Hermes' built-in "
                    "web tools through Linkup.",
    )
    _register_skills(ctx)
