# Checkout Reminder And Shop Price Release

## Approved Scope

The owner explicitly approved live service emails two hours after a new,
deliberate unfinished-checkout checkpoint. Existing checkout restrictions remain:
public checkout disabled, private pilot enabled, customer allowlist exactly `10`.
No historical cart enrollment, test emails, orders, payments, receipts, shipments,
OTP, production Sentry events, role changes, or consent changes are permitted.

The owner explicitly approved initializing independent `shop_price` from
`COALESCE(recommended_retail_price, price)`: 550 of the existing 552 storefront
prices change; two legacy zero prices remain valid. Supplier prices and RRP
remain unchanged. Subsequent supplier imports preserve the independent price.

Backend migration chain: `0140_shop_order_receipt_snapshot` ->
`0141_product_shop_price` -> `0142_checkout_reminders` ->
`0143_auto_checkout_checkpoint`. No previously released migration is edited.

Frontend scope: independent backoffice shop price, canonical public price DTO,
automatic checkpoint/recovery/cancellation, Base price controls, discount artwork,
and existing localized payment/delivery terms drawer. Broad product-form/layout
WIP, disputed product compositions and warehouse-role hiding are excluded.

## Safety Gates

- Defaults in source and example env remain OFF with dry-run ON.
- Production activation changes only the approved reminder keys, with a private
  env backup, exact baseline hash, preservation checks and atomic replacement.
- Reminder admission and dispatch enforce actual verified pilot membership.
  Neither an email match nor a recovery link grants account access.
- Recovery fragments are removed before third-party integrations, under both
  root and `/shop/` base paths. Recovery cannot replace a cart while a durable
  uncertain checkout intent remains unresolved.
- Unsupported recipient addresses terminate only their own reminder; operator
  configuration failures do not consume a durable delivery attempt. Ambiguous
  SMTP outcomes remain quarantined without automatic resend.
- Existing session guards, private Sentry incident storage, Shop Sentry runtime,
  monitoring containers, provider settings and all unrelated env are preserved.

## Verification And Deployment

Frozen sources: backend `dac6010f5aa7e76216e01debac74ce5dd721453b`
(PR 13, merge `46ece4bfbe33d666a6a9b37edbade6f03e337302`), frontend
`5176f58bee1415a957e21a4457c45b544a349e0b` (PR 22, merge
`e16cea8893a984c0ddec24f065d6515ef4f37c86`). Only backend, shop and admin
image pins change; public-site, blog, Postgres and Caddy pins stay unchanged.

Final local evidence: 360 backend exact-image tests passed, no skips; 834 Shop/
backoffice tests passed; 6 mocked browser scenarios passed; all four frontend
typechecks passed; affected production builds and network-isolated image SSR/
PNG checks passed. Infrastructure: 347 tests passed with 8 local conditional
Caddy skips; CI must execute its actual native Caddy gates. Independent review
closed both queue-starvation and uncertain-intent recovery findings.

Private server evidence for the deployment is stored in
`/opt/soulcuts/backups/remaining-shop-20261023/`, never in Git. It contains the
pre-release service/config/data baseline, approved-env hash ledger and private
env backup, exact-image manifest, and pending/accepted/follow-up comparisons.
The rehearsal prints its own private backup directory. None of these planned
acceptance phases is implied complete merely by publishing this runbook.

Exact candidate provenance: 440 runtime files match the frozen backend source;
all 51 installed runtime distributions match the previous production image.
Successful private production-copy rehearsal:
`/opt/soulcuts/backups/shop-rehearsal-6a2dec3c346844a69cef2821c11b4212`.
This includes the two exact PG16.15 CHECK deparse pairs for the reminder state
and expanded ingress actions, with strict metadata/raw-DDL checks retained.

Local checks include disposable PostgreSQL HTTP/order/import/concurrency tests,
fake SMTP lifecycle tests, Sentry regressions, all affected frontend unit/type/
build checks, and mock desktop/mobile browser checks without external mutations.

Before deployment, rehearse the exact candidate against a private production
copy with every email/reminder switch OFF and no provider credentials. Verify
RRP backfill, an empty reminder table, original-column fingerprints, sequences,
upgraded dump/restore, finite schema equivalence and previous-image core reads.

Publish exact-source Linux images with immutable digests. Require green infra
checks on the final head. Use the normal deployment writer pause, paired database
and upload backup, migration, health/digest/owner checks and manual acceptance
fence. Do not remove a recovery marker manually. A successful follow-up deploy
must not restart the newly accepted backend writers.

SMTP acceptance is TLS/AUTH/NOOP only: never MAIL/RCPT/DATA. Verify actual PNG
logo bytes and a representative public product image. Production verification
is read-only; natural user events after activation are not synthetic smoke tests.
