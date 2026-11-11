# Complete development-owned Shop release

Application owner: sc-fe development chat. Release chat made no application
changes to the prepared source.

FE PR: https://github.com/mharnichev/sc-fe/pull/48
Source: ae8de2f044dc518efec32d6abc65a2c10a4220f9
CI: https://github.com/mharnichev/sc-fe/actions/runs/41464576343 (SUCCESS)
Image: ghcr.io/mharnichev/sc-fe/shop-residual-20261101@sha256:b051fb714d4ef4dfa49cff834014de45d521e8f93aed310b19651150c39dca7e

Owner-approved complete scope is recorded in FE
docs/releases/shop-complete-20261102.json: navigation loader ownership, inline
mobile search, cabinet links/query routing, Special offer labels, compact home
spacing/copy, ICO/SVG/PNG/Apple favicons and additional regression coverage.
No prepared manifest exists; no new PWA behavior was invented.

Exact-source gates: production Linux image build, 388 unit tests, mounted
Chromium/WebKit regressions, 38 mocked browser cases on the exact image,
offline image smoke and immutable publication. All passed before this pin.

Only SHOP_IMAGE changes. Existing admin-shop deployment scope, Compose/Caddy,
other image pins, production env, closed pilot/noindex, session and checkout
protections remain unchanged. No migration or backend/writer restart required.
Private baseline: /opt/soulcuts/backups/shop-owned-release-20261102/before.json.
Acceptance must confirm all13 healthy, other12 identities/start times unchanged,
all env hashes identical, exact Shop digest, public loader/navigation/cabinet
behavior and favicon HTTP/MIME/head links. No real transaction or message.

Recovery: previous immutable Shop pin from release
20261102T140045Z-e1bcc81 through the normal reviewed pipeline. Environment
requires no restoration because this release changes none. Retain the prior
release directory mounted by unchanged Caddy.

Explicit exclusions confirmed by development owner: unproven Dobrodesk live
iframe/roundtrip, unapproved commercial delivery/return promises, obsolete
reminder fixtures weakening current guards, unused white monobank asset and
older snapshot code superseded by protected main. Disputed ingredients untouched.
