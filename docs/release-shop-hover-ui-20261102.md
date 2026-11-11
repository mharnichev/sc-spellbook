# Shop hover, SKU, TOP and avatar release

Frontend source: `8690501fc3f58cb7c498e62834c92ebd9aec6d6b`.
PR: https://github.com/mharnichev/sc-fe/pull/45
Image CI: https://github.com/mharnichev/sc-fe/actions/runs/41417797228

Verified image: `ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:0a1f36e3b50ded16e5675ca26b031d7dcc97950d3a5acfd9baea596454aaef96`.
Image CI passed:352 units, existing controls/journal mounted tests, both new
mounted suites in Chromium/WebKit,27 isolated browser scenarios and offline
asset/SSR404/noindex smoke. Linux amd64 and exact source labels verified.

Local gates passed: typecheck, production build, 352 unit tests, existing
Chromium mounted controls, two new Chromium mounted suites and27 isolated
mocked browser scenarios. Independent runtime and test review: no findings.
Linux Chromium/WebKit and exact-image gates remain mandatory before promotion.

Scope: Shop image only. Other pins, Compose, Caddy, environment files and the
existing admin-shop scope remain unchanged. No backend migration or writer
restart. Preserve session fences, closed checkout pilot and noindex.

Reconcile only the requested changes onto current main:
- Long desktop titles expand from two to three lines; only remaining overflow
  scrolls. Short titles retain idle/hover height. Reduced motion is supported.
- Nonblank SKU appears under the type only on desktop hover, with a soft
  transition and reserved spacing, never on mobile. Authoritative data unchanged.
- Product-detail TOP uses yellow glass material while retaining star and text.
- Bottom account never gains a highlight background; the black initials avatar
  remains centered with horizontal4px padding, no vertical padding, radius4px.

Retain the released compact photo pagination and its keyboard/touch/reset
behavior. Do not copy stale local cart/payment, route, media or session code.
Tests must exercise actual mounted components in Chromium and WebKit, plus
typecheck/build/unit gates and isolated mocked purchase/Sale regression flows.
No real orders, payments, receipts, shipments, OTP, notifications or Sentry test
events are allowed during acceptance.

Production acceptance: exact immutable digest and source label; all13 services
healthy; all other12 container identities/start times and all env hashes equal
the private baseline at /opt/soulcuts/backups/shop-hover-release-20261102.
Read-only responsive UI smoke and closed-pilot/noindex verification are required.
Rollback only the Shop pin through the same scope; retain Caddy's prior mount.
