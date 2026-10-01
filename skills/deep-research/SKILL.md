---
name: deep-research
description: "When and how to run Linkup deep research (linkup_research + linkup_research_status): scoping the brief, picking mode and reasoning_depth, polling, and presenting the cited report."
version: 1.0.0
author: Linkup
license: MIT
metadata:
  hermes:
    tags: [Research, Reports, Web, Citations, Linkup]
    related_skills: [linkup:web-search]
---

# Deep research with Linkup

`linkup_research` starts an autonomous agent that investigates the web for minutes, cross-checks claims, and returns a synthesized, cited report.

## Use it only when a deep search is not enough

Reach for research when the user asks for "deep research", an "exhaustive / comprehensive report", a "thorough investigation", or an in-depth comparison of many entities. For everything else, start with `linkup_search` (`depth: deep`). It is faster and cheaper.

Research costs more and takes minutes. **Tell the user what you are about to run and roughly how long it takes before starting.**

## Parameters

- `mode`
  - `answer`: one precise question with one correct answer. The answer is self-verified.
  - `investigate`: one defined entity, covered comprehensively.
  - `research`: broad exploration across many entities or topics.
  - Rule of thumb: a question ending in "?" with one answer → `answer`. "The state of / analysis of" → `research`. One company or person in depth → `investigate`.
- `reasoning_depth`
  - `S` (~2–5 min), `M` (~3–7 min, default for a bounded report), `L` (~5–10 min, market maps and multi-company work), `XL` (~10–20 min).
  - Use `XL` only when the user explicitly wants exhaustive coverage.
- `output_type`
  - `sourcedAnswer` (default) for reports.
  - `structured` only with a `structured_output_schema`.
- `include_domains` / `exclude_domains` / `from_date` / `to_date` when the user constrains sources or time.

## Write a scoped brief

Quality depends much more on the brief than on the parameters. Put these in `query`:

- the angles to cover and the leads to pursue
- the facts to verify and the entities to compare
- constraints: timeframe, geography, exclusions
- the output structure you want (sections, table columns)

## It is asynchronous

1. Call `linkup_research`. It returns an `id` right away.
2. Tell the user it has started and will take a few minutes.
3. Call `linkup_research_status` with that `id`. Each call waits up to `wait_seconds` (default 120) for completion.
4. While `status` is `pending` or `processing`, call it again. Don't give up early, and don't substitute your own knowledge for the pending result.
5. `completed`: the report is in `answer` (with `sources`), or in `output` for structured runs.
6. `failed`: report the `error` verbatim. Offer to retry with a narrower brief or a lower `reasoning_depth`.

If you must stop before it finishes, give the user the task `id` so it can be checked later.

## Present the result

- Lead with the headline finding.
- Keep Linkup's inline citations as `[Title](url)`.
- Flag gaps or conflicting sources that the report mentions.
- End with a `Sources:` list.
- Don't add facts that aren't in the report. If something the user asked for is missing, say so.
