# Shop ready updates release

Frontend source: `f9fad1f5ce0ff8237f465ce20a3019c61cfe6e08`.
Frontend PR: https://github.com/mharnichev/sc-fe/pull/46
Image CI: https://github.com/mharnichev/sc-fe/actions/runs/41453185975 (SUCCESS).
Immutable image: `ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:d767a007489aad64607f08687a1bcc8957750ca625125699a2da7db9903b11d1`.

Selective reconciliation onto current main, not a copy of the stale original:
- Compact idle SKU spacing, expanded only for actual desktop hover.
- Product description uses BaseAccordion: ten rendered lines below1280px,
  short/desktop full content, responsive/font/localized measurement, inert
  collapsed previews, animation cancellation and reduced motion.
- One persistent cabinet shell and internal transitions; retain router recovery,
  payment/session isolation and order-refresh guards from main.
- Base-aware branded transition overlay and explicit-click support launcher.
- Authenticated cabinet contact support was explicitly approved by the owner.
  Other private/query/hash routes remain blocked; SDK gets no customer/order
  context. Initialization/open failures are contained and never overwrite error
  state with late readiness.

Exclude unfinished mobile header panel/stack changes, stale category-description
removal, duplicated counters, old API/cart/payment guards and unapproved copy.
Category artwork already matches main. Preserve disputed content and other apps.

Local gates: typecheck/build,369 unit tests, Chromium mounted cases and29 isolated
browser cases. All matching Linux Chromium/WebKit/exact-image gates are mandatory.
No production transactions, OTP, notifications or test chat messages.

Deploy only SHOP_IMAGE through the existing admin-shop scope; other pins,
Compose/Caddy and backend/writers remain unchanged. Owner separately approved
NUXT_PUBLIC_DOBRODESK_ENABLED=true in /opt/soulcuts/env/shop.env. Stage only after
infra CI succeeds, immediately before deployment, with strict baseline hashes,
duplicate-key checks, private0600 backup and atomic mode/owner-preserving write.
Private evidence: /opt/soulcuts/backups/shop-all-release-20261102. The prepared
record allows only the exact approved shop.env hash delta; all other environment
hashes and all other12 service identities/start times must remain unchanged.

Acceptance: exact image/source;13 healthy services; other12 unchanged; public
checkout false/pilot true; noindex; responsive public/product/cabinet UI checks.
Verify explicit runtime support activation without exposing integration settings.
Retain Caddy's prior mounted release. Recovery restores the previous immutable
Shop pin and the private shop.env.before only after confirming no concurrent
environment changes; never overwrite unrelated secrets or activate other apps.
