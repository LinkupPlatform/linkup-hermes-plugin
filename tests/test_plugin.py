"""Offline tests — no network, no Hermes required. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from _load import PLUGIN_DIR, RecordingContext, load_plugin, submodule

plugin = load_plugin()
client = submodule("client")
tools = submodule("tools")
provider_mod = submodule("provider")
settings = submodule("settings")
commands = submodule("commands")

TASK_ID = "0b6f3c1e-8d2a-4c3b-9f1e-2a7d5e6f8a90"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(status: int, body: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.linkup.so/v1/x", status, "err", {},
                                  io.BytesIO(json.dumps(body).encode()))


class KeyedTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"LINKUP_API_KEY": "test-key"})
        patcher.start()
        self.addCleanup(patcher.stop)
        settings.bind(None)


class RegistrationTests(unittest.TestCase):
    def test_register_matches_manifest(self):
        ctx = RecordingContext()
        plugin.register(ctx)
        manifest = (PLUGIN_DIR / "plugin.yaml").read_text()
        names = [t["name"] for t in ctx.tools]
        self.assertEqual(names, ["linkup_search", "linkup_fetch", "linkup_research", "linkup_research_status"])
        for name in names:
            self.assertIn(f"- {name}", manifest)
        self.assertTrue(all(t["toolset"] == "linkup" for t in ctx.tools))
        self.assertTrue(all(t["schema"]["name"] == t["name"] for t in ctx.tools))
        self.assertEqual([p.name for p in ctx.providers], ["linkup"])
        self.assertEqual(ctx.commands, ["linkup"])
        self.assertEqual(ctx.cli_commands, ["linkup"])
        self.assertEqual(ctx.skills, ["deep-research", "web-search"])

    def test_version_matches_manifest(self):
        self.assertIn(f"version: {plugin.__version__}\n", (PLUGIN_DIR / "plugin.yaml").read_text())

    def test_check_fn_tracks_key(self):
        with mock.patch.dict(os.environ, {"LINKUP_API_KEY": ""}):
            self.assertFalse(tools.check_available())
        with mock.patch.dict(os.environ, {"LINKUP_API_KEY": "k"}):
            self.assertTrue(tools.check_available())


class ClientTests(KeyedTestCase):
    def test_request_sends_auth_and_json(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b'{"ok": true}')) as urlopen:
            self.assertEqual(client.request("POST", "/search", {"q": "x"}), {"ok": True})
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.linkup.so/v1/search")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
        self.assertTrue(req.get_header("User-agent").startswith("linkup-hermes-plugin/"))
        self.assertEqual(json.loads(req.data), {"q": "x"})

    def test_missing_key(self):
        with mock.patch.dict(os.environ, {"LINKUP_API_KEY": ""}):
            with self.assertRaises(client.LinkupError) as cm:
                client.request("GET", "/credits/balance")
        self.assertIn("LINKUP_API_KEY is not set", str(cm.exception))

    def test_error_messages(self):
        cases = {
            401: "rejected the API key",
            402: "out of credits",
            429: "rate limit",
        }
        for status, expected in cases.items():
            with mock.patch("urllib.request.urlopen", side_effect=http_error(status, {})):
                with self.assertRaises(client.LinkupError) as cm:
                    client.request("POST", "/search", {})
            self.assertIn(expected, str(cm.exception))

    def test_validation_details_surface(self):
        body = {"error": {"code": "VALIDATION_ERROR", "message": "Validation failed",
                          "details": [{"field": "depth", "message": "depth must be one of ..."}]}}
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400, body)):
            with self.assertRaises(client.LinkupError) as cm:
                client.request("POST", "/search", {})
        self.assertIn("depth: depth must be one of", str(cm.exception))


class SearchToolTests(KeyedTestCase):
    def run_search(self, args, response):
        with mock.patch.object(client, "request", return_value=response) as req:
            out = json.loads(tools.linkup_search(args))
        return out, (req.call_args[0][2] if req.called else None)

    def test_defaults_and_shaping(self):
        response = {"results": [{"type": "text", "name": "A", "url": "https://a", "content": "x" * 5000,
                                 "favicon": "f"}]}
        out, payload = self.run_search({"query": " hi "}, response)
        self.assertEqual(payload, {"q": "hi", "depth": "standard", "outputType": "searchResults"})
        self.assertEqual(out["results"], response["results"])

    def test_max_results_passed_through_uncapped(self):
        _, payload = self.run_search({"query": "q", "max_results": 100}, {"results": []})
        self.assertEqual(payload["maxResults"], 100)

    def test_all_results_and_sources_kept(self):
        many = [{"type": "text", "name": f"R{i}", "url": f"https://r{i}", "content": "c" * 20000} for i in range(40)]
        out, _ = self.run_search({"query": "q"}, {"results": many})
        self.assertEqual(out["results"], many)
        sources = [{"name": f"S{i}", "url": f"https://s{i}", "snippet": "s" * 5000, "favicon": "f"} for i in range(30)]
        out, _ = self.run_search({"query": "q", "output_type": "sourcedAnswer"}, {"answer": "a", "sources": sources})
        self.assertEqual(out["sources"], sources)

    def test_filters_and_sourced_answer(self):
        out, payload = self.run_search(
            {"query": "q", "depth": "deep", "output_type": "sourcedAnswer", "include_domains": ["sec.gov"],
             "from_date": "2026-01-01"},
            {"answer": "42", "sources": [{"name": "S", "url": "https://s", "snippet": "sn"}]},
        )
        self.assertEqual(payload["includeDomains"], ["sec.gov"])
        self.assertEqual(payload["fromDate"], "2026-01-01")
        self.assertNotIn("maxResults", payload)
        self.assertEqual(out["answer"], "42")
        self.assertEqual(out["sources"], [{"name": "S", "url": "https://s", "snippet": "sn"}])

    def test_html_entities_decoded(self):
        out, _ = self.run_search({"query": "q"}, {"results": [
            {"type": "text", "name": "FAQ &amp; What&#039;s New", "url": "https://a", "content": "a &lt; b"}]})
        self.assertEqual(out["results"][0]["name"], "FAQ & What's New")
        self.assertEqual(out["results"][0]["content"], "a < b")

    def test_structured_requires_schema(self):
        out, payload = self.run_search({"query": "q", "output_type": "structured"}, {})
        self.assertIn("requires structured_output_schema", out["error"])
        self.assertIsNone(payload)

    def test_structured_schema_serialized(self):
        schema = {"type": "object", "properties": {"ceo": {"type": "string"}}}
        out, payload = self.run_search(
            {"query": "q", "output_type": "structured", "structured_output_schema": schema},
            {"data": {"ceo": "X"}, "sources": []},
        )
        self.assertEqual(json.loads(payload["structuredOutputSchema"]), schema)
        self.assertEqual(out["data"], {"ceo": "X"})

    def test_invalid_inputs_return_errors(self):
        for args in ({}, {"query": "q", "depth": "ultra"}, {"query": "q", "from_date": "yesterday"}):
            out, _ = self.run_search(args, {})
            self.assertIn("error", out)

    def test_setting_changes_default_depth(self):
        settings.bind(RecordingContext({"search_depth": "fast"}))
        _, payload = self.run_search({"query": "q"}, {"results": []})
        self.assertEqual(payload["depth"], "fast")

    def test_api_error_is_returned_not_raised(self):
        with mock.patch.object(client, "request", side_effect=client.LinkupError("boom")):
            self.assertEqual(json.loads(tools.linkup_search({"query": "q"})), {"error": "boom"})


class FetchToolTests(KeyedTestCase):
    def setUp(self):
        super().setUp()
        self._pages = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(tools, "_pages_dir", return_value=Path(self._pages.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._pages.cleanup)

    def test_payload_and_full_page(self):
        images = [{"url": f"https://i/{i}"} for i in range(50)]
        page = "\n".join(f"line {i}" for i in range(60000))
        response = {"markdown": page, "images": images, "favicon": "https://f"}
        with mock.patch.object(client, "request", return_value=response) as req:
            out = json.loads(tools.linkup_fetch({"url": "https://x.com", "mode": "pro", "extract_images": True}))
        self.assertEqual(req.call_args[0][2],
                         {"url": "https://x.com", "renderJs": True, "mode": "pro", "extractImages": True})
        self.assertEqual(out["markdown"], page)
        self.assertEqual(out["images"], images)
        self.assertEqual(out["favicon"], "https://f")
        self.assertEqual(list(out)[:3], ["url", "markdown_file", "total_chars"])
        self.assertEqual(Path(out["markdown_file"]).read_text(encoding="utf-8"), page)

    def test_small_page_not_saved(self):
        with mock.patch.object(client, "request", return_value={"markdown": "x" * 5000}):
            out = json.loads(tools.linkup_fetch({"url": "https://x.com"}))
        self.assertNotIn("markdown_file", out)
        self.assertEqual(os.listdir(self._pages.name), [])

    def test_schema_extraction(self):
        schema = {"type": "object", "properties": {"title": {"type": "string"}}}
        with mock.patch.object(client, "request", return_value={"markdown": "# T", "data": {"title": "T"}}) as req:
            out = json.loads(tools.linkup_fetch({"url": "https://x.com", "schema": schema, "instructions": "i"}))
        self.assertEqual(req.call_args[0][2]["schema"], schema)
        self.assertEqual(req.call_args[0][2]["instructions"], "i")
        self.assertEqual(out["data"], {"title": "T"})

    def test_js_fallback_keeps_longer_static_page(self):
        pages = {True: {"markdown": "# //Error"}, False: {"markdown": "real content " * 200}}
        with mock.patch.object(client, "request", side_effect=lambda m, p, payload, timeout: pages[payload["renderJs"]]) as req:
            out = json.loads(tools.linkup_fetch({"url": "https://x.com"}))
        self.assertEqual(req.call_count, 2)
        self.assertTrue(out["markdown"].startswith("real content"))

    def test_no_fallback_when_render_js_explicit(self):
        with mock.patch.object(client, "request", return_value={"markdown": "short"}) as req:
            json.loads(tools.linkup_fetch({"url": "https://x.com", "render_js": True}))
        self.assertEqual(req.call_count, 1)

    def test_rejects_non_http_url(self):
        self.assertIn("error", json.loads(tools.linkup_fetch({"url": "file:///etc/passwd"})))


class ResearchToolTests(KeyedTestCase):
    def test_start(self):
        with mock.patch.object(client, "request", return_value={"id": TASK_ID, "status": "pending"}) as req:
            out = json.loads(tools.linkup_research({"query": "compare", "mode": "research"}))
        self.assertEqual(req.call_args[0][2],
                         {"q": "compare", "outputType": "sourcedAnswer", "reasoningDepth": "M", "mode": "research"})
        self.assertEqual(out["id"], TASK_ID)
        self.assertIn("linkup_research_status", out["next_step"])

    def test_wait_polls_until_complete(self):
        responses = iter([
            {"id": TASK_ID, "status": "pending"},
            {"id": TASK_ID, "status": "processing"},
            {"id": TASK_ID, "status": "completed",
             "output": {"answer": "report", "sources": [{"name": "S", "url": "https://s", "snippet": ""}]}},
        ])
        now = [0.0]

        def sleep(seconds):
            now[0] += seconds

        with mock.patch.object(client, "get_research", side_effect=lambda _id: next(responses)):
            task = tools.wait_for_research(TASK_ID, 60, sleep=sleep, clock=lambda: now[0])
        self.assertEqual(tools.shape_research_task(task)["answer"], "report")
        self.assertGreaterEqual(now[0], 2.0)

    def test_wait_respects_deadline(self):
        now = [0.0]
        with mock.patch.object(client, "get_research", return_value={"id": TASK_ID, "status": "processing"}) as get:
            task = tools.wait_for_research(TASK_ID, 5, sleep=lambda s: now.__setitem__(0, now[0] + s),
                                           clock=lambda: now[0])
        self.assertEqual(task["status"], "processing")
        self.assertLessEqual(now[0], 5.0)
        self.assertGreater(get.call_count, 1)

    def test_status_zero_wait_and_failure(self):
        with mock.patch.object(client, "get_research", return_value={"id": TASK_ID, "status": "failed", "error": "x"}):
            out = json.loads(tools.linkup_research_status({"id": TASK_ID, "wait_seconds": 0}))
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "x")

    def test_status_rejects_bad_id(self):
        self.assertIn("error", json.loads(tools.linkup_research_status({"id": "../../etc"})))


class ProviderTests(KeyedTestCase):
    def setUp(self):
        super().setUp()
        self.provider = provider_mod.LinkupWebSearchProvider()

    def test_identity(self):
        self.assertEqual(self.provider.name, "linkup")
        self.assertTrue(self.provider.is_available())
        self.assertTrue(self.provider.supports_search())
        self.assertTrue(self.provider.supports_extract())
        self.assertEqual(self.provider.get_setup_schema()["env_vars"][0]["key"], "LINKUP_API_KEY")

    def test_search_envelope(self):
        response = {"results": [
            {"type": "text", "name": "A", "url": "https://a", "content": "c" * 20000},
            {"type": "image", "name": "img", "url": "https://i"},
        ]}
        with mock.patch.object(client, "request", return_value=response) as req:
            out = self.provider.search("q", limit=100)
        self.assertEqual(req.call_args[0][2]["maxResults"], 100)
        self.assertEqual(out, {"success": True, "data": {"web": [
            {"title": "A", "url": "https://a", "description": "c" * 20000, "position": 1}]}})

    def test_extract_full_page(self):
        with mock.patch.object(client, "request", return_value={"markdown": "# T\n" + "b" * 300000}):
            docs = self.provider.extract(["https://x"])
        self.assertEqual(len(docs[0]["content"]), 300004)

    def test_search_failure_envelope(self):
        with mock.patch.object(client, "request", side_effect=client.LinkupError("nope")):
            self.assertEqual(self.provider.search("q"), {"success": False, "error": "nope"})

    def test_extract_mixed_results(self):
        def fake(method, path, payload, timeout):
            if "bad" in payload["url"]:
                raise client.LinkupError("blocked")
            return {"markdown": "# Hello\n\nbody"}

        with mock.patch.object(client, "request", side_effect=fake):
            docs = self.provider.extract(["https://good", "https://bad"])
        self.assertEqual(docs[0]["title"], "Hello")
        self.assertEqual(docs[0]["raw_content"], docs[0]["content"])
        self.assertEqual(docs[1]["error"], "blocked")


class CommandTests(KeyedTestCase):
    def test_slash_status_and_balance(self):
        with mock.patch.object(client, "request", return_value={"balance": 12.5}):
            self.assertIn("Balance : 12.5", commands.slash_command(""))
            self.assertEqual(commands.slash_command("balance"), "Linkup balance: 12.5 credits")

    def test_slash_search(self):
        response = {"answer": "Paris", "sources": [{"name": "Wiki", "url": "https://w", "snippet": ""}]}
        with mock.patch.object(client, "request", return_value=response):
            out = commands.slash_command("search capital of France")
        self.assertIn("Paris", out)
        self.assertIn("https://w", out)

    def test_slash_unknown(self):
        self.assertIn("Usage", commands.slash_command("wat"))

    def test_status_without_key(self):
        with mock.patch.dict(os.environ, {"LINKUP_API_KEY": ""}):
            self.assertIn("NOT SET", commands.slash_command("status"))


if __name__ == "__main__":
    unittest.main()
