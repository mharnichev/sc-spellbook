# Shop Sale Storefront And Quote Ingress

Activate only after the backward-compatible Sale API release is accepted.
This scope may update only SHOP_IMAGE and the exact public quote path in the
existing Shop direct-API matcher. Compose and all other image pins must remain
identical. Exact path-token membership rejects wildcard insertion, including
identical-config retries; removing the one token must reconstruct the previous
Caddyfile byte-for-byte, unless the identical exact configuration is already live.

The barbershop public BFF forwards anonymous quote requests but intentionally
does not forward Authorization. Shop's quote API uses optional customer identity
for promotion validation, so it must use the existing Shop direct-API path.
Only /api/v1/public/shop-promotions/quote is added. Neighboring promotion routes,
backoffice routes and booking/session-sensitive routes retain their BFF boundary.
Direct API retains source-address normalization and no-store/private headers.

Required shop-ingress pulls and recreates only Shop and Caddy with --no-deps.
Validated literal Shop/Caddy pins override inherited shell values. Backend and
all writers are not restarted or migrated. Existing schema, health, owner and
image-identity gates remain required. Failures do not advance current or stop
writers; a partially replaced frontend/ingress still needs explicit reconciliation.
Do not remove a release folder that Caddy still mounts.

Acceptance is read-only except a non-consuming quote calculation: verify Sale
products/facets, exact ingress behavior, noindex, mobile/desktop media and UI,
unchanged closed pilot/session protection/environment, all healthy services and
unchanged unrelated containers. No orders, invoices, payments, receipts, shipment,
notification, reward or production Sentry test event may be created. Payment and
promo interaction tests use synthetic mocked API responses, not production writes.
