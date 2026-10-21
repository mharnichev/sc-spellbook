# Shop Locale Follow-Up

Source `8d6c44cc8a9aaa85fc3dcee40f9517885d9e5988`, exactly 11 scoped paths.
Localize product-page labels, accessibility text, fallback/error actions and
catalog sort labels. Enrich legacy recently-viewed and guest cart/wishlist
snapshots from existing public GETs with English presentation fields only.
Keep source names, identity, price, quantity, stock, availability and session
ownership intact. Missing/hidden/mismatched products retain existing fallback;
late responses cannot resurrect removed items or change a replacement session.
The previously released ingredients scrolling CSS is byte-identical.

## Verification

- Shop 187 tests, typecheck and build passed, zero skipped.
- 30 offline Firefox browser cases passed, process exit zero, across desktop,
  390px and 320px: UK/EN, reload, cached cards, current catalog fallback,
  quantities/prices, removed items and guest/account session transitions.
- Desktop tests use the visible locale control. Mobile tests cover persisted
  locale plus reload; the unchanged mobile header has no visible locale control.
- Independent source and corrected browser-harness review: no findings.
- 11 source hashes and 1924 protected tracked files match the freeze.
- Linux Node 20.20.2 amd64, read-only, network none: 681 output files, 54 served
  assets, ten SSR cases and zero business mutations. Actual newly built image
  repeated these checks successfully before publication.
- Immutable Shop digest:
  `sha256:fd0b1089d001901cee125c31f4b6f57d8e26237949b154195b6f60276ed29e5d`.

## Rollout

Require green infrastructure CI on the exact final PR head and independent
pin/scope review before merge. Normal frontend-only deployment: no migration,
backend/reminder restart or new data backfill. Preserve every other image pin,
environment byte, payment capability and closed customer-10 pilot. The separate
230-product English ingredients operation is already complete; do not repeat it.

After rollout verify exact digest, all service health, writer identity/start
times and unchanged environment hashes. Check actual product UK/EN description,
ingredients labels, native long-text scrolling and old recently-viewed fallback
in Chrome, without creating orders, payments, shipments or notifications.
All other local WIP and unrelated header/category cosmetics remain excluded.
