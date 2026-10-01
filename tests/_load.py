"""Load the plugin directory as a package the way Hermes' PluginManager does."""

from __future__ import annotations

import abc
import importlib.util
import os
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PACKAGE = "linkup_hermes_plugin_under_test"


def _ensure_web_provider_abc() -> None:
    """Use Hermes' real ABC when importable; otherwise install a faithful stub."""
    try:
        import agent.web_search_provider  # noqa: F401
        return
    except ImportError:
        pass

    class WebSearchProvider(abc.ABC):
        @property
        @abc.abstractmethod
        def name(self) -> str: ...

        @property
        def display_name(self) -> str:
            return self.name

        @abc.abstractmethod
        def is_available(self) -> bool: ...

        def supports_search(self) -> bool:
            return True

        def supports_extract(self) -> bool:
            return False

    def get_provider_env(name: str) -> str:
        return os.environ.get(name, "").strip()

    agent_pkg = sys.modules.setdefault("agent", types.ModuleType("agent"))
    module = types.ModuleType("agent.web_search_provider")
    module.WebSearchProvider = WebSearchProvider
    module.get_provider_env = get_provider_env
    agent_pkg.web_search_provider = module
    sys.modules["agent.web_search_provider"] = module


def load_plugin():
    _ensure_web_provider_abc()
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]
    spec = importlib.util.spec_from_file_location(
        PACKAGE, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def submodule(name: str):
    load_plugin()
    return importlib.import_module(f"{PACKAGE}.{name}")


class RecordingContext:
    """Minimal stand-in for PluginContext that records registrations."""

    def __init__(self, config=None):
        self.config = config or {}
        self.tools, self.providers, self.commands, self.cli_commands, self.skills = [], [], [], [], []

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools.append({"name": name, "toolset": toolset, "schema": schema, "handler": handler, **kwargs})

    def register_web_search_provider(self, provider):
        self.providers.append(provider)

    def register_command(self, name, handler, **kwargs):
        self.commands.append(name)

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli_commands.append(name)

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills.append(name)
