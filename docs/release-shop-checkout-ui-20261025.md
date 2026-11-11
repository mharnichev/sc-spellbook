# Shop Checkout And Payment UI Release

## Scope

Only SHOP_IMAGE and its source comment change. Build the exact merged frontend
source for Linux/amd64 and pin its immutable registry digest. All other images,
backend schema, writers, environment and monitoring remain unchanged.
Frontend PR https://github.com/mharnichev/sc-fe/pull/28 is merged as
`45842da630f7bc207bca2e0798ee20b3df5adbde`; its tree equals the tested candidate
`ca12b7eeb2ce9c701af1b6126880f070a14aa8f8`.
Published Shop image:
`ghcr.io/mharnichev/sc-fe/shop@sha256:ec25672d7d301144a76c1de25fc48c132bb0e57e36ed014e6af6c2aba0c1cc33`.
Offline image smoke passed for SSR/noindex, compiled JS/CSS and static icon MIME,
Linux/amd64 architecture, source label and unchanged runtime environment.

Ready local updates are ported onto current main rather than replacing it with
the older dirty working tree: localized buy/cart/unavailable labels, basket and
checkout contact copy, payment access/help and same-tab provider navigation,
bounded read polling/timeouts, and post-order cleanup/navigation diagnostics.
Final order totals remain server authoritative. The basket note promises only
confirmation of the final amount when the order is placed, not extra discounts.

Production's legacy online-payment response remains supported without new
actions/revision/attempt fields. New payment-method switching is excluded because
its backend endpoint is not in production source `dac6010f`. Do not narrow cabinet
receipt visibility from payment channel to payment method alone.

Preserve session/late-response guards, durable retry keys, hidden recovery
capabilities, manual-only scrubbed Sentry, current consents and live checkout
reminders. Public checkout stays off; the private pilot remains customer 10 only.
Do not port disputed compositions, master warehouse hiding, stale asset/root URL
variants, or unapproved shipping/return promises. Keep `/shop/` base-aware assets.

## Verification And Acceptance

Require frontend units, typecheck, production build, mocked browser checkout,
payment/receipt and responsive UK/EN catalog/basket checks. Tests must not call
real payment/fiscal/shipping/SMS/email providers or emit production Sentry events.
274 Shop units, typecheck, production build and 34 mocked browser cases passed.
Independent review closed both access-denial/capability ownership findings.
347 infra tests passed locally, with eight conditional native Caddy skips;
actual Caddy and monitoring integrations remain required CI gates.
Bank navigation is tested with synthetic URLs and fail-closed external routing;
the test explicitly returns to the local app if browser protection blocks the
mock bank origin. Do not weaken browser security to render a mocked provider.

Access denial must discard protected projections and remain in effect until a
successful read. A changed guest capability cannot leave a request permanently
busy or accept its late result. Payment creation requires a known enabled,
unpaid `not_started` snapshot and explicit action; retry after uncertainty needs
a read and retains the original idempotency key.

Run the unchanged production workflow only after green Validate infra on the
exact PR head, including native Caddy and isolated monitoring integration. The
frontend-only path must not migrate or restart backend writers.

Previous release: `/opt/soulcuts/releases/20261025T142009Z-61ec4fa`.
Private before/after evidence: `/opt/soulcuts/backups/shop-20261025/`.
Verify all thirteen service health/identity/env hashes, read-only schema and
business-data hashes, closed pilot/reminder gates, exact Shop digest and public
HTTPS/assets. No production checkout, payment, receipt, shipment or notification
is a smoke-test fixture. If necessary use the current rollback script with the
explicit previous release and identical backend pin, preserving all gates.
