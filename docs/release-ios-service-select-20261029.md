# Backoffice iPhone Service Selector Candidate

## Scope

sc-fe PR39 source `005c20b143df72c40a5a71fea94010456f8531d4`, based on
`16eb0efe156f3e664481d3330ad59c7871a9bcd2`. Only four scoped files; no dependency,
API, migration, GA4, pricing or scheduling change. Touch/pen does not implicitly
focus search; coarse-pointer modal menus flow in the modal. Keyboard access,
Escape and Tab remain available. Source/component SHA256:
`c5c6fd543c4e11e5c552d0ebde5327ee8e502136bf9b707d362df688bb9ec82e`.

Only admin-app may be updated or restarted. Backend, reminder writer, public-site,
Shop, blog, Caddy, PostgreSQL and monitoring must retain container identities and
start times. Do not create real bookings, messages, payments or customer writes.
Preserve existing session guards and the closed Shop pilot. No credential/env
files are changed. The previous manifest access denial was not bypassed: the new
direct user request was followed by a successful explicit escalated read of the
repository version manifest. Private production env files remain unread.

## Verified Candidate

654 unit tests, 10 mounted tests, typecheck and build passed. Portable fixtures
passed 14 Chromium and 14 Linux WebKit iPhone13-profile scenarios with retries0.
The exact final image passed all14 Chromium cases again. A first local image
attempt could not connect because Docker's internal network did not publish its
loopback port; no functional assertion ran. After diagnosis and a local HTTP200
preflight the unchanged assertions passed. External browser requests and real
API mutations are blocked by the fixtures.

The final Linux/amd64 image preserves production runtime base
`ghcr.io/mharnichev/sc-fe/admin@sha256:0da8407da0047855f9658ee6e73c48b6f30ed905cb8e7805b9e58eb4ed5435ce`.
All305 output files match the tested artifact manifest SHA256
`2ce1d4f5dc82e96d793a0ebe01ed00a96b30e88648187b12a4fe24b955cdfa1a`.
Runtime layers, environment defaults, command, entrypoint and user are unchanged.
Source archive SHA256:
`4559e1b587d0c0dca5a2dfb216bf1b7225b8ae04af4de899acc2f8f6287f0832`.
Physical iPhone/native Safari keyboard behavior is NOT verified; user acceptance
remains required. Do not describe the reported physical-device bug as proven fixed.

## Required Admin-Only Gate

`versions/deploy.scope` requires admin-app-only deployment. The release refuses
before mutating Docker commands if other image pins differ, required pins are
invalid/missing, or shared Compose/Caddy files differ. An eligible deployment
pulls/up only admin-app with no dependencies and forces the literal release pin.
All normal locking, schema, owner, health and image-identity checks remain.
Identical-pin retries remain admin-only. Generic releases without the scope file
retain the existing deployment path. A future broader release must explicitly
remove this scope file; do not weaken its checks to get a deployment through.

Caddy retains its existing identical configuration mount. Retain the mounted old
release directory until a future authorized Caddy recreation. A failed admin
startup/acceptance leaves current unchanged but may have replaced the running
admin container; recovery is manual and must stay admin-only.

Require independent review and exact-head green infra CI before merge. Private
read-only before/preflight/after identity evidence is stored under
`/opt/soulcuts/backups/ios-service-select-20261029/`. Production acceptance checks
all13 services and exact served admin assets without saving a real booking.
