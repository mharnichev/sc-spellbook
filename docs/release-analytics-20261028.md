# Public-Site Analytics Release

## Scope

Frontend source `56c69a90c96241475b8e72d902e827837e4ba7ce`, sc-fe PR37.
Only PUBLIC_SITE_IMAGE changes. Backend, admin, Shop, blog, engines, monitoring,
migrations, prices, schedules, consent settings and providers remain unchanged.
Original dirty repositories are not incorporated. Existing session protection
and the closed Shop pilot are retained. No real test bookings, notifications or
production analytics success events may be created.

Preserve direct GA4 G-YYYXH2R239 and GTM-5NK5VGXR, whose published container also
routes to G-CNQHGXKKV6. No direct second-ID installation, tag/config/profile or
advertising changes. Tracking follows consent and private-route rules. Add only
bounded no-slot, slot-load and waitlist diagnostics; do not send PII, tokenized
URLs, raw errors or API objects. Contacts submission captures a stable snapshot
across availability awaits and fences double submits. Success remains tied to
successful API response, with no automatic POST retry on uncertain results.

## Evidence And Limitations

160 unit tests, typecheck and production build passed again in the release
checkout. Independent source review/simplification was completed by the source
task with no remaining findings. The source task reports 52 distinct mock-browser
cases across desktop/mobile Chromium, Firefox and Linux WebKit; native macOS
Safari14 is not verified. Mock API does not prove backend persistence.

Exact Linux/amd64 image has 405 matching output files; manifest SHA256
`dbacfb1d9292e24820622f01632e2ae783a7c9cf2ee90967e07bd2a5958524fd`.
Runtime base and dependencies are unchanged. A local synthetic interception
harness using saved official GA/GTM scripts produced one booking_success request
for each destination, answered by local204. No event was sent to Google; this
does not establish actual production Google receipt.

Separate sc-e2e PR5, commit cc460664ea41baeaa3b69f9ce103520bdb2d7426, stays open.
Its run40737735927 has a passing booking-critical test step but failed artifact
upload due to quota; overall CI is NOT green. The new mock suite is not wired to
CI. No check is skipped/weakened, artifacts deleted, quota/payment altered or
approval submitted. This testrepo PR is not merged as part of the FE release.
No cross-repo CI dependency is declared by the FE/infra repository release rules.

## Deployment And Acceptance

Require exact-head green mandatory infra CI before merge, then normal
frontend-only deploy and public SEO gate. No backend writer restart or migration.
Private before/preflight/after identity evidence under
`/opt/soulcuts/backups/analytics-release-20261028/` must confirm all13 services
healthy and all containers except public-site/Caddy unchanged. Read only safe
image/health fields; do not read secret files, credentials or customer records.
Verify deployed revision/digest, routes/assets and the unchanged two-destination
topology. Never claim real conversion receipt without corresponding evidence.
