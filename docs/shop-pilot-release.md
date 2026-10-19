# Closed Shop pilot infrastructure

Local implementation based on production infra `02184c0`. Not production approval.
No production image pins have changed. `SHOP_IMAGE` is deliberately required with
no default: select and pin the accepted immutable candidate in a later release.
Image references are passed opaquely to Compose; `ghcr.io/repo@sha256:<digest>`
is supported for BE/Shop/admin, including migration and reminder services. No
deployment parser assumes a colon-SHA tag. Keep existing public/blog pins bytewise.
Compose also accepts POSTGRES_IMAGE and CADDY_IMAGE. Local defaults remain
postgres:16-alpine and caddy:2.8-alpine; before production use, primary must pin
the currently running engine digests in versions/production.env so release pulls
cannot silently upgrade the engines. This change does not write those pins.
The existing backend pin is deliberately rejected by the 0129/module preflight.
Copy the backend example Dockerfile/start.sh contract into the accepted BE build;
Compose runs the candidate image's `/app/scripts/start.sh`, not an infra bind mount.

## FE integration contract

The inspected FE candidate is `/private/tmp/sc-fe-shop-pilot-20261019`.
Shop has `app.baseURL=/shop/`, browser API `/api/v1`, private SSR API
`http://backend:8000/api/v1`. Shop must not prepend `/shop` to API paths.
Both API bases are runtime config; no internal hostname may reach browser config.
The inspected Shop and admin clients attach bearer tokens themselves. Admin refresh
posts a JSON refresh token; there is no production admin BFF to preserve.

Only these apex API families go directly through Caddy: public customers, products,
categories, brands, delivery, orders, and exact feedback/email. The barbershop BFF
continues to handle all other apex API paths, including bookings, customer activity,
reviews, repeat booking and campaign offers. Its restricted cookie/token forwarding,
Set-Cookie handling and X-Customer-Activity-Session marker must remain intact.
Admin-host `/api/v1` routes are direct and preserve Authorization, bodies and prefixes.
Admin Compose explicitly sets NUXT_PUBLIC_API_BASE=/api/v1, overriding old env files.
The api host remains backend-facing. Caddy does not strip `/api/v1` or `/shop/`.

`/shop` redirects to `/shop/`; the public apex root is NOT redirected or replaced.
Shop pages including the redirect are noindex/nofollow/noarchive and no-store.
Noindex is not access control. BE pilot membership remains a separate primary-owned
gate; pending IDs must deny all. Public checkout remains false even after acceptance.
Public/blog image pins, assets and the www support-widget/Dobrodesk exception are
unchanged. Only Shop Dobrodesk is forced false.

## Network and forwarding

`api_ingress` is internal `172.30.41.0/29`, Caddy `.2`, backend `.3` with unique alias
`api-ingress-backend`. Uvicorn trusts only `172.30.41.2`. The default network remains
for SSR/DB/outbound traffic; its peers are NOT trusted to supply client addresses.
There is no published backend port. Review default-network membership/host access.
The supplied host routes (172.17/16, 172.18/16, 172.31.1.1/32 and default) do not
overlap. Deployment repeats a read-only route-table/Docker-network overlap check.
This requires host python3, iproute2 and Docker Compose. No Caddy health cycle exists.

Official Cloudflare IPv4/IPv6 lists were checked on 2026-10-19:
https://www.cloudflare.com/ips-v4 and https://www.cloudflare.com/ips-v6.
Caddy trusts only these peers, uses strict parsing and CF-Connecting-IP only, then
overwrites upstream XFF with parsed client_ip. It strips alternate identity headers.
Maintain the list through reviewed updates, not a deployment-time network fetch.
Cloudflare IP membership is not zone authentication. Confirm origin firewall/auth,
Cloudflare header transforms/Workers/Pseudo IPv4 policy, and API cache bypass.
Validate the backend socket peer is `.2` after recreation and that two browser
clients have distinct sources. Local spoof tests do not prove the real CDN chain.

## Deploy and recovery gates

Deploy/restore/rollback/acceptance share a host-side atomic release.lock directory.
All operators must use this convention; it cannot prevent independent manual SQL
or old release scripts. Stale locks require investigation, never automatic removal.

Before starting, require approved image digests, actual production-copy rehearsal
0110 -> 0129, tested DB/media restore and old-image schema-compatibility evidence.
Offsite/encrypted retention and named RPO/RTO remain separate operator-owned
readiness requirements; the closed pilot does not establish or change them. The primary owns
`scripts/rehearse-shop-production-copy.py` and its test; this infra change does not
replace that rehearsal. Verify uploads is the real persistent mount, not an empty
new directory. Do not run deploy for a first installation without an existing DB.

Deploy requires an existing current release and compares literal previous/current
BACKEND_IMAGE pins, including digests. An inherited BACKEND_IMAGE cannot override
that comparison. Changed-backend releases (including the initial pilot)
stop backend AND the separate booking-sms-reminders loop with an explicit
90-second grace period (also used by failure cleanup
and restore). Both services declare stop_grace_period=90s for Compose recreation.
Primary records in-flight queue statuses before stopping either writer. A grace
period is not proof that an external transport completed: reconcile durable
accepted/uncertain outcomes after restart; never automatically replay them.
Deploy then verifies writers stopped, creates a private paired backup directory, validates DB archive
TOC/media archive and writes SHA256/size manifest. A TOC check is not a restore test.
Only then does `migrate` run once with no dependencies, API lifespan, uploads mount,
static address or restart. Lock wait is 5s, each migration statement 300s; this is
not a guaranteed overall migration deadline. A failed backup/migration/schema gate
keeps writers stopped and retains backend-recovery-required. No automatic downgrade
or old-backend-image restart is allowed; rollback.sh refuses backend-changing rollback.

After services start, HTTP health is followed by existing API owner log verification
and exactly one granted advisory key (1396919372,1) in the application DB. The CLI
only reads locks; it does not start workers. Logs are filtered to sanitized owner
state, scoped to the current container start. Missing/failed owner evidence fails.
Changed-backend deployment exits **3** with the recovery marker retained: services are running but
release acceptance is intentionally pending. CI should be read as pending/failed,
not retried automatically. A normal rerun refuses the marker.

Unchanged-backend releases update only public-site/blog/admin/shop/Caddy with
--no-deps, leaving API/reminders and backend configuration untouched. They run a
read-only schema check, health checks and existing owner verification, then update
current and exit 0 without backups, migration jobs or a recovery marker.
Frontend-only failure does not stop writers; frontend recovery remains manual.
Backend config changes must not be smuggled through this frontend-only path.
API, migration and reminder services explicitly share the same three HTTPS CORS
origins, so CLI settings validation does not fall back to localhost defaults.
Changed-backend preflight imports and instantiates actual Settings and required
modules and verifies head 0129 inside the candidate before stopping writers.
Exceptions produce only a fixed sanitized failure, never raw validation inputs.
This does not change the BE image or globally redact other Pydantic error paths.
Rollback requires an explicit target, identical backend pin, no recovery marker,
read-only schema/owner verification and frontend health checks; only frontend
services are recreated. Backend-changing rollback remains forbidden.

### Required manual acceptance

Using an existing authorized backoffice session (never mint an admin token):

- Read Shop operations watch on the sole API process: role owner, state running,
  no error, expected scheduler_names. Derive the list from candidate app.main and
  effective config, not defaults alone. Required here: SMS queue, campaigns,
  customer activity; preserve existing booking completion, review, waitlist,
  repeat/master reminders, catalog caches, digest and configured Brevo/NP-directory.
  NP tracking and all new Shop transports/mocks remain false. There is no 2h
  booking-reminder scheduler in app.main.
- Verify successive read-only queue snapshots/progress and classify the existing
  accepted/failed jobs. Never force a send/resend to prove health. Verify the
  separate reminder loop is single-instance, running its expected command/version,
  and has no new errors. Reconcile uncertain outcomes before recovery/replay.
- Check existing booking/admin flows, Shop login/member denial, public checkout
  503, actual proxy peer/client attribution, stable mounted media and public/blog
  pages/support behavior. Check 1-worker latency and DB-pool headroom.
- Record evidence, timestamps, expected scheduler names and the accepted release
  in the operator change record. Then run from that exact release directory:

```sh
PILOT_MANUAL_GATE=verified EXPECTED_RELEASE="$PWD" bash scripts/accept-shop-pilot.sh
```

Acceptance rechecks existing owner logs/DB lock, updates current and removes the
marker. It does not turn on checkout/providers. Owner verification remains a point
in time, not ongoing monitoring: configure alerts and a controlled owner restart
runbook; followers do not promote themselves.

Image identity is also mandatory before pending acceptance, acceptance itself, and
frontend deploy/rollback current-link updates. `verify-deployed-images.py` reads
only literal image pins, resolves each expected reference locally with Docker image
inspect .Id, and compares against the running container .Image (image config ID,
not the registry manifest digest). It checks all eight long-running services:
backend, booking-sms-reminders, Shop, admin, public-site, blog, Caddy and PostgreSQL.
Each must have exactly one running container with correct Compose service/project
labels. New app/engine pins require full lowercase 64-hex sha256 digest references;
existing public/blog commit tags are preserved and resolved locally without pulls.
Queries have 15s deadlines and suppress raw Docker errors; no full env/config dump.
The required digest pins are validated before any deployment pull or writer stop,
so production cannot silently fall back to mutable engine tags.
The deployment must have recorded phase=pending_acceptance; a marker left by a
failed migration/startup cannot be cleared merely by manual acknowledgment.
The check is point-in-time; the host release mutex does not fence out-of-band Docker
administration. Manual scheduler/queue checks and recovery reconciliation remain.

## Local verification

```sh
python3 -B -m unittest discover -s tests -v
RUN_CADDY_INTEGRATION=1 python3 -B -m unittest discover -s tests -p test_caddy_shop_pilot.py -v
```

The Caddy test uses a cached image, network=none, no published ports and synthetic
upstreams. It tests actual routing, prefix preservation, bearer forwarding,
untrusted-header spoof rejection, noindex, redirect and www support isolation.
It is not production OTP, a real browser refresh session, CDN TLS or capacity proof.

## Pre-rollout evidence, 2026-10-19

This records preparation, not production acceptance. Application sources are BE
`8df5963c6a8fb79fc53833a8bd2d05c50428ef91` and FE
`75ad59891f2ee9665635a64724e559224692cc2c`. Exact app and existing-engine digests
are pinned in `versions/production.env`. Public/blog pins remain unchanged.
Backoffice/shared types/utils at the FE assembly base match the deployed admin
source; unrelated local barbershop/blog edits were not imported.

- BE: 474 adjacent, 134 affected, 482 R6 and 74 focused tests plus local migration
  rehearsal passed. Sets overlap and must not be summed as distinct cases.
- FE: 141 Shop and 298 backoffice tests, both builds/typechecks and read-only
  desktop/mobile fixture smoke passed. No real provider acceptance is implied.
- Infra: 75 tests passed with `RUN_CADDY_INTEGRATION=1`, no skips.
- Actual production-derived private copy: `/opt/soulcuts/backups/shop-rehearsal-51ed8620678149a19ad8ffa91144dc80`.
  Upgrade 0110 -> 0129 preserved rows in all 81 original public tables other than
  the Alembic version table, comparing their original columns, and all existing
  sequences. Dump/restore preserved all rows/columns in 160 upgraded tables and
  all sequences. Five old-image core ORM models passed read-only queries; this
  is limited compatibility evidence, not permission for automatic rollback.
- Raw schema dumps were **not byte-identical**. Catalog validation and full raw
  dump comparison accepted only 21 exact differences under the existing finite
  PG16 contract (22 named definition pairs plus enum implementation ordering).
  Unknown differences fail. Only the two top-level dump guard lines are removed;
  non-guard bytes and all line endings are preserved during exact object comparison. Rehearsal tool
  SHA-256: `7ed83562ba6b5efbe89928ba12473e74643a1cc7eac24e4edfb90c6e9a947683`.
  The first raw-only comparison failure is retained separately, not counted as
  passing evidence. Private copy containers were stopped; no app lifespan ran.
- Actual media restore: `/opt/soulcuts/backups/shop-media-rehearsal-3d3cc0bc81d64f09af96629e9e4e1fbc`.
  All 16 regular files (4,636,955 bytes) restored with matching content; archive
  SHA-256 `aa750253cbb432945915c269cd5b75c14ae21bb61420205eb319126a79ac1088`.
  Live media was not changed. This live rehearsal does not replace the fresh
  quiesced paired DB/media backup required at cutover.
- The candidate accepted real production settings with explicit API HTTPS CORS
  in a network-disabled, config-only probe. Secret values were not printed.
  Migration/reminder CLI services now explicitly share that same CORS contract.

Pilot identity is existing active customer `10`; no duplicate, OTP, manually
issued token or verification override was created. The user must complete normal
phone verification. Public checkout and all new live/mock financial/shipment
transports remain disabled; the primary applies the separate pilot ID allowlist.

Actual production role is pre-existing superuser `soulcuts`; least privilege has
not been established by this release. Offsite/encrypted retention and RPO/RTO
remain unverified operational requirements, not claims of this rehearsal. Public
opening and real purchase/payment/fiscal/shipment/return acceptance remain
separate. The user performs real-flow acceptance; the agent performs no real
orders, OTP/SMS, provider POST, payment, receipt or shipment as test actions.
