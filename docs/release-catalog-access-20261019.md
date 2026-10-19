# Catalog permissions and processed-photo release

## Authorized scope

Deploy the reviewed catalog-access and backoffice display-photo task diff,
plus the subsequently authorized stock/POS additions described below, over the
current production release, preserving unrelated local changes.
Do not alter production roles, photo records, Shop pilot flags or allowlist.
Do not create real orders, payments, fiscal documents, shipments, OTPs or other
notifications. Normal existing barbershop automation must remain enabled.

Backend scope: current database master-link authorization for catalog writes;
product/gallery mutation routes and inventory create/bind aliases; additive
read-only processed-image fields in backoffice/inventory responses; explicit
relationship loading for these projections. No models, migrations or feature
configuration changes are included.

Frontend scope: backoffice catalog route/control defenses, preserving staff
and superuser policy and existing inventory/POS reads; canonical processed
photos for display, while original URLs remain the edit source. Explicit empty
display arrays remain authoritative rather than reviving inactive originals.

Only backend, admin and Shop image pins may change. Public-site, Blog, Caddy
and PostgreSQL pins must remain identical to release `6a6d817`.

## Final Stock/POS Additions

While the first infra check was queued, the user authorized all latest logic.
Content comparison against the prepared release found seven additional backend
paths and six frontend source/test paths. Other local differences were stale
pre-release reversals or unrelated generated/IDE/data files, not new release work.

- Backend source `3356f0bce30f3cefd3c00313e324c529474f36d8`: stock-first
  ordering before pagination/search limits, including effective promotion prices,
  and optional `in_stock` filtering on the public product-list endpoint only.
  Category filter parameters remain unchanged. Seven-path integrated suite:
  79 passed, zero skipped, including real PostgreSQL filtering/totals/pagination,
  effective prices and null-reservation compatibility. No schema/config changes.
- Frontend source `50c65529f5c501429f6736e8ee3a9d83f962dce3`: compact POS
  search/scanner/photo fallbacks, sales-grant-conditioned POS navigation, mobile
  CSS cascade, accessible test locators and in-stock home/load-more requests.
  Independent review found a read-navigation regression; inventory navigation
  remains unconditional, while mutation and sale preparation guards are unchanged.
  Six input paths plus one focused regression test: admin 558 and Shop 143 tests
  passed, zero skipped; both typechecks and builds passed. Focused six overlap.
- Independent exact combined source review found no remaining blockers.
- Final offline amd64 images passed backend authorization/head checks, admin
  startup/SPA assets and Shop SSR/assets/deep-link/noindex checks. Only local
  GET-only fixtures were used, without application lifespan or provider actions.
- Frozen Nuxt output manifests: admin
  `d9902fec4af360cfca1c3ff5e8ab9e51ef1996e2eb3001244f5053aa8a579f68`,
  Shop `881355019fb2f85ac91c6609f97d11eee7b6cdd91e5518efaac35a2e5e265237`.
- The image pins now point to these final sources, superseding the prepared
  candidates below. The previous green infra run does not authorize this new
  pin set: require a fresh successful exact-head CI before merge/deployment.
- Production UI checks remain part of acceptance; source/unit/offline-image
  evidence is not a claim of completed production visual/master-admin testing.

## Previously Verified Prepared Candidates

- Backend source `5d1aa2637a01611959aba747977415729b18d664`: exact nine-file task
  patch over current main `606fa5120`, no conflicts or unrelated drift.
  Integrated safety suite: 176 passed, zero skipped; focused 29-test run overlaps.
- Admin source `97b62dcb5831f8afe891c2327a74ed84e4e8d2fb`: 22 changed files over
  current main `a0d529b2`. The 23rd task input, quick search, is a deliberate
  no-op: the released component already delegates image display to the updated
  product card, and its old compact-only markup was not imported.
  Integrated suite: 552 passed, zero skipped; typecheck and build passed.
- Independent read-only final BE/FE cross-contract review found no blockers.
- Both registry images are `linux/amd64`. Offline backend image verification
  checks ten guarded mutation routes, current-link denial, staff/SU policy,
  response fields and unchanged Alembic head without application lifespan.
- Admin packs the frozen verified Nuxt output into its existing Node 20 Alpine
  runtime base, pinned to the same platform digest. It is a client-rendered app:
  the target-image check validates SPA shell/startup and three JS/CSS assets,
  not server-rendered login text. The copied artifact manifest matches exactly:
  `174bcbfdbe3e411ea78a4b1e7f1d405773ac009a57eb102d15891bd9f8741918`.
- Root's earlier dirty-base evidence includes three browser mock scenarios;
  the separate production Chrome UI confirmation remains root's responsibility.

Before rollout the read-only photo snapshot has 552 product source records,
18 gallery records and 899 variants. Only aggregate hashes are exported; compare
afterward without uploading, replacing or reprocessing production photos.

## Required gates

- Apply only task-specific deltas to the actual current main branches; preserve
  released Monday availability, session isolation, pilot and runtime URL fixes.
- Run relevant tests on the integrated candidate; earlier dirty-checkout results
  are supporting evidence, not a substitute for candidate verification.
- Perform independent read-only review of the final auth/image contracts.
- Verify published image architecture and content identity; run safe target-image
  smoke without external network or application lifespan/provider side effects.
- Require green exact-head infra CI before merge.
- Use the normal changed-backend paired-backup, graceful writer handoff,
  migration-readiness, owner and image-identity gates. Head remains
  `0129_shop_ingress_limits`; do not force frontend-only deployment.
- Exit 3 is the expected pending-acceptance state, not successful acceptance or
  permission to retry. Recheck owner/schedulers, reminder process, queue status,
  HTTP/SEO and pilot settings before normal explicit acceptance.
- Root task performs the separate Chrome-extension check of master rights and
  admin photos after rollout. This release must not change roles to make it pass.
