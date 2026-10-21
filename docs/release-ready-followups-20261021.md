# Verified Frontend Follow-Ups

Source `be55d684dfbdfa54f53cdd1349867cf63b78ba52` is a clean, 12-path
integration on `942b0af797aea011d4203f6aea7eba221658f04b`. Only public-site
and Shop pins change; every other pin, workflow and deployment guard is retained.

## Included

- Completed UK/EN ZSU landing page, localized footer link and public sitemap URL.
  Existing booking eligibility controls remain authoritative; no percentage or
  automatic eligibility is added. Fix the Node20 direct TypeScript test import
  through the repository's existing transpilation pattern, retaining assertions.
- Text-only Shop dropdown, centered artwork capped at 160px, centered captions,
  arrow rotation on hover/focus without card movement. Retain actual localized
  descriptions, artwork, published-tree routing, asset-prefix helpers and 404.
- OTP handler, watcher and button share six-ASCII-digit completion, preserving
  leading zero and trim behavior. This matches the existing backend generator;
  no backend/auth/session/permission changes are part of this release.

## Verification

- Explicit Node20.19.6: public-site 142 unit tests, Shop 194 tests; zero skipped.
  Both apps pass typecheck and production build.
- Offline browsers cover UK/EN ZSU metadata/FAQ/accordion/footer/booking links,
  sitemap, desktop/mobile category rendering, max artwork size, long-label/arrow
  clearance, hover/focus, navigation and fatal 404 at 1440/390/320px.
- Mounted OTP form against a local-only mock passes at all three widths:
  incomplete/nonnumeric codes never verify, error remains visible, leading zero
  is preserved, pending submission is disabled and synthetic session succeeds.
  No real OTP, provider, order, payment or notification requests are made.
- Independent source review: no findings; all 12 source hashes and 1927 protected
  files verified against the current base and frozen candidate.
- Actual built Linux Node20.20.2 amd64 images, network none/read-only: 406 public
  output files and 27 served assets; 676 Shop output files and 100 served assets;
  UK/EN SSR, SEO/sitemap, pilot noindex and category 404 checks pass. Zero business
  mutations. Both frozen tar archives pass extraction roundtrip.

Immutable digests:

- Public: `sha256:481d6a9bfd43bafca9f509c1e053c80534bbf212b3723e4e9f4a622fd19eae9e`
- Shop: `sha256:e744b3ee334e52a15d43840f69feb68014d4056b7a6c88533315aac6a696a8be`

## Excluded And Preserved

Unfinished input/payment, Dobrodesk/CSP/security/dependency work, role-facing
sidebar changes and old migration chains are excluded. Existing brands page,
EN product/cache fixes, ingredients scrolling, closed customer-10 pilot and
payment capabilities are retained. No backend image, migration, account, role,
consent, environment setting or ingredients data operation is authorized here.
Do not reapply any earlier English/original ingredients backfill.

## Rollout And Acceptance

Require independent pin/scope review and green infrastructure CI on the exact
final PR head before merge. Use the normal frontend-only workflow. Its backend
pin equality gate avoids migrations and backend/reminder recreation; existing
health, owner, immutable image and public SEO checks remain mandatory.

Capture private baseline writer IDs/start times/images, environment hashes and
the full 552-product ingredients fingerprint before rollout. After promotion,
verify all eight services, exact public/Shop digests and source labels, schema
0138 and unchanged protected baseline. Check actual ZSU canonical/FAQ/footer/
sitemap and Shop navigation/artwork/EN/404 in Chrome at desktop/mobile widths.
Do not send real OTP/SMS, create business facts, alter grants or weaken cache/CSP
rules for acceptance.
