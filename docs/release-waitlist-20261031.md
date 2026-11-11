# Waitlist freed-slot correction

Backend PR: https://github.com/mharnichev/sc-be/pull/21
Source: `c1baf624f35e31491666ffdfb27c7153d1e47d3c` (based on main `1d0753d3`).

A partially overlapping booking edit previously queued the whole old interval after commit. The waitlist availability check correctly rejected that occupied snapshot. The correction offers only the released fragments, checks repeated processing under the master lock, and rolls back an occupied snapshot before changing a candidate or message. Booking overlap protection remains unchanged. PATCH conflicts occur before commit; post-commit background conflicts do not become a client response.

Local focused validation: 256 passed, zero skipped, including 14 real PostgreSQL tests. Tests cover unchanged/expanded edits, partial fragments, occupied snapshots, concurrent/repeated processing, rollback, eligibility after subsequent freeing, and existing expiry/claim/cancel races. Independent code/workflow review passed. Existing best-effort background delivery is not a durable outbox.

The exact-source image workflow requires the same regressions, Linux build, isolated 0143-to-0144 migration/protected reward history checks, API health and unauthenticated access denial before publishing its immutable digest. CI run https://github.com/mharnichev/sc-be/actions/runs/41244007845 passed all gates and published `ghcr.io/mharnichev/sc-be/api-waitlist-20261031@sha256:6a2754b4f2aa677da94af60d88d3fbb5580aa3da5f43aaf85c6bd53850de4314`. No migration, settings, frontend, engine or shared runtime change is included.

Keep existing `backend-admin` deployment scope: only BACKEND_IMAGE changes; the unchanged admin pin is reused. The normal script replaces backend and reminder writer with a fresh paired backup and schema/owner/image checks, then exits 3 pending manual acceptance. Other image pins and Compose/Caddy bytes must remain unchanged. Never retry through a recovery marker.

Before cutover record aggregate queue states, owner/scheduler state, reminder utility and current image/container identities via read-only checks; do not force customer messages or replay uncertain jobs. After startup verify actual image IDs, schema0144, expected effective schedulers, successive queue snapshots and single reminder loop; inspect existing booking/admin pages without creating or editing real records. Only then execute normal exact-release acceptance. Preserve Shop pilot/provider configuration. A successful deployment does not establish Sentry resolution; monitor the issue separately without claiming absence of future events.
