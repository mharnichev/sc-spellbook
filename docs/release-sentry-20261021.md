# Backend Sentry Release

## Scope

- Backend source: `d29d654e89fb2410eeae97230b1517a520435152` (sc-be PR #1).
- Candidate: `ghcr.io/mharnichev/sc-be/api@sha256:145da657523a908611ec9e6be85b9ef13e93ce2e14e4a0673012b8c27b47e027`.
- Previous: `ghcr.io/mharnichev/sc-be/api@sha256:2aa25bc3d8dfca7e8382cc9e504e67b2cf386a586c7532eca5c9baef27fcb5ad`.
- No schema changes: exact head remains `0139_shop_input_guards`.
- All frontend, Caddy and PostgreSQL pins remain unchanged.
- Preserve session protection, closed Shop pilot, consents and existing provider settings.

## Image Provenance

The image uses the immutable previous production image as its base. Only the
committed application, migrations and startup scripts are copied over it. No
environment files, uploads, test data or graph files enter the build context.
The OCI revision label identifies the exact source above.

Only two new packages are installed offline with `--no-deps --require-hashes`:

| Package | Version | Wheel SHA-256 |
| --- | --- | --- |
| sentry-sdk | 2.70.0 | `89600e8bb5fc5239cad5c4434217f453204f2207ad29399ea58947460b37a62e` |
| urllib3 | 2.8.0 | `0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3` |

`pip check` passes. Comparing actual Linux image distribution inventories shows
no removed packages or changes to existing package versions.

## Review And Tests

Independent review found three privacy gaps in the original PR: retained header
values, client request IDs, and opaque path tokens in outgoing HTTP telemetry.
They are fixed and covered by actual SDK envelope capture tests. Correlation IDs
are limited to canonical UUIDs; outgoing URLs retain destinations, not raw paths.
Trace contexts and nested tuple values are also scrubbed. Re-review: no findings.

- Relevant Sentry/config/startup/background/reminder/SMS/booking tests: 324 passed,
  2 skipped (explicit isolated database required).
- Exploratory complete suite: 2678 passed, 1500 skipped, 2 failed, 92 errors.
  An identical run on current main without Sentry produced 2640 passed, the same
  1500 skipped, and exactly the same failure/error test IDs (verified from JUnit).
  These include absent opt-in database URLs, PostgreSQL-only checks in SQLite
  fixtures, and a stale migration-head assertion. The full suite is not green.
- Actual Linux image with network disabled: application imports, no-DSN inactive
  client, synthetic SDK transaction/breadcrumb scrubbing and cron check-ins pass.
- Infra suite: 251 tests, 8 skipped; Compose configuration passes. Independent
  infra review found no issues in the scoped changes.
- No production notifications or synthetic business/provider writes were made.

## Server Configuration

Configure `/opt/soulcuts/env/backend.env` directly on the server. Do not put the
DSN in Git, PR comments or chat. `SENTRY_DSN=` disables initialization. Preserve
an existing value; append an empty line only if the key is absent and the owner
has not supplied the project DSN yet. No DSN has been supplied for this release.

Optional settings: `SENTRY_RELEASE` (source SHA),
`SENTRY_TRACES_SAMPLE_RATE=0.05`, `SENTRY_EVENT_THROTTLE_SECONDS=600`.
Do not enable Sentry by guessing a DSN. An enabled real-project delivery test is
separate from local SDK tests and requires the actual configured project.

## Required Production Gates

1. Capture a fresh read-only production baseline, current image/env hashes,
   schema, worker ownership, pilot restrictions and queue/counter state.
2. Complete the isolated production-copy rehearsal with explicit
   `--source-head 0139_shop_input_guards` and the exact candidate/previous pins.
   No English/content backfill inputs are part of this release.
3. Require green mandatory infra checks on the exact final PR head, then merge.
4. Use the normal deploy workflow: paired database/files backup, writer fencing,
   migrate/check exact head, healthy image/owner checks and pending-acceptance gate.
5. Perform authorized admin diagnostics and read-only smoke, compare queues,
   pilot/settings/data invariants, and accept using `accept-shop-pilot.sh` only
   after those gates pass. Preserve the previous image for recovery.

At preparation time SSH to the known production host timed out. Production
baseline, env inspection, rehearsal, deployment and acceptance are NOT complete.
Do not merge this infra PR to start deployment until server access and gates are
available. Updating this example env does not change the server env.
