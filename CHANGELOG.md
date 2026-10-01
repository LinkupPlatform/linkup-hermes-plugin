# Changelog

## 1.0.0

- `linkup_search`, `linkup_fetch`, `linkup_research`, `linkup_research_status` tools.
- `linkup` web backend for Hermes' built-in `web_search` / `web_extract`.
- `/linkup` slash command and `hermes linkup` CLI.
- Bundled `linkup:web-search` and `linkup:deep-research` skills.
- Desktop settings form via `config_schema`.
- Untruncated responses: all results, sources, fields, images, and full page Markdown.
- Large fetched pages are also saved as pageable Markdown files (`markdown_file`), pruned after 24 hours.
