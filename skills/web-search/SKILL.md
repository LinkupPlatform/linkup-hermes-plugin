---
name: web-search
description: "How to get accurate, cited web answers with linkup_search and linkup_fetch: picking depth and output_type, writing retrieval-plan queries, filters, and citation rules."
version: 1.0.1
author: Linkup
license: MIT
metadata:
  hermes:
    tags: [Web, Search, Research, Citations, Linkup]
    related_skills: [linkup:deep-research]
---

# Web search with Linkup

Use `linkup_search` for anything current or verifiable. Use `linkup_fetch` when you already have the exact URL.

A Linkup query is an **instruction to a retrieval system**, not a question to answer. Say what to find, where to look, and which fields you need. Then do the synthesis yourself.

## Choose the request shape first

Answer three questions, in order:

1. **What inputs do I have?** A URL → `linkup_fetch` it, don't search for it. Only a name or topic → search.
2. **Where does the data live?** One fact that appears in snippets (CEO, price, date) → `depth: fast`. A few facts across snippets → `standard`. Data on full pages (tables, specs, pricing) → it must be scraped.
3. **Do I need to chain steps?** Must find a URL *then* scrape it → `deep`. Everything parallel → `standard`. Unsure → `deep`.

| depth | Speed | Use for |
|---|---|---|
| `flash` | fastest | latency-critical keyword lookups |
| `fast` | ~1s | one keyword-shaped fact |
| `standard` (default) | ~1–3s | most questions; can scrape a URL **given in the query** |
| `deep` | ~30–120s | find-then-scrape, comparisons, multi-source validation |

`standard` cannot discover a URL and scrape it in the same call. Use `deep` ("First find the official pricing page, then scrape it") or split into search + `linkup_fetch`.

## Output type

- `searchResults` (default): ranked sources with content. Best when you will synthesize or chain steps.
- `sourcedAnswer`: a written answer plus sources. Best for quick user-facing answers.
- `structured`: JSON that matches `structured_output_schema` (root `"type": "object"`). Use it when data feeds code, a CRM, or a table.

## Query patterns

```
company only · need CEO           → depth=fast     "Who is the CEO of {company}?"
company only · latest funding     → depth=standard "Find {company}'s latest funding round amount and date"
company only · pricing (full page)→ depth=deep     "Find the pricing page for {company}. Scrape it. Extract plan names, prices, and features."
known URL · pricing               → linkup_fetch(url) — or depth=standard "Scrape {url}. Extract plan names and prices."
```

- Write natural-language instructions, not keyword soup. Name the entity, version, year, and fields.
- Disambiguate names: `"Clause AI" legal-tech startup`.
- For broad topics, run two or three searches on different facets rather than rewording one.
- Use `from_date` / `to_date` for time-bound questions instead of writing "recent".
- Use `include_domains` / `exclude_domains` only when the user names sources. Never invent domains.

## linkup_fetch

- Returns clean Markdown for HTML pages and PDFs. `render_js` is on by default. Keep it on unless the page is static and speed matters.
- Use `mode: "pro"` for sites that block scrapers.
- Pass `schema` (+ `instructions`) to get typed fields back in `data`.
- It cannot log in to sites (e.g. LinkedIn). Use `linkup_search` for those.
- Pages come back whole. Pages over 20k characters are also saved as Markdown at `markdown_file`. If Hermes moved the result to a file, page through `markdown_file` with `read_file` (offset/limit) or `search_files`, not the moved JSON file.

## Citations

1. Lead with the direct answer.
2. Back it with specific facts, numbers, and dates.
3. Cite inline as `[Title](url)`, using only URLs returned by the tools.
4. End with a `Sources:` list.

Never invent or guess a URL. If the results don't support a claim, say so. Don't fill the gap from memory.
