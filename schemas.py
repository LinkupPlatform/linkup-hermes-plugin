"""Tool schemas — what the model sees."""

_DOMAIN_FILTERS = {
    "include_domains": {
        "type": "array", "items": {"type": "string"},
        "description": "Only return results from these domains (max 100), e.g. [\"sec.gov\"]. "
                       "Use only when the user names trusted sources — never invent domains.",
    },
    "exclude_domains": {
        "type": "array", "items": {"type": "string"},
        "description": "Drop results from these domains.",
    },
    "from_date": {
        "type": "string",
        "description": "Only content published on or after this date (YYYY-MM-DD). "
                       "More reliable than writing 'recent' in the query.",
    },
    "to_date": {
        "type": "string",
        "description": "Only content published on or before this date (YYYY-MM-DD).",
    },
}

LINKUP_SEARCH = {
    "name": "linkup_search",
    "description": (
        "Search the live web with Linkup and get fresh, citable results. Use for anything current or "
        "verifiable: news, prices, people, companies, docs, facts that may have changed since training. "
        "Write the query as a retrieval instruction (what to find, where, which fields), not keywords.\n"
        "depth: 'fast' = sub-second, one keyword-shaped fact; 'standard' (default) = most questions, can "
        "scrape a URL given in the query; 'deep' = multi-step (find a page THEN scrape it), comparisons, "
        "multi-source validation (often 30-120s — use only when standard is not enough). 'flash' = lowest "
        "latency, no LLM.\n"
        "output_type: 'searchResults' (default) = ranked sources with content to synthesize yourself; "
        "'sourcedAnswer' = a written answer plus sources; 'structured' = JSON matching "
        "structured_output_schema (required for that mode).\n"
        "Always cite the returned URLs; never invent URLs. If you already have the exact URL, use "
        "linkup_fetch instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language retrieval instruction, e.g. \"Find Stripe's latest funding "
                               "round amount and date\" or \"Find the pricing page for Vercel. Scrape it. "
                               "Extract plan names and prices.\"",
            },
            "depth": {"type": "string", "enum": ["flash", "fast", "standard", "deep"],
                      "description": "Search depth (default: standard)."},
            "output_type": {"type": "string", "enum": ["searchResults", "sourcedAnswer", "structured"],
                            "description": "Response format (default: searchResults)."},
            "structured_output_schema": {
                "type": "object",
                "description": "JSON Schema (root type 'object') for output_type='structured'.",
            },
            "max_results": {"type": "integer", "minimum": 1,
                            "description": "Cap the number of results. Omit to get everything Linkup "
                                           "returns (usually 20)."},
            "include_images": {"type": "boolean", "description": "Also return relevant images."},
            **_DOMAIN_FILTERS,
        },
        "required": ["query"],
    },
}

LINKUP_FETCH = {
    "name": "linkup_fetch",
    "description": (
        "Fetch one known URL with Linkup and return the page as clean Markdown (HTML pages and PDFs). "
        "Faster and cheaper than searching when you already have the exact URL. JavaScript rendering is "
        "on by default. Set mode='pro' for sites that block scrapers. Pass a JSON 'schema' (and optional "
        "'instructions') to also get typed fields extracted into 'data'. Cannot log into sites such as "
        "LinkedIn — use linkup_search for those."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL to fetch."},
            "render_js": {"type": "boolean",
                          "description": "Execute client-side JavaScript first (default true). Turn off only "
                                         "for known-static pages where speed matters."},
            "mode": {"type": "string", "enum": ["standard", "pro"],
                     "description": "'pro' uses enhanced anti-bot retrieval for difficult sites."},
            "extract_images": {"type": "boolean", "description": "Also return images found on the page."},
            "schema": {"type": "object",
                       "description": "Optional JSON Schema (root type 'object'); matching fields are "
                                      "returned under 'data'."},
            "instructions": {"type": "string",
                             "description": "Natural-language extraction guidance (only with 'schema')."},
        },
        "required": ["url"],
    },
}

LINKUP_RESEARCH = {
    "name": "linkup_research",
    "description": (
        "Start a Linkup deep-research task: an autonomous agent that investigates the web for minutes, "
        "cross-checks sources, and returns a cited report. ONLY use when the user asks for deep research, "
        "an exhaustive/comprehensive report, or a multi-entity comparison that one linkup_search (depth="
        "'deep') cannot cover. It is asynchronous: this call returns a task id — then call "
        "linkup_research_status with that id until status is 'completed' or 'failed'. Tell the user it "
        "will take a few minutes. Costs more than search.\n"
        "mode: 'answer' = one precise question; 'investigate' = one entity in depth; 'research' = broad, "
        "many entities. reasoning_depth: S (~2-5 min), M (~3-7 min, good default for bounded reports), "
        "L (~5-10 min), XL (~10-20 min, only when exhaustive coverage is requested)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A well-scoped research brief: angles to cover, entities to compare, facts to "
                               "verify, constraints, and the output structure you want.",
            },
            "mode": {"type": "string", "enum": ["answer", "investigate", "research"],
                     "description": "Investigation style. Omit to let Linkup choose."},
            "reasoning_depth": {"type": "string", "enum": ["S", "M", "L", "XL"],
                                "description": "Effort / latency budget (default M)."},
            "output_type": {"type": "string", "enum": ["sourcedAnswer", "structured"],
                            "description": "'sourcedAnswer' (default) for a cited report, 'structured' for "
                                           "JSON matching structured_output_schema."},
            "structured_output_schema": {"type": "object",
                                         "description": "JSON Schema for output_type='structured'."},
            **_DOMAIN_FILTERS,
        },
        "required": ["query"],
    },
}

LINKUP_RESEARCH_STATUS = {
    "name": "linkup_research_status",
    "description": (
        "Check a Linkup research task started with linkup_research. Waits up to wait_seconds for it to "
        "finish, then returns status ('pending', 'processing', 'completed', 'failed') and, when completed, "
        "the cited report in 'output'. If still running, call again with the same id — do not answer from "
        "memory while the task is pending."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Task id returned by linkup_research."},
            "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 300,
                             "description": "How long to wait for completion in this call (default 120)."},
        },
        "required": ["id"],
    },
}
