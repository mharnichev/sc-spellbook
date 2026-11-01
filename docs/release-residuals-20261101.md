# Scoped Frontend Residual Release

Preparation: release only independently tested/reviewed genuinely additive
Backoffice and Shop residuals. Source and immutable image pins are finalized
after hosted Linux build gates. No backend, migration, ingredient, account,
session, pricing, provider, public launch or legal-terms changes are included.

Final frontend source: 98cbab27fb8ca9a58b2d5b8045e3219958d1b70b (FE PR 41).
Backoffice image CI: 41329618483, successful. Shop image CI: 41329613416,
attempt 2, successful on the same source without credential or ACL changes.
Attempt 1 passed build, unit, browser, payment and offline smoke gates but
its registry publication exited with `denied`. An untagged manifest existed
and was readable; the intended tag did not exist. A single full rerun after
package creation succeeded. The registry did not disclose the underlying
cause; this is not proof of a code defect or a permission-policy fix.

Shop final CI passed 299 unit tests, mounted Chromium and WebKit interactions,
12 mocked payment scenarios against the exact built image, and offline
asset/SSR 404/noindex smoke. Backoffice passed 656 unit tests, 15 mounted
ARIA checks, 10 selector checks, type checking and production build. Both
images must be pulled and their platform/revision checked on production
before activation. Use only the immutable final pins in production.env,
not any untagged or earlier candidate image.

The required `admin-shop` scope accepts changes only to ADMIN_APP_IMAGE and
SHOP_IMAGE. Existing strict immutable pin parsing and identical Compose/Caddy
bytes are mandatory before any Docker mutation. Other changed/missing/invalid
inputs fail closed, including changes to the backend pin. Literal pins override
inherited shell image variables. Only admin-app and shop are pulled/recreated
with --no-deps. Existing schema, image identity, owner and health gates remain.
Retries with one or neither pin changed remain within the same required scope.

Caddy retains its previous identical release mount. Do not remove that mounted
release directory. Backend, reminder worker, public site, blog, PostgreSQL and
monitoring must preserve container IDs/images/start timestamps (11 unchanged
services). Frontend failures preserve current and do not stop database writers;
a failed rollout may already have replaced a frontend container and requires
explicit reconciliation, not a claimed automatic runtime rollback.

Production acceptance is read-only: Chrome UI/assets, health, image/source
identities, unchanged service metadata and existing closed-pilot settings.
No real or fake orders, payments, receipts, shipments, rewards, messages, OTP or
production Sentry test events. Payment tests use isolated mocked responses.

Excluded residuals: older auth/session/payment/telemetry/pilot variants, hidden
master inventory, conflicting old migration numbering, ingredient parser/data,
already shipped category artwork, historical docs and standalone local tests.
Do not publish the dirty original working trees.
