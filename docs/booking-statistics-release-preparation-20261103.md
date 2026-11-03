# Booking/statistics release infrastructure preparation

Base: infra main8e3ca87f958617a69513e76f6ce294a60159328c.
Preparation only: no production mutation, deployment, application source edits,
image build/publication or pin changes. Do not merge or deploy this draft before
the independently reviewed frozen application revisions and explicit release handoff.

## Infrastructure contract

- Backend candidate must expose exactly0145_booking_funnel_observations as its
  single Alembic head. Old0144, missing/multiple and unknown future heads fail
  the existing preflight before stopping writers or creating a recovery marker.
- Production-copy rehearsal targets0145 and names its upgraded archive0145.
  Existing0144 source copies remain supported, along with earlier approved
  baselines and their original RRP/reminder checks. Existing row/sequence,
  protected-history and restored-schema validations remain mandatory.
- New public-admin scope accepts only PUBLIC_SITE_IMAGE and ADMIN_APP_IMAGE
  changes, with byte-identical Compose/Caddy. It exports the immutable pinned
  references and invokes only pull/up --no-deps public-site admin-app.
- Shop/blog/backend/Caddy/Postgres pin changes, mixed scopes/selectors, malformed
  pins and shared configuration drift are rejected before Docker operations.
  No-op retries and single-image changes remain confined to the same two services.

## Required release sequence

1. Receive independently reviewed frozen FE/BE revisions and full test evidence.
2. Build exact Linux candidate images and immutable digests for isolated full-stack
   FE/BE E2E. Do not substitute previously promoted/nightly pins. Use disposable
   database/project/ports and synthetic data, without production credentials,
   real bookings, schedules, messages, payments or fiscal/provider actions.
3. Prove0144-to0145 upgrade preserves existing data/history and new backend
   remains compatible with the old frontend. Backend owner's image-smoke script
   still has an0144 target contract to update in its own application repository;
   release preparation must not edit that repository or weaken ledger checks.
4. After explicit handoff, fill only accepted immutable image pins. Deploy backend
   first with unchanged FE images via backend-admin scope. Retain paired backups,
   migration/readiness checks, recovery marker and authenticated manual acceptance.
5. Only after backend acceptance deploy accepted public/admin images via
   public-admin scope. Keep Shop/blog/other services and environment unchanged.
6. Verify physical-calendar monthly metrics, Kyiv clipping, funnel denominators
   and sample limits, booking availability/accessibility, owner/queues and safe
   public smoke. No production test writes. Do not clear a failed recovery marker.

Versions/production.env, versions/deploy.scope, Compose, Caddy and all app
repositories are intentionally unchanged in this preparation candidate.
