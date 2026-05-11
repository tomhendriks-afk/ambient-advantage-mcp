# ambient-advantage-mcp — Claude context

This is the FastAPI service that powers the Ambient Advantage MCP server.
It runs on Cloud Run in `northamerica-northeast2` (Toronto), scales to zero,
and exposes a public, read-only MCP endpoint at `mcp.ambient-advantage.ai`.

For full architecture, see `ARCHITECTURE.md` in this directory and the build
plan at `../ambient-advantage-docs/mcp-server-build-plan.md`.

---

## What this service does

- Mounts the Model Context Protocol (MCP) HTTP/SSE transport at `/mcp`.
- Registers a set of read-only tools that wrap the public content feeds of
  the four Ambient Advantage sites (briefing, take, podcast, build-log).
- Caches outbound fetches in-process with a small TTL dict.
- Serves a `/health` liveness endpoint for Cloud Run probes.

## What this service does NOT do

- No writes. No Firestore. No GCS.
- No shared secrets with the daily-briefing pipeline.
- No raw query logging. Records counts and lengths only.

---

## Patterns I must respect

**Zero coupling with the pipeline.** This service reads only from public
content URLs that any external agent could read. Never reach into Firestore,
the pipeline's GCS bucket, or any of the cloud-run-podcast secrets.

**Schema as public contract.** Tool names and Pydantic input/output schemas
are versioned (`schema_version: "v1"`). Additive changes only after launch;
bump the major version in the tool name otherwise.

**Cache before fetch.** Every outbound HTTP call goes through `app/cache.py`.
Index feeds: 5-minute TTL. Article bodies: 1-hour TTL. Coalesce concurrent
requests to the same URL to avoid cold-start stampedes.

**No raw query logging.** Some agent queries include sensitive context
(client names, internal projects). Log structured fields only:
`tool_name, query_len, result_count, upstream_latency_ms, total_latency_ms,
cache_hit`.

**Feature flag the MCP mount.** `MCP_ENABLED=true` gates the `/mcp/*` mount
so the service can be deployed before tools are wired up.

---

## Key code paths

| Concern | File |
| --- | --- |
| API routes + MCP mount | `app/main.py` |
| Tool registry | `app/mcp_server.py` |
| Source adapters | `app/sources/{briefings,takes,podcast,build_log}.py` |
| TTL cache | `app/cache.py` |
| Pydantic schemas | `app/schemas.py` |
| Config & env vars | `app/config.py` |
| Docker | `Dockerfile` |
| CI/CD | `cloudbuild.yaml` |
| Tests + fixtures | `tests/` |

---

## Common commands

Read-only diagnostics — run freely:

```sh
# Local dev
uvicorn app.main:app --reload --port 8080
curl http://localhost:8080/health

# Run tests
pytest -q

# Tail Cloud Run logs (once deployed)
gcloud logging read 'resource.type="cloud_run_revision"
  resource.labels.service_name="ambient-advantage-mcp"
  severity>=ERROR' --limit=50 --format=json

# Service description
gcloud run services describe ambient-advantage-mcp \
  --region=northamerica-northeast2
```

Mutating — propose first, run only with explicit approval:

```sh
# Build + deploy
gcloud builds submit --config=cloudbuild.yaml

# Map custom domain
gcloud beta run domain-mappings create \
  --service=ambient-advantage-mcp \
  --domain=mcp.ambient-advantage.ai \
  --region=northamerica-northeast2
```

---

## Git sync rule

Before any commit or push, pull the latest remote state first:

```sh
git fetch origin main && git rebase origin/main
```

Both the local dev machine and (later) Cloud Build may write to this repo's
metadata branches. Pull first to avoid rejected pushes or — worse — losing
remote commits. Never use `git push --force` on this repo.

---

## Deploy checklist

1. `git fetch origin main && git rebase origin/main`
2. Run `pytest -q` locally. All tests must pass before pushing.
3. Show the diff. Get explicit approval.
4. `git push origin main` — Cloud Build auto-triggers (once wired up).
5. Watch the build: `gcloud builds list --limit=1` → `gcloud builds log <id>`.
6. After deploy, verify: `gcloud run services describe ambient-advantage-mcp
   --region=northamerica-northeast2 --format="value(status.url)"` then
   `curl <url>/health`.
