# Backoffice Slot And Product UI Release

## Scope

Change only ADMIN_APP_IMAGE and its source comment. Frontend PR:
https://github.com/mharnichev/sc-fe/pull/29, candidate source
`4f4d0f76b9a099f372303a5777c23081aca15612`. Require the merged tree to match
this tested source before publishing/deployment.

PR29 merged as `31d365f2960ffe5fe3ff4db685808238c4d3ca45`; the entire merge tree
is identical to the tested candidate. Published immutable image:
`ghcr.io/mharnichev/sc-fe/admin@sha256:79ed91dbf61046e0cb1db7ff5b48a53416a94feabc5a26e87ac65bcab9d4d2e6`.

Port new changes onto current main, never replace it with the old dirty local
tree. Include slot-to-multiday availability with exact initial time, mobile
availability shortcut, calm date drafts, compact product settings/help and
gallery view/edit separation. Keep the gallery mounted while hidden so closing
or saving the editor does not discard pending uploads. Preserve existing
session/late-response guards, availability read-before-retry and date checks,
PWA/offline behavior, permissions, theme and responsive field sizes.

Do not hide warehouse from masters or change product ingredient content.
Do not change backend, Shop, public site, blog, schema, environment, account
roles, consents, reminder settings or telemetry. Closed Shop pilot remains
customer 10 only with public checkout disabled. No real provider transactions
or notifications, no production Sentry test events.

## Gates

Require final frontend unit suite, typecheck, production build, isolated mounted
calendar/product browser checks and integrated mocked API/browser tests. Cover
exact slot transfer, explicit submission, role-specific endpoints, duplicate
protection, mobile navigation, product view/edit/create, settings validation and
pending lock, delayed two-photo upload completion after closing edit mode.
Do not weaken assertions to pass a slow dev-server navigation test: verify the
same assertions against the final production build.

Final evidence:621 unit tests, typecheck, production build and all20 mocked
browser/API scenarios on the actual Linux runtime image passed. Mounted
calendar/product checks passed at mobile/desktop and light/dark viewports.
Independent full and followup reviews have no unresolved findings.347 infra
tests passed locally (8 conditional native Caddy skips remain covered by CI).
Slow dev/cold-host runs were not accepted as success: final image tests passed
in26.3seconds with assertions intact and a bounded90second scenario budget.
Final pending two-photo regression uses local test PNGs, never production media.

Independent read-only review must have no unresolved findings. Build the exact
clean source's platform-neutral Nitro/JS artifact, verify it contains no native
`.node` binaries, and package it in the unchanged pinned Linux/amd64 runtime.
Verify unchanged runtime environment/source,
compiled assets/MIME and PWA icons offline. Publish immutable digest only after
application gates pass. Require unchanged Validate infra CI on the exact PR
head, including Caddy and monitoring integration; do not bypass CI or policies.

## Production Acceptance

Baseline: `/opt/soulcuts/releases/20261025T210532Z-d923f3f`.
Private evidence: `/opt/soulcuts/backups/backoffice2-20261025/`.
Run the unchanged deployment workflow. This is frontend-only: do not migrate,
restart writers or introduce backend acceptance gates. Preserve all other image
pins. Verify 13 healthy services, unchanged non-admin/non-Caddy identities,
environment hashes, schema `0143_auto_checkout_checkpoint`, business-data
fingerprints and closed-pilot/runtime gates. Check public HTTPS and read-only
browser UI without submitting real catalog/scheduling mutations. If necessary
use the existing frontend-only rollback path with the explicit baseline release.
