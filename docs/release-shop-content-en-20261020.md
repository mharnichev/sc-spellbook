# Shop English Content Release

## Scope

Rebase the reviewed English content package onto payment migration
`0137_shop_online_payment`. The new nullable columns belong to migration
`0138_shop_content_en`. Preserve payment dispatch, canonical payment channels,
receipt reload behavior, financial snapshots, inventory, grants and the closed
customer-10 pilot. Do not send provider requests or create business facts for QA.

The content artifact is a private operator input, never a Git or image asset:
`prod-public-dynamic-en.json`, SHA-256
`992d43055f3266de376be3b85085078633c4b68c4c7412fba4681a155bd1110a`.
It contains 228 reviewed product identities and 287 non-null translated fields.
Only `description_en`, `short_description_en`, and `ingredients_en` are updated.
The new category description column remains null. Historical order snapshots
are not rewritten; optional current-product names are display projections only.

## Required Gates

1. Freeze clean production-based source; never package original dirty checkouts.
2. Run backend migration/content/payment/pilot regressions and independent review.
3. Run integrated frontend tests, type checks, builds and offline browser smoke.
4. Publish immutable image digests and verify their actual Linux runtime.
5. Rehearse production head 0137 to 0138 on an internal-network private copy,
   using `rehearse-shop-production-copy.py --content-input-dir ...
   --content-sha256 ... --source-head 0137_shop_online_payment`. Require exact
   source-column/sequence preservation, full English target-vector equality,
   upgraded archive restore equality and old-image read-only compatibility.
6. Require green mandatory infrastructure checks on the exact final PR head.
7. Use normal deployment backup, writer quiescence, migration and pending
   acceptance. An exit requesting manual acceptance is not release completion.

## Pending-Release Content Operation

Use `run-shop-content-backfill.sh` from the exact pending release under its
normal release lock. Supply `EXPECTED_RELEASE` and the exact
`EXPECTED_BACKEND_IMAGE`. `apply` accepts the owned private input directory and
the pinned SHA above. Preserve the returned private report directory.

The operator binds image, schema, input, source, complete existing data,
sequences, grants, environment bytes and tool hashes before writing. A durable
snapshot and recovery marker precede the single atomic CLI transaction. The
backfill verifies source raw/public CAS, rejects conflicting manual English,
checks idempotence and verifies the full product vector including unreviewed
products. Only then may the wrapper restart the two pinned writers without
pulling or rebuilding. All error/signal paths stop writers and retain fences;
owned labeled database tasks must also stop.

Do not modify environment flags, input hashes or deployed tools to force success.
Do not remove recovery markers by hand. A lost acknowledgement requires
`reconcile`, never a blind second apply. `rollback` restores only the complete
original content vector after whole-vector CAS and original-data checks; it is
not a database or application rollback. Durable rollback/finalization receipts
support acknowledgement recovery without repeating writes.

## Pre-Deployment Evidence

- Backend source `e6ddef435a75d046f690b636e5193c096d7ea42b`: 556 regressions,
  9 payment fault gates and 7 actual PostgreSQL adapter tests, zero skipped.
- Frontend source `3010b53c6d8e9fba0df4b6e6e140fbf54d4baaad`: Shop 172 tests,
  18 offline browser cases; admin 592 tests and 4 browser cases; type checks,
  builds and Linux runtime checks passed. Category illustrations and 404 are
  integrated without losing EN descriptions. Independent source review passed.
- Infrastructure: 247 tests passed, including actual Caddy and signal/task cleanup.
- Protected production-copy rehearsal:
  `/opt/soulcuts/backups/shop-rehearsal-edf6b43c5384419498084177e8892801`.
  Migration 0137 to 0138, atomic 228-product backfill, idempotence, full target
  vector, original rows/sequences, upgraded archive restore and old-image
  read-only compatibility passed. Both archive hashes were checked separately.
- ZSU SEO, input hardening, payment-label WIP and Dobrodesk/security changes are
  excluded. No policy, engine, secret, account, consent or pilot expansion.

## Runtime Acceptance

Verify actual container digests, schema 0138, healthy services, owner scheduler,
unchanged environment/pilot/grants/financial and stock facts. Check public EN/UK
description and ingredient display, null fallback, category routes, order-name
fallback and admin diagnostics without orders, payments or notifications.
Finalize the content marker only after explicit runtime verification; then use
normal backend manual acceptance. Final success requires current-release
promotion, absent fences, green final deployment/SEO and safe HTTP/browser smoke.
