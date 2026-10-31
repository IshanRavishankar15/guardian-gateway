# Guardian Gateway

Guardian Gateway is a locally runnable API gateway MVP demonstrating API-key authentication, configurable upstream routing, distributed token-bucket limits, PostgreSQL-backed configuration, Redis runtime state, and Prometheus-compatible observability.

## Architecture

```text
API client --X-API-Key--> FastAPI gateway --> configured upstream
                               |  \
                               |   +--> Redis (atomic Lua token bucket)
                               +------> PostgreSQL (keys, routes, policies, audit)
                                         ^
                                         +-- one-shot Alembic migration service
Admin browser --> Next.js dashboard --> protected admin API and process metrics
Prometheus ---------------------------> /metrics
```

The gateway authenticates a client before route lookup, selects the longest matching enabled path prefix, checks the most specific enabled policy, then forwards the request. PostgreSQL is the configuration source of truth. A single Redis Lua operation reads and refills the bucket, decides quota, deducts a token when allowed, writes the state, and sets its expiry. Every gateway process uses the same Redis bucket key. Redis errors fail closed with HTTP 503. Upstream timeouts return 504 and connection/request failures return 502. The gateway does not retry upstream requests. Request and response bodies are capped by `MAX_GATEWAY_BODY_BYTES` to bound memory use; oversized requests receive 413 and oversized upstream responses receive 502.

The dashboard reads route and policy configuration from the admin API and traffic aggregates from the running backend process. Prometheus labels use bounded route-area, method, and status-class values; raw paths and credentials are not labels.

## Local setup

Prerequisites: Docker Engine with the Compose plugin. No Python or Node installation is needed for the default Compose workflow.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
```

Services are available at:

| Service | Address |
| --- | --- |
| Dashboard | http://localhost:3000 |
| Gateway and admin API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Prometheus metrics | http://localhost:8000/metrics |
| Mock upstream | http://localhost:9000 |

PostgreSQL, Redis, backend, frontend, and mock upstream ports bind to loopback only. A one-shot `migrate` service applies Alembic migrations once after PostgreSQL is healthy; gateway containers wait for it to complete before starting, avoiding competing migration attempts. Readiness checks both PostgreSQL and Redis at `/health/ready`; `/health/live` checks only that the application process responds.

`.env.example` contains development-only credentials. Replace the admin token and database password before exposing any service beyond a trusted local machine. Do not commit `.env`. `APP_ENV=production` or `staging` rejects the default admin token at startup. That guard does not make this a production-hardened deployment: this MVP has no production identity provider or role model, TLS termination, secret rotation, network policy, or multi-process metrics aggregator. Restrict `/metrics` to a trusted monitoring network in any shared deployment.

## Configure and demonstrate

1. Open the dashboard at http://localhost:3000 and enter the `ADMIN_TOKEN` from `.env`.
2. Or use this PowerShell example to provision a client, key, route, and small policy. Replace the development token if you changed it:

   ```powershell
   $runId = [guid]::NewGuid().ToString("N").Substring(0, 8)
   $adminHeaders = @{ "X-Admin-Token" = "change-me-admin-token" }
   $client = Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/clients -Headers $adminHeaders -ContentType "application/json" -Body (@{ name = "demo-client-$runId" } | ConvertTo-Json)
   $key = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/admin/clients/$($client.id)/api-keys" -Headers $adminHeaders
   $route = Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/routes -Headers $adminHeaders -ContentType "application/json" -Body (@{ name = "demo-route-$runId"; path_prefix = "/demo-$runId"; upstream_base_url = "http://mock-upstream:9000"; methods = @("GET", "POST"); timeout_seconds = 5; enabled = $true } | ConvertTo-Json)
   $policy = Invoke-RestMethod -Method Post -Uri http://localhost:8000/admin/rate-limit-policies -Headers $adminHeaders -ContentType "application/json" -Body (@{ name = "demo-policy-$runId"; client_id = $client.id; route_id = $route.id; capacity = 3; refill_rate = 0.1; enabled = $true } | ConvertTo-Json)
   $demoUrl = "http://localhost:8000$($route.path_prefix)/echo?example=1"
   ```

   The raw API key is returned only once; copy `$key.api_key` securely. The database stores only its SHA-256 digest and a short display prefix.
3. Call the route with `X-API-Key: <issued-key>`. The mock's `/echo` endpoint shows the forwarded method, path, query, body, and safe headers. The API key and administrative headers are not forwarded.
4. Send more requests than the burst capacity. Requests beyond the available quota receive HTTP 429, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` headers.
5. Observe route/policy configuration and aggregate metrics in the dashboard; `/metrics` can be scraped by Prometheus.

Example request (replace the placeholder locally):

```powershell
curl.exe -i -H "X-API-Key: $($key.api_key)" $demoUrl
```

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live` | Liveness probe |
| `GET /health/ready` | PostgreSQL and Redis readiness |
| `GET /metrics` | Prometheus exposition format |
| `/admin/clients` | Create/list clients; update activation |
| `/admin/clients/{id}/api-keys` | Issue/list keys (raw key only on creation) |
| `/admin/api-keys/{id}/revoke` | Revoke a key |
| `/admin/routes` | Create/list/update/delete routes |
| `/admin/rate-limit-policies` | Create/list/update/delete policies |
| `GET /admin/metrics/summary` | Authenticated dashboard aggregates |
| `/{request_path}` | Authenticated route to a configured upstream |

All `/admin` endpoints require `X-Admin-Token`. Gateway calls require `X-API-Key`. Route destinations must be HTTP(S) URLs without credentials, query, or fragment, and their exact hostname must be listed in `ALLOWED_UPSTREAM_HOSTS`. Set this list to the minimum trusted destinations. The local example includes loopback hosts for failure demonstrations; remove them when they are not required. This check does not replace network-level egress restrictions or DNS/IP controls.

## Configuration

| Variable | Purpose | Development default |
| --- | --- | --- |
| `APP_ENV` | Runtime environment; production/staging requires a changed admin token | `development` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose PostgreSQL initialization | `guardian_gateway`, `guardian`, `change-me-locally` |
| `DATABASE_URL` | Async SQLAlchemy connection | Compose PostgreSQL URL |
| `REDIS_URL` | Shared limiter state | `redis://redis:6379/0` |
| `REDIS_SOCKET_TIMEOUT_SECONDS`, `REDIS_CONNECT_TIMEOUT_SECONDS` | Redis call timeouts | `1.0` |
| `ADMIN_TOKEN` | Admin API/dashboard credential | `change-me-admin-token` |
| `ALLOWED_UPSTREAM_HOSTS` | Comma-separated exact host allowlist for configured destinations | `mock-upstream,localhost,127.0.0.1` |
| `MAX_GATEWAY_BODY_BYTES` | Maximum accepted request and upstream response body size (1 byte–100 MiB) | `10485760` (10 MiB) |
| `FRONTEND_ORIGIN` | Allowed dashboard CORS origin | `http://localhost:3000` |
| `BACKEND_PORT`, `FRONTEND_PORT` | Local published ports | `8000`, `3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-to-API base URL | `http://localhost:8000` |

To stop services while retaining local database and Redis data, run `docker compose down`. To delete that data as well, run `docker compose down -v`.

## Development workflow

The default Compose profile is the local development stack. After changing backend or frontend dependencies/code, rebuild and restart with `docker compose up --build -d`. Run backend linting, typing, and tests using the commands below. The test profile uses the same local PostgreSQL/Redis services and creates a second gateway container; it cleans up test records but should still only be pointed at disposable development data. Run `docker compose down` when finished; this retains named database volumes.

## Tests and load check

Run backend integration tests, including an independent second gateway container sharing the same Redis instance:

```powershell
docker compose --profile test run --build --rm test-runner
```

The test profile creates `backend-replica`; the cross-process test alternates concurrent requests between the primary and replica and asserts that only the configured burst is admitted. Tests create uniquely named fixtures and clean up their own rows and bucket keys.

Run a reproducible concurrency/load sample (adjust counts as desired):

```powershell
docker compose --profile test run --build --rm test-runner python -m tests.load_test --requests 200 --concurrency 25
```

The runner reports completed responses, throughput, HTTP and transport errors, quota rejections, and P50/P95 latency. Results depend on local hardware and are not production capacity claims. The runner creates temporary configuration and removes it after completion.

Build-check the dashboard:

```powershell
docker compose run --build --rm --no-deps frontend npm run build
```

GitHub Actions runs dependency audit, backend integration tests, backend Ruff and mypy checks, dashboard strict TypeScript checking, dashboard production build, and Compose configuration validation on pushes and pull requests. The backend static checks can be run locally with:

```powershell
docker compose --profile test run --build --rm --no-deps test-runner sh -c "ruff check app tests && mypy app"
```

The dashboard's strict TypeScript check runs during `npm run build`; run it on demand with `npm ci` and `npm run typecheck` from `frontend`.

## Deployment scope

The supported deployment for this repository is local Docker Compose development and demonstration. It is not ready to expose directly to the public internet. For a controlled deployment experiment, use `APP_ENV=production`, a unique high-entropy `ADMIN_TOKEN`, production-grade `DATABASE_URL` and `REDIS_URL`, a minimal `ALLOWED_UPSTREAM_HOSTS` list, and a deliberate body limit; then put TLS and authentication in a trusted reverse proxy and restrict network access to the database, Redis, and `/metrics`. The Compose file is not a production orchestration or secrets-management solution: it uses local development credentials by default, publishes services for local use, and does not configure TLS, Redis/PostgreSQL authentication policy beyond local defaults, backups, high availability, or aggregated metrics. Treat these as deployment requirements, not features already implemented.

## Data and implementation notes

- Alembic migrations define `clients`, `api_keys`, `routes`, `rate_limit_policies`, and `audit_logs`, including foreign keys, unique constraints, scope uniqueness, and policy checks.
- API keys use high-entropy random material and only the SHA-256 digest is persisted. The raw key is returned only at issuance.
- Policies are selected by specificity (client+route, client, route, then global). A global policy shares one quota across gateway clients and routes.
- The local dashboard summary reads process-local Prometheus counters/histograms. With multiple replicas each instance reports its own counters; use Prometheus aggregation for fleet-wide views.
- The Redis outage policy is fail-closed: a configured policy cannot be bypassed when Redis is unavailable.
- The test setup runs disposable clients against a developer's Compose database. Avoid running it against production or valuable shared data.
