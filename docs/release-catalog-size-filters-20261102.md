# Development-owned catalog size filters

Backend PR: https://github.com/mharnichev/sc-be/pull/23
Source: 0fbe79fe6491266907be7ceb16036ebfde478030
CI: https://github.com/mharnichev/sc-be/actions/runs/41471152277 (SUCCESS)
Image: ghcr.io/mharnichev/sc-be/api-waitlist-20261031@sha256:6de02b21fdd8cb4223f105d5c3adcd019478b24dae6f4d0434609bd3eb59ca34

The backend owner prepared normalization of equivalent volume/weight filters,
unique product counts, numeric ordering and legacy slug aliases. Release owner
made no application edits. API schema and canonical migration head
0144_master_rewards are unchanged. No data backfill, account, env or pilot change.

Owner-local isolated unit/HTTP suite:41 passed,0 skipped. Required CI also ran
catalog/promotion/real PostgreSQL tests without skipped checks, then built the
exact Linux image and checked0143-to0144 migration, protected reward history,
API health and unauthenticated denial on an internal-only network. All passed.

Scope backend-admin changes only backend/reminder image. Admin image and all
other pins, Compose and Caddy stay unchanged. Run normal paired DB/media backup,
migration readiness and owner checks. Deployment deliberately stops at pending
manual acceptance; its exit3 is not permission to bypass the gate. Verify the
private paired archive manifest, authenticated watch owner/scheduler names,
read-only queue snapshots, reminder utility, live filter values and aliases,
then invoke accept-shop-pilot.sh for the exact release. No real test transaction,
SMS, email, fiscal action, shipment or provider request.

Private baseline and queue evidence:
/opt/soulcuts/backups/catalog-search-release-20261102.
Previous release:20261102T145627Z-6d9c85c. Recovery must reconcile schema, queues
and paired backup before any rollback; never downgrade or clear a recovery marker
without the prescribed checks. Retain prior Caddy-mounted release directory.

Full owner inventories confirmed no other ready backend changes beyond this PR;
main3431095f3 and prior prod781215ded have identical trees. Old root migrations,
disputed ingredients/ID45, stock visibility changes, local popular-product data
fixtures and obsolete auth/payment/cart implementations remain excluded.
