# Release Inventory - 2026-11-17

## Verified Production Baseline

- Infra: f5bb3a668e5fd648913d0ac5ba8d043d1b8d662e.
- Backend: 4efcb48b650d39fafb561b0831b27d9a4b8c4a0f, schema 0167_product_usage.
- Shop: b28130cbe1d9215eaab4448c88977d2fad93f914.
- Backoffice: 532ef2fa1b5b1c2cab83e760346dd784f2fb1e33.
- Barbershop: 7136a52c585a8a60eb59364c9aa3b42bff39b53f.
- Blog pin: 45a120d5adbadace898a400d394c5a2306f00a00.

Server-side baseline runtime verification passed: all eight image IDs match,
migration readiness passes, owner running, reminder process has zero restarts
and zero matching error lines. No production test orders or notifications.

## Candidate Changes

- Backend: preserve supplier model-name suffixes, including volume and NEW;
  two-file owner-prepared patch, no migration or data backfill.
- Backend: compact catalog cards, promotion/facet calculation and bounded
  product IDs for favorites; owner-prepared patch integrated on production base.
- Shop: hide photo pagination only in volume-selection cards; one-line patch
  prepared by sc-fe. PR 85, candidate e1d73458b; Linux CI 44176213570 passed.

## Already Deployed

- Shop UI, SEO, image/cache/transition performance and catalog pagination scroll.
- Backoffice mobile modal navigation, Mono cancellation/refunds, General Balance
  calendar and monthly-discount helper.
- Barbershop mobile bottom bar and half-visible booking vinyl.
- Previously accepted checkout/session/payment P0/P1 work (5925d1389 backend,
  3d7d6d566 frontend are ancestors of the respective deployed revisions).

## Not Blanket Release Sources

Local main and working trees are older than production branches. Backend
origin/main removes deployed migrations 0159 through 0167 and payment work;
frontend dirty files omit deployed observation, validation and consent guards.
Neither tree may replace the running release wholesale. Originals are preserved.

## Pending Or Excluded

- Animated favicon in all four apps: local behavior tests pass, but there is no
  confirmed owning/completed handoff or exact production-base browser acceptance.
- New checkout delivery UI and receipt/barcode UI requests: responsible chats
  report no completed implementation, so no release-ready patch exists.
- Targeting-report investigation: analysis only; exact reconciliation needs
  Google Ads export and published GTM configuration, not a code deployment.
- Telegram Mini App PR 43: owner ported eight feature files to the current base,
  but joint regression gives 251 passed and three Monobank caplog failures whose
  interaction is unresolved. Also requires a separate verified Caddy scope.
  Owner explicitly labels this release WIP; not included.
- Disputed ingredients and unowned local artifacts remain excluded.

## Gates

Owner handoff, exact-source tests and independent review precede image
publication and the normal sc-spellbook release. Preserve current session,
checkout/pilot, DSN, provider configuration and all unrelated service pins.

## Verification Evidence

- Backend PR 44, candidate a50c07c12: four optimization files, two name-parser
  files, catalog regression tests and an exact tracking-response expectation.
  No production schema/data change. Additional CI verifies no skipped tests.
- Integrated local PostgreSQL run: 115 passed in 230.18 seconds. Supplemental
  EN and exact-100/max-int32 tests supplied by the optimization owner and rerun
  on the integrated final candidate: three passed in 13.32 seconds.
- Two independent read-only reviews found no actionable bugs. Review gaps led
  to added non-null English-field and successful ID-boundary regression tests.
- Shop owner production build and Chromium checks at 390/1440 passed:
  volume cards have no dots; ordinary multi-image cards retain their controls.
- Blog application tree in its exact deployed source matches the corresponding
  current release snapshot; only unowned local favicon work differs meaningfully.
- Local infra tests: 470 run, OK, 11 skipped (Docker-specific checks run in CI).
  The first sandboxed attempt was denied filesystem/subprocess access; the
  explicitly unrestricted rerun passed without any test changes.
- Existing production checkout flags were recorded read-only and are not changed
  by this release. No runtime configuration or secrets are edited.
- Backend image CI 44177523688 passed on a50c07c12, including all catalog,
  checkout, migration, protected-history and offline API checks. Broad booking
  PR checks must also be green before promotion.
- Shop image CI 44176213570 passed on e1d73458b, including mounted Chromium,
  WebKit, mocked payments, Sale flows and offline image smoke.
- Root robots already advertises the Shop sitemap on the public endpoint;
  divergence of that line between app branches is source-sync debt, not missing
  public functionality. No Barbershop image update is required for that line.
