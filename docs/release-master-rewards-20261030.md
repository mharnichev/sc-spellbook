# Manual master rewards release preparation

Scope: backend PR20 c96e89f9563e7c123dfea74607927a1a24469083 and backoffice
PR40 9afeca7441940bea340355a1283b66010e5a82b0 only. Other local work is excluded.
Source repositories have no checks; an empty check rollup is not a passed CI.

The candidate requires new immutable BACKEND_IMAGE and ADMIN_APP_IMAGE pins before
release, plus `versions/deploy.scope` set to `backend-admin`. This preparation
does not yet change pins or activate that scope. Do not merge this preparation
until image, exact-head CI and independent review gates are complete.

The scoped path rejects unrelated image or Compose/Caddy configuration changes
before Docker mutation. Only backend, its shared-image booking-sms-reminders
worker, migration one-offs and admin-app are pulled or recreated. Writers stop
for paired database/uploads backup and migration, then restart on the same new
backend image. Public site, Shop, blog, Caddy, PostgreSQL and monitoring remain
unchanged. Existing release lock, recovery marker, Sentry-store preflight, image
identity, scheduler ownership and manual acceptance gates remain mandatory.

Migration 0144 creates six private tables; no backfill, initial rate unset.
Rollback must preserve ledger tables and data: no destructive downgrade or
automatic database restore after writes. On failure retain recovery marker and
stopped writers until explicit recovery reconciliation.

Production acceptance is read-only: health, immutable image identity, served
assets, API schema/access denial, authorized private reads if available,
scheduler names/queue state, unchanged identities/start times for other services.
Do not create sales, rewards, settlements, payments, receipts or notifications.
Retain session protections, closed Shop pilot, existing consents and all secrets.

Baseline observed: `/opt/soulcuts/releases/20261029T215628Z-f4e3ed4`;
backend source 49801383 has the same tree as GitHub main 6a974272;
backoffice source 005c20b1 has the same app tree as GitHub main 619ab3f4.
