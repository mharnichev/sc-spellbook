# Admin Product Media Follow-up

## Production Finding

Chrome acceptance of catalog/stock release `f01d85e` found an existing routing
defect: the released same-origin API base makes relative product media resolve
on the admin host. That host returned the SPA HTML with status 200, while the
same existing backend media path returned status 200 and image/webp.

No photo records or files are changed by this repair. The 900 variant rows match
the paired pre-rollout backup exactly. The older 899-row baseline predates an
additional preferred variant created at 16:38 UTC, before the rollout at 16:59.
Original product source and gallery hashes still match the older baseline.

## Primary Acceptance Waiver

The primary explicitly defers the known photo UI defect only for infrastructure
acceptance of `f01d85e`, not overall task completion. All eight image identities,
health/restarts, owner lock, 13 schedulers, reminder process, paired private
backup hashes, schema head 0129, pilot flags, queue/order aggregates and HTTP/SEO
checks passed. No real business operations were performed. The expected workflow
exit 3 and pending marker require the normal explicit acceptance command; no
marker bypass or direct production-file editing is permitted.

After that infrastructure acceptance, deploy this separately reviewed same-image
infra repair through a fresh green exact-head CI and normal frontend-only path.
Overall photo UI acceptance remains pending until real browser images load.

## Repair Scope

Only GET/HEAD `/media/products/*` on the admin host reaches the existing backend
media mount, with the path intact. Other media paths, APIs, application routes
and hosts retain their routing. Retain nosniff and add a deferred restrictive CSP
with sandbox/default-deny/frame-deny for uploaded content on the admin origin.
Missing media must return backend 404, never the SPA fallback.

All seven image pins remain identical to `f01d85e`; do not restart backend or
reminders, migrate or create another backend-critical marker. Verify image MIME
and byte hashes, Chrome loaded photos, authenticated diagnostics and Shop pilot
settings afterward. Do not modify roles, photos, orders or provider settings.

Final local opt-in infra suite: 83 passed, zero skipped. Isolated Caddy fixtures
verify GET/query preservation, HEAD, no POST/PUT/DELETE forwarding, restrictive
headers, missing-media 404 and unrelated routing. The raw HTTP fixture keeps its
input socket open long enough for proxy responses; assertions were not weakened.
Fresh exact-head GitHub CI and final independent review are required before merge.
