"""Live end-to-end check against the real Linkup API (uses credits).

    LINKUP_API_KEY=... python3 tests/live_smoke.py              # search, fetch, web backend
    LINKUP_API_KEY=... python3 tests/live_smoke.py --research   # also runs a small (S) research task
"""

from __future__ import annotations

import json
import sys
import time

from _load import load_plugin, submodule

load_plugin()
tools = submodule("tools")
client = submodule("client")
provider = submodule("provider").LinkupWebSearchProvider()

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")


def timed(fn, *args):
    start = time.monotonic()
    result = fn(*args)
    return result, f"{time.monotonic() - start:.1f}s"


if not client.has_api_key():
    sys.exit("LINKUP_API_KEY is not set")

out, took = timed(lambda: json.loads(tools.linkup_search({"query": "Who is the CEO of Nous Research?", "depth": "fast"})))
check("linkup_search fast/searchResults", bool(out.get("results")), f"{len(out.get('results') or [])} results, {took}")

out, took = timed(lambda: json.loads(tools.linkup_search(
    {"query": "What is the latest release of Hermes Agent by Nous Research?", "output_type": "sourcedAnswer"})))
check("linkup_search standard/sourcedAnswer", bool(out.get("answer")), f"{(out.get('answer') or out.get('error'))[:90]!r}, {took}")

out, took = timed(lambda: json.loads(tools.linkup_search({
    "query": "Nous Research company facts", "output_type": "structured",
    "structured_output_schema": {"type": "object", "properties": {"ceo": {"type": "string"}, "founded": {"type": "string"}}},
})))
check("linkup_search structured", isinstance(out.get("data"), dict), f"{out.get('data') or out.get('error')}, {took}")

out, took = timed(lambda: json.loads(tools.linkup_fetch({"url": "https://example.com"})))
check("linkup_fetch", "documentation examples" in (out.get("markdown") or ""), f"keys={sorted(out)}, {took}")

out = json.loads(tools.linkup_search({"query": "q", "depth": "nope"}))
check("invalid input returns error", "error" in out, out.get("error", ""))

res, took = timed(provider.search, "Hermes Agent plugin catalog", 3)
check("web backend search()", res.get("success") and len(res["data"]["web"]) > 0,
      f"{len((res.get('data') or {}).get('web') or [])} hits, {took}")

docs, took = timed(provider.extract, ["https://example.com", "https://nousresearch.com"])
check("web backend extract()", len(docs) == 2 and all(d.get("content") for d in docs),
      f"titles={[d.get('title') for d in docs]}, {took}")

check("balance", isinstance(client.balance().get("balance"), (int, float)))

if "--research" in sys.argv:
    start = json.loads(tools.linkup_research({
        "query": "What year was Nous Research founded, and who are its co-founders? Cite primary sources.",
        "mode": "answer", "reasoning_depth": "S"}))
    check("linkup_research start", bool(start.get("id")), str(start.get("id") or start.get("error")))
    status = {"status": "pending"}
    began = time.monotonic()
    while start.get("id") and status.get("status") not in ("completed", "failed") and time.monotonic() - began < 900:
        status = json.loads(tools.linkup_research_status({"id": start["id"], "wait_seconds": 120}))
        print(f"      … {status.get('status')} after {time.monotonic() - began:.0f}s")
    check("linkup_research_status completed", status.get("status") == "completed",
          (status.get("answer") or status.get("error") or "")[:160].replace("\n", " "))

sys.exit(1 if failures else 0)
