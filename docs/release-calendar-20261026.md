# Backoffice Calendar Planner Release

## Scope

Publish only the backoffice image. Keep backend, Shop, public-site, blog,
PostgreSQL, Caddy and monitoring pins/settings unchanged. Do not include unrelated
product-content, warehouse-visibility or other local WIP.

The planner adds an explicit schedule entry from bookings, reads existing
availability, validates individual/common times and closes existing one-day
intervals using the existing role-specific API. Spanning intervals cannot be
deleted through a single-day action. A backend conflict preserves booked
availability. Existing appointments are never deleted by this UI.

Retain session/actor/role/master, generation, route-leave and unmount fences;
stop batch writes on context changes and discard late responses. Keep exact
read-before-write reconciliation for lost create responses. Fail closed if the
current schedule cannot be loaded. Preserve Kyiv date/time and horizon checks.
BaseInput ARIA changes are additive; generic input behavior remains unchanged.

## Verification And Deployment Gates

Require full backoffice unit tests, typecheck, build, independent review and
mock-browser checks for administrator/master, partial failures, stale context,
existing windows, conflicts, accessibility and desktop/mobile light/dark themes.
Use no real schedule edits, bookings, orders, payments, notifications or Sentry
test events. Production acceptance is read-only.

Publish exact-source Linux image with immutable digest. Require green infra CI
on the final head and use the normal frontend-only deployment path. No migration,
backend writer restart, role/consent/env changes or Shop pilot activation.

Private baseline and follow-up evidence under
`/opt/soulcuts/backups/calendar-20261026/` must confirm all services healthy,
unchanged env/business fingerprints and unchanged backend/reminder/Shop/
public-site/blog/monitoring containers. Only admin and the normal Caddy release
mount may be recreated. The closed Shop pilot and two-hour reminders stay intact.

## Candidate Evidence

Frontend source `747d7d1f754c9f5707fe0eafdc374b297dfde6f6` (PR 31).
645 full backoffice unit tests, typecheck and build passed. Independent review
has no remaining findings. All 43 mock-browser scenarios passed against the exact
Linux/amd64 image, including desktop/mobile light/dark, parent prop batching,
conflicts, partial retries, no implicit writes and review/login regressions.

Runtime dependencies/base are unchanged. All 304 build-output files match the
image bytes, manifest SHA-256
`3faeed31c6360ebc62d63b4a11807b1e4a46607eb42e42bb4a5b8bdf6329ff5d`.
No native binaries are present in the portable Nitro output.
