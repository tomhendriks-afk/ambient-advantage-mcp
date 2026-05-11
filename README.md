# ambient-advantage-mcp

A public, read-only **MCP server** that exposes the [Ambient Advantage](https://ambient-advantage.ai) content archive — daily AI briefings, Chiel's Take opinion pieces, podcast episodes, and Build Log posts — as queryable tools for LLMs and agents.

**Status:** Phase 1 in development. Not yet deployed.

## What this is

[Model Context Protocol](https://modelcontextprotocol.io) servers let LLMs call tools over a standard transport. This server wraps Ambient Advantage's public content feeds (`briefings.json`, `articles.json`, `feed.xml`, `posts.json` and their markdown twins) and exposes them as read-only tools an agent can call to:

- Look up a specific briefing by date
- Search briefings, takes, or build-log posts by keyword
- Fetch a podcast episode's metadata + transcript
- List recent content from any of the four sites

Every response includes `source_url` and `published_at` so downstream agents can cite correctly.

## Public endpoint (once deployed)

```
https://mcp.ambient-advantage.ai/mcp
```

## Architecture

A small FastAPI service on Cloud Run that reads only from the public content endpoints of the four Ambient Advantage sites. No Firestore, no shared secrets with the pipeline, no internal state. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for details.

## Tools (Phase 1)

| Tool | Purpose |
| --- | --- |
| `get_latest_briefing` | Most recent daily briefing in full |
| `get_briefing_by_date` | Specific briefing edition |
| `search_briefings` | Full-text search across briefings |
| `list_briefing_topics` | Distinct topics in a date range with counts |
| `get_chiels_take` | Single opinion piece by slug |
| `search_chiels_take` | Search Chiel's Take by keyword |
| `list_chiels_take` | Recent Takes with metadata |
| `get_podcast_episode` | Episode metadata + transcript by date |
| `list_podcast_episodes` | Recent episodes with metadata |
| `get_build_log_post` | Build Log post by slug |
| `search_build_log` | Search Build Log, optionally filtered by tag |
| `list_build_log_components` | The component grid as structured data |

## Local development

```sh
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
curl http://localhost:8080/health
```

## License

MIT — see [`LICENSE`](LICENSE). The pattern is intentionally forkable for other thought leaders who want to make their content agent-accessible.
