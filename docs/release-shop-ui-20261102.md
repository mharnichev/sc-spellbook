# Shop UI release, 2026-11-02

Scope: Shop only, reconciled onto frontend main. No backend, admin, public-site,
blog, ingress, schema or environment changes.

Frontend source: `a01db3f45c8e0c853d322f1c1f3ab94e9c5e9d6c`.
Frontend PR: https://github.com/mharnichev/sc-fe/pull/43
Image gate: https://github.com/mharnichev/sc-fe/actions/runs/41406304552

Verified image: `ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:da469149965a9dbbb46c2574fc9c7536beace029a0bd352c7673a9244617e80b`.
Image gate passed: 352 units, mounted Chromium/WebKit, 27 browser scenarios,
offline asset and SSR 404/noindex checks, Linux amd64/source-label proof.

Includes body-anchored TOP/favorite controls with reserved preview targets,
glass TOP styling, shadow removal, compact desktop title/price spacing,
Sale hover plaque, and accessible basket-total animation. Card runtime script,
authoritative arithmetic, session fencing and payment behavior are unchanged.
Stale original UI/runtime variants and disputed product content are excluded.

Local gates: typecheck, production build, 352 unit tests, mounted Chromium
pointer/keyboard/touch controls and 27 isolated mocked browser scenarios passed.
Exact Linux image must pass the same unit/mounted Chromium/WebKit/browser gates
and offline SSR 404/noindex smoke before its immutable digest is promoted.

Deployment uses existing `admin-shop` scope with only `SHOP_IMAGE` changed.
Compose and Caddy bytes must remain identical. Unchanged admin configuration
must not recreate its container. Compare all other 12 service identities,
start times and environment hashes with the private pre-release baseline.
No backend migration or writer restart is permitted. Keep the previous release
directory because Caddy retains that configuration mount.

Acceptance: all 13 services healthy; exact Shop digest and source label;
all other 12 service identities unchanged; environment hashes unchanged;
closed pilot and noindex retained; desktop/mobile read-only browser smoke.
Do not create orders, payments, receipts, shipments, notifications or OTPs.
Rollback uses the previous immutable Shop pin through the same scoped release.
