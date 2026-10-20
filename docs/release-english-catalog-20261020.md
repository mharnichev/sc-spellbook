# English Catalog Release

## Scope

Backend source `1b45e7b34adbc35ab5cc69d9ed542a68480ea133` and Shop source
`fd47ade2a98942801ac8af3535bcbea212b8b9e0` add nullable English metadata,
API serialization/search, and reactive English labels with original-language fallback.
Migrations are 0134 -> 0135 -> 0136_category_names_en. Only the backend and Shop
image digests change. Existing QR grants, closed pilot, payment flags, original
names/slugs/hierarchy, stock and financial facts must remain unchanged.

## Required Gates

1. Freeze the exact source and image digests; independently review the complete
   application and infrastructure diff. Pass tests, types, build, Linux runtime
   verification, and all mandatory checks on the exact final infrastructure head.
2. Copy the two reviewed input JSON files privately into an owned 0700 directory
   directly under `/opt/soulcuts/backups`; source files must be private regular
   files. Never commit inputs, database copies, reports, or secrets to Git/images.
3. Run the protected production-copy rehearsal from source head
   `0134_shop_canonical_collation` with all three English input arguments. It must
   cover both dry runs, separate applies, idempotence, original-column/sequence
   preservation, and restore of the fully translated copy.
4. Use the normal deploy workflow, paired database/files backup and writer
   quiescence. Migration/health success is not final backend acceptance.
5. Under the release-lock wrapper, run `scripts/run-english-backfill.sh apply`
   with the reviewed inputs and both exact SHA-256 values. Inspect the wrapper's
   usage and required release/pin variables before invoking it. The operator
   preserves the backend acceptance fence, stops both writers and creates durable
   private reports before each entity transaction.
6. Verify pinned runtime health and safe, read-only Shop UK/EN rendering:
   product/category/child labels and breadcrumbs, 552 products and 44 categories.
   Confirm pilot, QR flags/grants and original catalog/financial facts unchanged.
7. Only after runtime/UI verification, finalize English via the wrapper with
   `ENGLISH_RUNTIME_VERIFIED=true`, then perform normal manual backend acceptance
   for the exact release. A successful English receipt is not backend acceptance.

Reviewed product input SHA-256:
`0bfcfa906550d8f96d5338ebbeb67ce81e40406fcdf69f11f40145f0b2a5af7d`.
Reviewed category input SHA-256:
`a30b7ab2727425a5bffd16427bf1e038c99bc939469d1b368936aae322a28d50`.

## Recovery

Product and category writes are separate transactions, not a combined atomic
operation. An on-disk `prepared_apply` report alone does not prove commit.
On failure keep writers stopped and preserve all private evidence and fences.
Do not bypass acceptance, automatically start old code, or blindly restore a dump.

Use the explicit wrapper recovery modes for the exact report directory:
`reconcile` verifies fully committed target vectors; `rollback` restores only the
three English columns under whole-entity compare-and-swap with unchanged original
database provenance. Mixed or foreign vectors require investigation, not overwrite.

Finalization durably writes `finalized.json` before removing the English fence.
If commit succeeds but the parent loses the acknowledgment or receives a deferred
signal, the English fence may legitimately be absent: keep the backend fence and
writers stopped. Never recreate the English fence or reapply translations. Use
`recover-finalize` to stop any surviving owned tasks, perform fresh read-only
verification and restart the exact pinned writers. Recheck runtime/UI, run
idempotent `finalize`, then normal backend acceptance. Preserve the receipt.

Schema downgrade removes the new translation columns; it is not data recovery.
Do not create orders, invoices, receipts, shipments, OTP or notifications for tests.

Direct Docker database tools must explicitly reproduce Compose's internal
`POSTGRES_HOST=postgres` and `POSTGRES_PORT=5432` process overrides. Host-facing
dotenv values are not the container database authority; never relax the network
guard to accept them or change production env files to accommodate a one-shot.
If failure occurs before the snapshot or any apply, confirm zero English writes,
no surviving owned tasks and no English fence before restoring the same pinned
writers under the release lock; retain the backend acceptance fence.
For an already pending immutable release, a reviewed, exact-hash operator hotfix
with green CI may be executed from a private recovery-tools directory under the
owning release lock, still binding the original pending release/image. Do not
overwrite release files. Preserve the same writer stop, env verification, failure
cleanup, runtime verification and acceptance protocol. Publish the infrastructure
hotfix only after the pending release has been accepted normally.
