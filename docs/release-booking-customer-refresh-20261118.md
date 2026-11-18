# Booking Customer Refresh - 2026-11-18

## Scope

SOULCUTS-API-G: preserve the eagerly loaded customer when service updates
refresh Booking with populate_existing=True. One application line adds
selectinload(Booking.customer), avoiding MissingGreenlet in the response path.
No permissions, pricing, promotions, availability, API or business-rule changes.

- Verified production base: e6d1e199365d48868c4d17331cfd30c889cd3ffb.
- Candidate source: 5b37e104fc36eafad70017933eaef444e4fcc32f, sc-be PR 45.
- Exactly two source paths: app/services/booking.py (+1 line), and
  tests/test_booking_service_update_async_integration.py (15 async HTTP cases).
- Owner patch SHA256:
  ffdbba0cdf4487ee4ce7a51753546449f98acf55e90af7a4b60ed7d84781b846.
- Only the backend image pin changes; all frontend/engine pins are preserved.
- Schema remains 0167_product_usage. No new config, migration or data backfill.

## Evidence And Required Gates

- Owner red: four MissingGreenlet failures on the original production source.
- Owner green: 18 targeted tests and 81 promotion/first-visit tests, no skips.
- Owner migration round trip passed; independent read-only review: no blockers.
- Exact Linux image CI 44273807701 passed, including migration/API/image smoke.
- PR merge tree equals exact source tree:
  889915957e9e1a5c30f773beb41ba058330ed3db.
- Required broad Linux booking gate 44273812024 must be fully green before
  promotion. Interrupted/partial local runs are not counted as passing.
- Standard release lease, writer pause, paired DB/media backup, readiness,
  recovery and acceptance guards are unchanged.
- Production acceptance uses server-side read-only runtime and log checks.
  Do not patch a real booking or create orders, payments, receipts or notices
  for smoke. Existing session and checkout/pilot settings stay unchanged.
