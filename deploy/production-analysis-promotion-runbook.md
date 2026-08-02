# Monatise production analysis promotion and rollback

## Scope

This promotion replaces the web process for `monatise-live` with the canonical
20-engine orchestration runtime in paper, analysis-only mode. It does not enable
an exchange adapter or order submission. The staging service and its Redis and
PostgreSQL resources remain separate.

The current rollback target is Render deployment
`dep-d9n7fsoae00c73b0ni70`, commit `8f3bc58265a75abd03e9dd48abb8ec504c425b67`.
Record the reviewed PR merge commit and the new Render deployment ID here in the
deployment change record before promotion.

The legacy `/data` authentication disk belongs to the previous web runtime and
is not mounted by the orchestration service. Preserve the old Render deployment
until product owners separately decide how to migrate or retire that legacy UI
and authentication data.

## Pre-deployment gate

1. Require a green pull-request run with all PostgreSQL and Redis contracts.
2. Confirm `render.yaml` retains `monatise-live`, one worker, Oregon, Starter,
   `/health/ready`, and `autoDeployTrigger: off`.
3. Confirm the production PostgreSQL and Redis resources and the namespace
   `monatise:production-analysis` are distinct from staging.
4. Configure CoinGlass, Telegram, and OpenClaw secrets without exchange keys.
5. Verify every execution flag is false, the kill switch is true, and audit is
   enabled.
6. Take or verify a PostgreSQL backup. Migration 001 is additive and compatible
   with the rollback runtime, which does not read the orchestration tables.

## Manual promotion

1. Review and merge the approved PR manually.
2. Sync the production Blueprint from `render.yaml` without enabling auto-deploy.
3. Record the previous deployment ID and new commit.
4. Manually deploy that exact commit to `monatise-live`.
5. Wait for `/health/ready` to return 200, then run:

   ```bash
   MONATISE_OPENCLAW_TOKEN="<production control token>" \
     uv run python scripts/production_analysis_smoke_test.py \
     --base-url "https://monatise-live.onrender.com"
   ```

6. Verify audit integrity after the smoke analysis and confirm only one Redis
   scheduler leader. A replacement process that initially loses the lease keeps
   contending and starts its scheduler after acquiring it.

## Rollback triggers

Rollback immediately for readiness 503, migration failure, Redis failure,
multiple or missing scheduler leadership after the lease window, audit-integrity
failure, CoinGlass failure, accidental execution enablement, unavailable
governance kill switch, secret exposure, or any production staging/test route.

## Rollback

1. Disable external analysis requests while preserving health access.
2. In Render, select deployment `dep-d9n7fsoae00c73b0ni70` and choose Rollback.
3. Confirm that the previous runtime is live and its health endpoint passes.
4. Do not reverse migration 001; it is additive and safe to leave in place.
5. Leave the production Redis namespace intact. Its leases and replay keys expire
   by TTL; PostgreSQL remains authoritative for durable state and audit history.
6. Verify the failed orchestration instance released scheduler leadership and
   retain its audit records and logs for incident review.
