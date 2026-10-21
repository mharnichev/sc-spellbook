# Multiselect And Catalog Breadcrumbs Release

Frontend source `fd7b3ee1d7cccd237bb74c27e59b7fb2a567f6d2`, based on
`74e6f337b87d2b2c681877a977361c4a36f842d3`. Exactly three runtime components
and three tests change; all 1945 other tracked paths are protected. Frontend PR19.

## Scope

- Backoffice BaseMultiSelect: bounded scrolling, keyboard/focus behavior, bulk
  selection, disabled-option preservation, thumbnails and missing-image fallback.
- Product promotion options use the existing display-image and asset-URL helpers.
- Ordinary Shop catalog uses compact breadcrumbs and one accessible hidden H1;
  the popular-products title remains unchanged.
- Review fixes preserve the visible/custom summary in the accessible trigger name
  and reuse the existing app-local TrashIcon, retaining the smoke policy.

No session/auth changes, sidebar role changes, dependency changes, backend image,
migration, data backfill, environment edits, provider enablement or WIP included.
Closed customer-10 Shop pilot and noindex policy remain intact.

## Evidence

- Backoffice: 594 unit tests, 10 mounted browser checks, typecheck and build pass.
- Shop: 211 unit tests, typecheck and build pass. UK/EN catalog fits 1440/390/320.
- Responsive combined catalog/top browser suite: 4 pass, 2 existing failures.
  Both failures are the unchanged `/top` decorative SVG extending to 323px on a
  320px viewport, reproduced by a separately built immutable main. Assertions
  and failure artifacts were retained; this is not represented as an all-green
  browser suite. No unrelated styling repair or assertion suppression included.
- Independent exact-source review: no findings, including final regression tests.
- Frozen output tar extraction roundtrips and all source-scope hashes verified.
- Actual Linux amd64 Node20.20.2 images, network none/read-only: admin297 files,
  28 served assets; Shop672 files, 55 assets, UK/EN SSR/SPA and noindex pass.
  Mock API was GET-only; zero business mutations. No native addons.

Immutable pins:

- Admin `sha256:98d30cccb351e3f2c7bf75a4ae5f298404f90bd43bd4d733f8ca6d0358d503f1`
- Shop `sha256:5e1bdbf5d36d5934be39029eed3ee3c4f47c93773fa28754804820236c24981f`

## Rollout

Require green mandatory infra CI on the exact final PR head, then the normal
main deployment workflow. Only the two pins change; backend-pin equality must
select the frontend-only path, with no migration or writer recreation. Do not
alter workflows, security/session controls, settings or recovery gates.

Read-only production baseline is private under
`/opt/soulcuts/backups/multiselect-breadcrumbs-20261021-a0uoebse`.
Before rollout confirm current remains `20261021T130541Z-87c21c7`, schema0139,
eight services ready and no recovery fences. After rollout verify exact digest
and source labels, all six protected service identities/start times, every env
file/runtime hash, full552-product fingerprint, 279 original/278 EN ingredient
counts, zero orders/intents and the closed pilot. Run normal owner/image/SEO
checks and read-only Chrome catalog/promotion-modal acceptance. Do not save a
promotion, send notifications or create orders/payments/checks/shipments for QA.

Retain prior immutable pins and the normal frontend rollback procedure. No DB
backup/migration/recovery operation is needed or authorized for this UI-only
release; do not execute backend recovery or repeat completed ingredient writes.
