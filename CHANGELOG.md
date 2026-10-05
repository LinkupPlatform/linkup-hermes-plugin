# Changelog

## 1.0.1

Fixes from the Hermes plugin-catalog review ([#1](https://github.com/LinkupPlatform/linkup-hermes-plugin/issues/1)):

- The `linkup` backend's `web_extract` now works on multiplexed gateways: fetch workers inherit the caller's profile scope.
- `linkup_fetch` refuses URLs that carry credentials and honors `website_blocklist`, like core `web_extract`.
- `web_extract` stays within Hermes' `web.extract_timeout`: one deadline per batch, finished pages are kept, and the JS fallback is skipped when time is short.
- The JS fallback only fires on broken renders (near-empty pages or "enable JavaScript" walls), so short pages are no longer fetched twice.
- `hermes linkup use-as-web-backend` also switches `web.search_backend` / `web.extract_backend` when they name another provider.
- Invalid depth settings fall back to the default instead of failing tool calls.
- Unexpected tool errors are logged.
- Documented `LINKUP_API_BASE_URL`.

## 1.0.0

- `linkup_search`, `linkup_fetch`, `linkup_research`, `linkup_research_status` tools.
- `linkup` web backend for Hermes' built-in `web_search` / `web_extract`.
- `/linkup` slash command and `hermes linkup` CLI.
- Bundled `linkup:web-search` and `linkup:deep-research` skills.
- Desktop settings form via `config_schema`.
- Untruncated responses: all results, sources, fields, images, and full page Markdown.
- Large fetched pages are also saved as pageable Markdown files (`markdown_file`), pruned after 24 hours.
