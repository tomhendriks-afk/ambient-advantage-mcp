# Architecture — ambient-advantage-mcp

This document describes the runtime shape of the Ambient Advantage MCP server. The build plan that motivated the design lives in the sibling docs repo at `ambient-advantage-docs/mcp-server-build-plan.md`.

## One-paragraph summary

A small FastAPI service running on Cloud Run that mounts an MCP HTTP/SSE transport at `/mcp`. Each registered tool delegates to a source adapter that fetches public content feeds from the four Ambient Advantage content sites, wraps the result in a Pydantic schema, and returns it to the calling LLM. A TTL cache sits in front of every outbound fetch. The service has no database, no shared secrets with the pipeline, and reads only from URLs that any external agent could read.

## Component map

```
+--------------------+      +----------------------------------+
|   MCP client       |      |  ambient-advantage-mcp           |
|   (Claude, agent)  |─────▶|  (FastAPI + mcp SDK on Cloud Run)|
+--------------------+      |                                  |
                            |  /healthz                        |
                            |  /mcp/* (MCP HTTP/SSE)           |
                            |                                  |
                            |  ┌────────────┐  ┌────────────┐  |
                            |  │ tool       │  │ TTL cache  │  |
                            |  │ registry   │─▶│ (in-proc)  │  |
                            |  └────────────┘  └─────┬──────┘  |
                            +────────────────────────┼─────────+
                                                     │
                                                     ▼
                            +──────────────────────────────────+
                            |  Public content feeds            |
                            |  briefing.ambient-advantage.ai   |
                            |  take.ambient-advantage.ai       |
                            |  podcast.ambient-advantage.ai    |
                            |  build.ambient-advantage.ai      |
                            +──────────────────────────────────+
```

## Why a separate service

1. **Zero coupling.** The MCP layer reads what every other external agent could read. A pipeline refactor cannot break it.
2. **Clean blast radius.** A bad deploy here cannot affect the daily briefing pipeline or the four content sites.
3. **Small surface to reason about.** Three runtime dependencies (FastAPI, MCP SDK, httpx). No auth wiring in Phase 1 beyond Cloud Run custom-domain TLS.
4. **Dog-fooding the discoverability surface.** Forces the public feeds (llms.txt, JSON twins, markdown twins, JSON-LD) to be coherent enough for a real agent to consume.

## Folder layout (target)

```
ambient-advantage-mcp/
  Dockerfile
  cloudbuild.yaml
  requirements.txt
  README.md
  ARCHITECTURE.md
  CLAUDE.md
  app/
    __init__.py
    main.py              FastAPI app + MCP transport mount + /healthz
    mcp_server.py        Tool registry, handlers, schemas (added in step 6)
    sources/             One module per content site (added in step 3)
    cache.py             In-process TTL cache (added in step 4)
    schemas.py           Pydantic models for tool inputs/outputs (added in step 5)
    config.py            Env vars (PUBLIC_BASE_URLS, CACHE_TTL_SECONDS, MCP_ENABLED)
  tests/
    test_tools.py        Offline smoke tests against fixtures (added in step 7)
    fixtures/            Frozen feed snapshots (added in step 7)
```

The shape intentionally mirrors `cloud-run-podcast/` so the conventions are recognisable across the project.

## Deployment shape (target)

- **GCP project:** `ai-briefing-chiel-2026`
- **Region:** `northamerica-northeast2` (Toronto)
- **Service name:** `ambient-advantage-mcp`
- **Resources:** 0.5 vCPU, 512 MiB, `min-instances=0`, `max-instances=5`, `concurrency=80`
- **Build:** Cloud Build trigger on push to `main`, mirroring `cloud-run-podcast`
- **Custom domain:** `mcp.ambient-advantage.ai`, mapped via Cloud Run domain mappings; CNAME in Cloudflare DNS

## What this service does NOT do (Phase 1)

- No writes. No Firestore. No GCS. No secret access (other than the Cloud Run service's own identity).
- No private/authenticated tools. Phase 2 will add token-gated tools for Chiel's own sessions; out of scope until Phase 1 has been live and stable for a few weeks.
- No raw query logging. Some agent queries may include sensitive context (client names, etc.); the structured log line records `query_len` and counts only.

See `ambient-advantage-docs/mcp-server-build-plan.md` for the full plan including Phase 2.
