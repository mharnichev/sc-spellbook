# Development-owned search heading and SKU spacing

FE PR: https://github.com/mharnichev/sc-fe/pull/49
Source: 4e33bd8462599a1ecf0fd77443a65b0f7926bc82
CI: https://github.com/mharnichev/sc-fe/actions/runs/41472391405 (SUCCESS)
Image: ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:8a9d3dc0ef94f1af716624ea62a670ccfbe3b9265fa4e10b4c65b75bc458c9c5

Prepared and reviewed by the sc-fe development owner. Release owner made no
application changes. One shared desktop search heading/close row is retained
across loading, empty and results states, including sticky scrolling. Hover-only
SKU has8px bottom spacing, zero idle height and zero action-row padding. Current
mobile search, keyboard, focus restoration, session/cart protections and all four
favicons are retained. Do not use the earlier f28851b8px-only image as this release.

Exact-source gates:388 units, mounted Chromium/WebKit and SKU geometry,
40 browser scenarios together on the exact image, production Linux build,
offline image smoke and publication. Independent development review completed.

Backend volume release20261102T153432Z-2e6be58 was accepted before this step:
private paired DB/media hashes validated, authenticated owner/running15scheduler
snapshot had no issues, queues unchanged, reminder import/config checked without
executing it, migration0144 and closed pilot unchanged. Canonical100-ml selects
all5 matching products; legacy100ml retains its original1-product subset by the
backend owner's confirmed backward-compatibility contract. No code fix required.

Only SHOP_IMAGE changes relative to that accepted backend release. Restore
admin-shop scope; backend/reminder pins, other images, Compose/Caddy and all env
remain unchanged. No new migration or writer restart. Verify13healthy, other12
container identities/start times identical to the accepted backend baseline,
exact Shop digest, live unified search row, focus/close/mobile behavior,8px SKU
and the category's normalized volume choices. No actual orders or notifications.

Other-app inventories: backoffice, barbershop and blog trees on main match
their existing production source pins. Backend main/prod differed only by the
now-released volume fix. No other ready application commits were identified.
Mixed dirty root work, obsolete migrations, disputed ingredients/ID45, stock
visibility, unapproved commercial promises and Dobrodesk live-frame WIP are not
silently treated as ready. See FE docs/releases/shop-search-spacing-20261102.json.

Private evidence: /opt/soulcuts/backups/catalog-search-release-20261102.
Frontend recovery uses the previous immutable Shop pin through a reviewed
admin-shop release; never revert the accepted backend or production environment.
