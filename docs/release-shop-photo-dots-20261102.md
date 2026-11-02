# Shop compact photo pagination

Frontend source: `887dabebdfa30b5dac48c72a9290d012128be444`.
PR: https://github.com/mharnichev/sc-fe/pull/44
Image CI: https://github.com/mharnichev/sc-fe/actions/runs/41408720228

Verified image: `ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:3705795b912d698ffa720e6db81f6ccd457b174743f06d0265af7170cc6f69b4`.
Exact image passed 352 units, mounted Chromium/WebKit, 27 isolated browser
scenarios and offline asset/SSR404/noindex smoke. Native amd64/source labels
were verified before publication. Infra local suite:366tests,9conditional skips.

Only the product-card photo pagination presentation changes. The three-photo
white pill is 72x22px instead of 132x44px, with 6px markers and disjoint 24x44px
BaseButton targets. The outer decoration remains stationary while a nested
option strip scrolls for many photos. Focus, Enter/Space selection, Escape,
touch, preview reset and adjacent TOP/favorite controls remain covered.
No financial/session runtime or product data changes.

Local: typecheck, build, 352 units, independent mounted Chromium review.
Require exact-image Linux Chromium/WebKit and mocked browser gates before
promotion. No production transactions, notifications or test events.

Only SHOP_IMAGE may change; existing admin-shop scope and identical Compose,
Caddy, other image pins and environments must be preserved. Validate all13
services healthy and other12 container identities/start times unchanged.
Keep closed pilot and noindex. Private baseline is retained on the server at
/opt/soulcuts/backups/shop-photo-dots-20261102. Roll back only the Shop pin
through the same scope; keep the previous release used by Caddy's mount.
