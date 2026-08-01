# Monatise application orchestration runbook

## Scope and safety

This layer coordinates crypto intelligence only. It has no broker, exchange,
order placement, position mutation, or governance-bypass interface. A blocked
decision, rejected/conditional risk result, blocked allocation, blocked policy,
or governance freeze stops downstream processing.

## Startup

1. Load configuration from defaults, deployment file, environment, then an
   approved runtime override.
2. Resolve secrets through the deployment secret provider; never place secret
   values in configuration snapshots, logs, audit records, or events.
3. Run `deploy/migrations/001_application_orchestration.sql`.
4. Validate the DI graph and the complete 20-engine registry.
5. Freeze configuration and start plugins, scheduler, health server, and the
   application.
6. Require HTTP 200 from `/health/ready` before accepting scheduled work.

Shutdown must stop new schedules, await active analysis tasks, flush exporters,
stop plugins, and then close Redis/PostgreSQL pools.

## Observability

Alert on `pipeline.runs.total{status="failed"}`, stage latency, repeated provider
retries, CoinGlass consecutive failures, event delivery failures, PostgreSQL
availability, Redis availability, audit-chain verification, and readiness 503s.
Correlation IDs flow through events, audit records, logs, state, and results.

## Backup and recovery

Use encrypted daily PostgreSQL custom-format backups with 30-day retention and
weekly restore drills. Enable continuous WAL archiving for point-in-time recovery.
Redis is a cache/scheduling acceleration layer; persist it with AOF but treat
PostgreSQL audit/event/state records as authoritative. Store backups in a
versioned, access-controlled bucket in a separate failure domain.

## Deployment

`docker-compose -f deploy/docker-compose.orchestration.yml up -d` starts durable
dependencies locally. Production credentials must come from the platform secret
manager. The existing GitHub Actions workflow runs every Python test for pushes
and pull requests. Roll out one instance first, check readiness and pipeline
failure rates, then continue. Roll back the application image before rolling back
additive migrations.

### Render paper staging

The legacy `monatise-live` service remains separate and continues to use
`scripts/serve_live.py`. The `monatise-paper-staging` service uses the dedicated
`monatise.application.deployment:app` ASGI entrypoint. This stabilization change
does not repoint production; promotion is a later, explicit decision.

Staging requires `MONATISE_DATABASE_URL` and `MONATISE_REDIS_URL` from
network-accessible managed services. It must never use localhost/Homebrew Redis,
inherit live/mainnet values, or receive exchange account addresses, private keys,
or order-submission credentials. CoinGlass is read-only. Telegram is
notification-only and OpenClaw is non-executable.

Render start command:

```text
uvicorn monatise.application.deployment:app --host 0.0.0.0 --port $PORT --workers 1 --timeout-graceful-shutdown 30
```

Required secret placeholders are `COINGLASS_API_KEY`,
`MONATISE_TELEGRAM_BOT_TOKEN`, `MONATISE_TELEGRAM_CHAT_ID`, and
`MONATISE_OPENCLAW_TOKEN`. Do not provision or deploy the blueprint until the
stabilization PR is approved. Auto-deploy is initially off and the service must
run one worker.

After deployment, run:

```bash
uv run python scripts/staging_smoke_test.py --base-url "$STAGING_URL"
```

The public smoke check validates liveness, readiness, managed dependencies,
migration status, canonical engine order, governance availability, and the
paper/no-execution notification invariants. Full pipeline fixtures, persistence,
restart recovery, event deduplication, and scheduler failover remain mandatory
service-backed staging acceptance checks before production promotion.

## Rate limits and retry policy

CoinGlass requests use a process-local rate limiter, bounded exponential backoff
with jitter, TTL caching, and health counters. The pipeline retries only stages
marked retryable. Analytical rejection is never retried or transformed into an
approval.
