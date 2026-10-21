# Remaining Input And Locale Release

Integrate positive, independently reviewed changes onto current main, never
publish the stale original working trees. Exclude ingredients/parser/data,
barber inventory navigation, session downgrades and old asset/routing changes.

## Scope And Compatibility

Shop input controls and API validation, public source/subject admission, exact
six-digit OTP validation, integer quantities, UK/EN payment copy, and the
barbershop SDK type dependency 0.3.2. Existing cross-origin support sandbox,
hosted provider loader and CSP stay unchanged; dependency tests do not prove
operator realtime delivery. No provider conversations are sent for acceptance.

Backend migration 0139_shop_input_guards follows 0138_shop_content_en and only
expands the existing admission action CHECK. No business table or composition
is updated. Existing admission identities/counters remain valid; the independent
bounded admission pool prevents nested business-pool starvation. Confirm DB
connection headroom and run actual two-instance concurrency tests.

Public mutating Shop requests have a 64 KiB body cap, including streamed and
dishonest Content-Length requests. Accepted bodies are replayed byte-for-byte.
New checkout validation runs after historical intent lookup; client retries
retain their saved key/body and existing session ownership guards. Email must
be rejected rather than cleaned into another recipient. Fractional or cleared
quantity drafts cannot become zero/removal. Preserve native numeric types and
IME composition; invalid pasted OTP must not turn into a valid six-digit code.

The OTP default glyph remains one UCS2 segment with a generated six-digit code.
Do not change production template overrides or send real SMS for tests.

## Required Gates

Frozen backend source `0a4ff219c2d16b280000e8b7f32101729ec0e23a` contains
30 scoped paths, with 722 other files verified unchanged. Source manifest:
`a78279df8678b58fbd083ef9f883b4cb592861e509157f9beab245841d52e8ea`.
Frontend source `4df7b756dffe21f140b81cab081e7693a5d8e173` contains 27 scoped
paths, with 1919 other files verified unchanged. Source manifest:
`ecfea5ad7c8047ca52eb0d405b6da6e2ea1e06bb2dee267030f2a01236b6a860`.
Independent source reviews found no remaining findings on these frozen inputs.

Backend verification: 369 contract/OTP/payment/owner/English tests and 237
input/DB/checkout/pilot/replay tests passed, zero skipped. The real migration
roundtrip retains original OTP/checkout counters. Earlier ENOSPC and invalid
synthetic digit-name fixture failures are retained, not counted as passes.
Only the synthetic names changed; all last-unit race/stock assertions remain.
Frontend: 209 Shop and 145 barbershop unit tests, types/build, 36 desktop/mobile
checkout/input and four offline payment browser cases passed. Actual frozen
Linux images verified 426 backend runtime files, 405 public output files and
676 Shop output files; read-only/network-none checks caused no business writes.

Published immutable backend/public/Shop digests are pinned in production.env;
admin, blog, Caddy, PostgreSQL, deployment policy and provider configuration
remain unchanged. A read-only preflight found zero production orders/intents,
so the size cap cannot invalidate a pre-existing accepted Shop retry here.
This is rollout-specific evidence, not a claim about importing legacy intents.

The first production-copy run stopped at schema comparison, not a production
migration: native PG16 IN and restored pg_dump expressions deparse their array
casts differently for the expanded admission CHECK. Both exact raw definitions
were collected from that copy. A network-none disposable PG16 reproduced those
bytes and both pretty definitions, accepted the same eight actions and rejected
three invalid actions. The comparison permits only that exact object/definition
pair, preserving type/flags/validation, all other schema bytes and the original
finite comparison. Reverse/near matches, ANY-to-ALL, changed/missing actions,
duplicate identities and unrelated raw DDL remain rejected. Re-run full tests,
independent review, exact-head CI and the complete production-copy rehearsal;
the earlier failure is not successful restore evidence.

Run frontend suites, types/build and offline desktop/mobile browser regressions,
including checkout/retry/locale/payment-channel/receipt and sandbox boundaries.
Run backend schema, validation, migration/downgrade/upgrade, source/subject/cart
concurrency, closed-pilot, payment and owner/startup regressions on owned local
PostgreSQL. Keep all failures and their fixes visible; do not waive assertions.
Obtain independent review and bind the final source to immutable Linux images.

Rehearse production-copy 0138 to 0139 with the new exact backend digest:
original rows/sequences unchanged, restore archive equality, read-only previous
image compatibility and exact-head readiness. Do not reapply any English or
ingredients backfill. No external provider network is available to rehearsal.

Require green mandatory CI on the exact infrastructure PR head before merge.
Use normal writer quiescence, paired DB/files backup, migration and pending
acceptance. A workflow exit requesting manual backend acceptance is not success.
Verify exact images, schema, all healthy services, authenticated owner scheduler
names/progress, reminder utility, environment hashes, closed customer-10 pilot
and unchanged product ingredient fingerprints. Only then use the normal exact
release manual-acceptance gate and run final public SEO/HTTP/Chrome smoke.
Never remove fences manually or create real orders/payments/checks/shipments,
OTP, notifications, accounts, roles or consent changes for QA.
