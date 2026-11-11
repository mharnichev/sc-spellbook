# Remaining Payment And Shop UI Release

## Scope

Release only the reviewed backend payment contract, Shop cart/catalog/basket
changes and barbershop support presentation. The actively developed backoffice
calendar is excluded; its source and production image pin are not changed.
Disputed compositions and warehouse visibility changes are also excluded.

Backend source: `5e972a66b654f1b83d8b2de8238d745bb54da46f` (PR 15).
Frontend source: `550b21770ba8360ef5749df74a0990189d0d735a` (PR 30).
No dependency or migration changes; schema remains
`0143_auto_checkout_checkpoint`.

Method changes require an owned, untouched order, a current revision and nullable
attempt snapshot, an idempotency key and valid owned stock reservations. Missing
or expired financial relationships fail closed. Dispatched invoices, unknown
results, failed/expired attempts and fulfillment facts cannot authorize another
invoice or a switch to offline payment. The frontend preserves its capability,
actor, navigation and access-denial fences. A lost POST response is reconciled by
GET, never an automatic POST retry.

Cart operations are serialized within a session; session transitions detach old
requests and cancel waiting observers. Unavailable products already in a cart
remain removable. Narrow product cards must retain readable, unclipped actions.
Support remains click-loaded inside its separate-origin sandbox; no direct SDK
or global-interaction experiment is included.

## Gates

Keep public checkout disabled, the closed pilot enabled with customer allowlist
exactly `10`, existing session defenses, consent, provider configuration, Sentry
privacy/durable storage, live approved two-hour checkout reminders and monitoring.
No real test orders, payments, fiscal documents, shipments, OTP, messages or
production Sentry events may be created. No roles or accounts are changed.

Require independent reviews, unit/integration/type/build checks, desktop/mobile
mock-browser checks, exact-image provenance and isolated production-copy
backup/restore/schema/old-image compatibility rehearsal. Require green mandatory
infra checks on the exact final head; no policy bypasses.

Use immutable digests through the normal release workflow. Keep writer pause,
paired database/uploads backup, migration/readiness checks and the manual
acceptance recovery marker. Acceptance requires all services healthy, the
authenticated operations-watch owner and scheduler set intact, queue/reminder
health, preserved env/data fingerprints and unchanged admin/monitoring services.
The follow-up workflow must not restart accepted backend writers.

Private baseline and follow-up evidence is stored under
`/opt/soulcuts/backups/remaining-release-20261026/`. Rehearsal prints its separate
private evidence directory. These planned gates are not completion claims.

## Verified Candidate Evidence

- Backend: 251 focused disposable-PostgreSQL/provider tests and 76 exact-image
  tests passed; 440 runtime source files and 5,853 dependency files match the
  committed source and production runtime respectively.
- Exact-backend production-copy rehearsal passed at
  `/opt/soulcuts/backups/shop-rehearsal-6fd9aa41e128426eb5ad104c6afde2f0`.
- Frontend: 291 Shop unit tests and 158 public-site tests passed; both affected
  apps pass typecheck and production build. Independent payment and UI reviews
  have no remaining findings.
- Shop output: 703 files, SHA-256
  `4c14dc7899bf03c58b7744a7ac004456ac8fbc3327775832f8f0a67fa316dc14`.
- Public-site output: 405 files, SHA-256
  `0506a8e970dbda34601136a1e17d074b9175d2dd3270a9f3798ace6ca5f3f17a`.
  Output bytes match their Linux/amd64 images; neither output contains native
  binaries. Production runtime base images and dependencies are retained.
- Local infrastructure: 347 tests passed with eight conditional native-Caddy
  skips. Mandatory CI must run the actual Caddy and monitoring integrations.
- Final Linux Shop image: eight mocked payment browser scenarios and six layout
  scenarios passed (320, 390, 768 and 1440 pixels), including lost-response GET
  reconciliation and rating/favorite nonoverlap. Browser writes are intercepted
  by the mock API; no production or provider mutations are used.
