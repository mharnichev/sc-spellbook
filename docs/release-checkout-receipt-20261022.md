# Checkout receipt and payment UI release

User authorized this scoped production release on 2026-10-22. Prepared for sequential deployment; not accepted until the normal manual gates complete.

- BE main `db9f9d81c5ec4cfeb3ba76976e413f597a993050` (PR11), exact production dependency base retained. New callback preference defaults false for new Shop orders; historical rows stay NULL. Item photo URL/package variant are immutable order snapshots.
- FE main `a42f9c689875b298d438d01a73499bc0d21f42c9` (PR20). Frozen tested outputs from tree-identical `07bf3e9c054a998be901d2b4282d1280b0b351ad`; existing pinned Node runtime retained. Checkout borders/surface/official card indicators/status art, snapshot receipt reload and callback team visibility. Existing session guards/localization/pilot/payment creation-refresh behavior retained.
- Migration `0140_shop_order_receipt_snapshot` follows deployed `0139_shop_input_guards`. The old local draft0139 depended on unmerged reminders and is intentionally not shipped. No reminder implementation, sends, scheduler, configuration or enrollment is included.
- Only backend, Shop and admin pins change. Public/blog/Caddy/PostgreSQL pins, env files and feature gates stay unchanged.

## Evidence before rollout

58 backend focused tests pass. Two real PostgreSQL integration tests verify new false/true, stored item image/variant after catalog mutation and new-session read. A further 49 HTTP/checkout regression tests pass. Disposable local PostgreSQL rehearsal blank→0139→0140→0139→0140 preserves seeded historical order and NULLs, verifies three nullable/no-default columns. Previous production ORM reads the new additive schema. No shared database was used.

31 focused frontend tests, both typechecks and both production builds pass. Independent review resolved the /shop/ asset-base issue and found no remaining actionable issue. Actual Chrome smoke confirms official marks and both status images load under /shop/, with mobile/desktop paid/review states. Screenshots are local UI with mock API; no live order/payment was created. The unrelated unsupported method-change endpoint/modal was excluded.

Infra safeguards: 251 unittest tests pass (8 explicit integration opt-ins skipped locally); changed migration preflight contract has31 passing focused tests. PR CI runs configured Compose/Caddy validation and integration gates. Repository app CI has no workflows; this release records explicit local validation instead.

## Ordered production procedure

Recheck baseline current release, locks/fences, digests and health. The deploy workflow must use its release lock, paired DB/media backups and manifest, candidate module/head preflight, sole migration owner, then service health/image/background-owner checks. A backend change intentionally exits3 at pending acceptance and retains recovery marker. Do not blindly rerun or clear it. Read-only authenticated operations watch, queue/progress and preserved config checks precede exact-path accept-shop-pilot.sh. Do not create orders, payments, phone calls or notifications for smoke.

If any migration/health gate fails, preserve recovery marker and diagnose with the compatible candidate; image-only rollback across a schema change is forbidden. Additive schema allows the previous ORM to read, but old schema-readiness intentionally rejects the new head, so rollback is not an automatic recovery plan.

Production baseline: `/opt/soulcuts/releases/20261021T192401Z-c8671a2`; schema0139; eight healthy/running services; no release/recovery lock. Product/order/payment/queue counts and hashes retained privately in task evidence. Public checkout remains false; pilot enabled for the existing member only; online flags remain as configured. Admin operations-watch access must be available before starting the backend replacement.
