# Manual master rewards release preparation

Scope: backend PR20 e90556f1fd1cd5d0c246342dcae894870c0f66c2 and backoffice
PR40 323a54770d1a37da9d89906ef89789e70d6e36ce only. Other local work is excluded.
Runtime code is unchanged from the reviewed c96e89f9 / 9afeca74 implementation;
additional source changes are independently reviewed hosted-build workflows.
An empty check rollup is not a passed CI.

The candidate pins immutable BACKEND_IMAGE and ADMIN_APP_IMAGE digests and sets
`versions/deploy.scope` to `backend-admin`. Do not merge until final exact-head
infra CI and independent review gates are complete.

Hosted image build/smoke/publish gates passed:
- Backend: https://github.com/mharnichev/sc-be/actions/runs/41134780721
- Backoffice: https://github.com/mharnichev/sc-fe/actions/runs/41133704388
Backend CI also verified synthetic 0143-to-0144 existing-data preservation,
unset initial rate, empty ledger, immutable history and downgrade refusal.
Both production registry pulls must succeed before stopping writers.

The scoped path rejects unrelated image or Compose/Caddy configuration changes
before Docker mutation. Only backend, its shared-image booking-sms-reminders
worker, migration one-offs and admin-app are pulled or recreated. Writers stop
for paired database/uploads backup and migration, then restart on the same new
backend image. Public site, Shop, blog, Caddy, PostgreSQL and monitoring remain
unchanged. Existing release lock, recovery marker, Sentry-store preflight, image
identity, scheduler ownership and manual acceptance gates remain mandatory.

Migration 0144 creates six private tables; no backfill, initial rate unset.
Recovery must preserve ledger tables and data: no destructive downgrade or
automatic database restore after writes. The old 0143 image rejects schema 0144;
it is not a drop-in rollback. Use forward-compatible recovery retaining 0144 and
history. On failure retain recovery marker and stopped writers until explicit
recovery reconciliation.

Production acceptance is read-only: health, immutable image identity, served
assets, API schema/access denial, authorized private reads if available,
scheduler names/queue state, unchanged identities/start times for other services.
Do not create sales, rewards, settlements, payments, receipts or notifications.
Retain session protections, closed Shop pilot, existing consents and all secrets.

Baseline observed: `/opt/soulcuts/releases/20261029T215628Z-f4e3ed4`;
backend source 49801383 has the same tree as GitHub main 6a974272;
backoffice source 005c20b1 has the same app tree as GitHub main 619ab3f4.
