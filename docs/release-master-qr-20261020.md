# Scoped Master QR Release

## Authorization And Boundaries

The user authorized the prepared backend/admin Master QR flow and only
`can_record_sales` plus `can_accept_qr_payments` for the five currently active,
non-superuser accounts linked to masters. Other users, privileges and local WIP
must remain unchanged. Shop flags/profile/mode/pilot allowlist and the existing
product authorization/media fixes are not part of this change.

The user confirmed mono terminal MI057872 is linked to Checkbox register
4001546786 and approved tax code 8, unit `шт.` for these goods. Readiness may
perform SELECT, pure guards and a single merchant-details GET; never create a
real order, invoice, payment, receipt, shipment, OTP or notification, operate a
shift, send DPS commands, or fetch X/Z reports. Chrome/mono are root-owned.

## Source And Migration Gates

- Integrate only necessary Master QR runtime dependencies into clean checkouts
  based on actual released main, not wholesale dirty source copies.
- Preserve historical migrations 0131/0132 byte-for-byte. Add dependencies 0130
  through 0133 plus necessary forward 0134 canonical-key collation repair;
  verify upgrade/downgrade/upgrade on isolated production-locale PostgreSQL.
- 0133 refuses downgrade once durable live dispatch history exists. Never
  automatically downgrade production or roll an older image onto newer schema.
  Paired private DB/media backup, stopped writers and explicit recovery remain
  required. Financial history must not be deleted to make rollback possible.
- Exact integrated tests, independent source review, target amd64 image checks
  and successful exact-head infra CI are mandatory before rollout.
- Expanded testing found the same 16 financial guard failures on both the QR
  candidate and unchanged base 5fabbc585 at head0129. SQL canonical JSON used
  locale-dependent key ordering while Python hashes use codepoint order. Both
  production and fixture use en_US.utf8; changing the fixture locale or waiving
  baseline failures is not an acceptance path. Master QR reuses this canonicalizer,
  so forward migration 0134 is a necessary financial dependency with independently
  reviewed historical-hash compatibility and guarded downgrade tests.
- Only backend/admin image pins may change. Public-site, Blog, Shop, PostgreSQL
  and Caddy image pins stay byte-identical to release 763f53d.
- Run the private production-copy rehearsal with explicit
  `--source-head 0129_shop_ingress_limits`; the historical default remains 0110.
  The copied database must match `en_US.utf8` collation/ctype before migration.
  Preserve original row/sequence fingerprints and verify the upgraded archive
  restores with the same rows, sequences and finite schema contract. A successful
  empty fixture or zero orders does not waive this populated-copy gate.
- The unchanged backend comparator retains its 22 audited PostgreSQL 16 deparse
  pairs. Infra adds only the exact forward cast-array pair for
  `mono_checkbox_poll_state.ck_mono_checkbox_poll_state_mono_checkbox_poll_kind`
  introduced in 0132. Table/name/type/flags and both catalog definitions must
  match; every other field remains subject to the original comparator. The
  source metadata is deep-copied, never changed in place. The explicit pair and
  definition hashes are recorded, and raw schema still permits exactly one
  matching line replacement with no additional DDL differences. This is not a
  general SQL normalizer. A network-disabled fixture using the production PG
  digest reproduced both definitions and unchanged accepted/rejected values.

## Activation Protocol

1. Snapshot private server env and all existing boolean grants with the reviewed
   `scripts/activate-master-qr.py snapshot`. The same shell must acquire the
   normal release mutex, export `RELEASE_LOCK_OWNER_PID=$$`, then directly run
   the Python helper; do not use exec or an intervening pipeline subshell.
   Snapshot contains IDs/booleans only for grants, plus a private env backup.
2. Deploy compatible images/schema with all four working flags still false.
   The normal deploy must reach `pending_acceptance`, retaining
   `backend-recovery-required`. Verify paired archives and disabled-state guards.
3. Under the owning release mutex, set `EXPECTED_RELEASE` to that exact release
   and gracefully stop backend plus booking-sms-reminders with timeout 90.
4. Run `activate-master-qr.py apply <private-snapshot-directory>`. It requires
   exact pending backend marker/head0134, stopped writers, zero real POS and
   waiting real orders, zero durable create requests and unchanged env/grants.
   It stages/fsyncs env first, writes a durable activation recovery marker,
   changes only the two grants for the five eligible masters, then atomically
   enables MASTER_MONO_ENABLED, MASTER_MONO_INVOICE_CREATE_ENABLED,
   MASTER_MONOBANK_LIVE_TRANSPORT_ENABLED and MONO_CHECKBOX_AUTO_ENABLED.
   Shop settings and every other env line remain unchanged.
5. Keep both recovery markers through controlled startup of backend/reminders
   on the exact candidate images. Do not rerun deploy.sh or bypass either marker.
6. Verify health, image IDs, current background owner/lock, normal reminder
   utility, expected additional mono polling scheduler, actual master SELECT
   capabilities/denied catalog mutations, tax8 pure basket, unchanged business
   counts and one GET-only merchant readiness. No invoice POST is a smoke test.
   Root separately performs master Chrome acceptance without creating a sale.
7. Under the same owning-wrapper rules, use MASTER_QR_RUNTIME_VERIFIED=true and
   `activate-master-qr.py finalize <snapshot>` only after readiness succeeds.
   It removes only the activation marker. Then normal explicit infrastructure
   acceptance may remove the backend marker and switch current. Its new guard
   refuses acceptance while any activation marker remains.

## Interrupted Activation

The private snapshot includes the exact former grants and guarded rollback SQL.
An interruption leaves a phase-marked activation file plus the backend recovery
marker, with writers stopped until operator reconciliation. Do not blindly retry.
If no durable create request exists, the helper's explicit `rollback` mode may
restore only the known env/grants snapshots under the owning lock with writers
stopped. It rejects concurrent env/grant changes and retains the backend marker.
After real dispatch history exists, preserve schema/evidence and use a reviewed
roll-forward procedure; neither blanket env restore nor downgrade is automatic.

## Pre-release Evidence

Read-only production audit: head0129; five eligible linked masters with neither
grant; zero orders/payments/handovers/shipments. Positive unreserved stock: 436
products, 202 active. Configuration/profile fingerprints and approved tax policy
validated without printing credentials. Working flags remain off before release.

Private activation snapshot:
`/opt/soulcuts/backups/master-qr-activation-20261020T132537885785Z`.
No grants/environment changes were made while taking it.

Frontend source 9505a18b5973a2d41683c8149aa613e503ff1e71: eight backoffice paths;
589 unit tests, zero skipped, typecheck/build and independent image-build review
passed. Offline amd64 SPA startup/assets and frozen output identity passed:
`8a04d64bfe5c501fb58d7394f142fb2d02a6074bc1c9c75a6da38d37d45b053d`.

Activation helper PostgreSQL fixtures verify scoped grants, exact rollback,
partial failures after SQL commit/env replacement, stale grants, waiting real
orders, old schema, inactive Master cards, optimized Python, foreign locks and
dotenv ambiguity. All 102 infrastructure tests, including Caddy integration and
strict deparse negative cases, passed without skips on the final image pins;
exact-head CI remains required.
Backend source `681ee672356ff68589ab57f625da6bccfcad134b`: 44 frozen paths,
content SHA-256 `065d8fc457244f1074bd1ce473217ce679a615580e52af0b200de48280f51508`.
Final isolated suite: 778 passed, zero failures/skips, including all 219 targeted
QR cases and all 45 payment-resolution cases. Explicit
`0129 -> 0134 -> 0129 -> 0134`, static checks, protected-source hashes and final
independent combined source review passed. External dirty-source drifts were
documented, not imported or reverted.

Backend amd64 image is pinned in `versions/production.env`; all 411 runtime files
were verified against its exact source commit in a network-disabled container.
Head 0134, required imports and safe default flags passed without starting the
application lifespan. Admin digest is the previously verified frozen SPA output.
The five other image pins remain unchanged.

The actual production-copy rehearsal passed on PostgreSQL 16.15/en_US.utf8:
`0129 -> 0134`, 159 existing tables preserved, 172 upgraded tables restored.
Existing rows/sequences and restored rows/sequences are identical. The schema
passes the finite contract with only the one audited 0132 deparse pair; raw schema
is not byte-identical and is not claimed to be. Five prior-image core ORM model
reads passed on the copy; this does not approve automatic image rollback.
Private evidence: `/opt/soulcuts/backups/shop-rehearsal-28d633ca2063401492cd4fadc9ea4636`.
Source dump SHA-256 `d7a77db248989db1d30474fb1337a1f5916990ee8e8d5d0fa53bb6a199a3d126`;
upgraded dump SHA-256 `2db34bc5a89f0494acfe36f6367704aab26c1674244409660481c9e38e9f5864`.
The private copy stopped successfully. Exact-final-head CI remains required
before rollout; production flags/grants remain disabled until activation gates.

The first copy attempt stopped before migration because `SHOW lc_collate` was
not a recognized setting; current-database locale checks now read `pg_database`.
The second passed migration/data preservation but correctly refused the new
0132 deparse pair before its isolated proof/review. Both failed attempts remain
failed evidence in private backup directories; neither changed production.
