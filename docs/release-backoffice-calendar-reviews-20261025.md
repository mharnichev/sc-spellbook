# Backoffice Calendar And Reviews Release

## Scope

Frontend PR https://github.com/mharnichev/sc-fe/pull/27 is merged as
`eaae400acf4ee4056b25fca5323a8b84b957c844`. The tested branch tree is identical
to that merge. Only ADMIN_APP_IMAGE and its source comment change.
Admin image: `ghcr.io/mharnichev/sc-fe/admin@sha256:55aedccadf70ed6ef4c6d29cce711976945eef73e2893f5723c9c797b331f938`.
It was built from an archive of the exact merged source for Linux/amd64.
Offline SSR, compiled JS/CSS MIME, source label and unchanged runtime env passed.

Backoffice changes: arbitrary availability days with independent times, initial
day/master selection from bookings, compact calendar legends/personal matrix,
inline review approval, shared button loader and pending login controls.
Read-before-retry reconciles already committed availability intervals. Session,
unmount and route-leave guards stop later requests and stale UI updates; an
already transmitted request cannot be cancelled or undone by navigation.

Keep PWA manifest/icon cache versions, safe areas, offline warnings and session
protections. Keep warehouse visibility for masters and product compositions.
No other app, backend, schema, environment, monitoring or provider change.
Public checkout stays disabled; the private pilot remains customer 10 only.

## Verification

- 620 backoffice unit tests, typecheck and Nuxt production build passed.
- Nine integrated mock browser scenarios cover role-specific API endpoints,
  selected day/master, approval/error/refetch/unmount and duplicate login.
- Mounted availability smoke passed at 320px, 375px and desktop; eight Chromium
  mobile/desktop PWA tests passed. Physical iPhone testing is not claimed.
- Independent reviews closed initial-prop and navigation races. Retry, failed
  reconciliation, partial success, session switch and cancelled navigation have
  focused regression coverage. No real production mutations were used.
- 347 infra tests passed locally, with eight conditional Caddy integration skips.
  Require green Validate infra on the exact release head, including native Caddy
  and the actual isolated monitoring stack. Do not bypass these gates.

## Deployment And Recovery

Previous release: `/opt/soulcuts/releases/20261024T125948Z-fb37b21`.
Use the unchanged production workflow and frontend-only deploy path, immutable
Linux/amd64 admin digest and normal lock/schema/health/background-owner gates.
No migration, backend acceptance or writer restart is necessary or authorized.
On failure inspect runtime state and use the current rollback script with that
explicit previous release and the same backend pin; do not use older tools.

Private evidence is under `/opt/soulcuts/backups/backoffice-20261025/`: thirteen
service identities/health, env hashes, read-only schema/business-data checks and
pilot/reminder gates. Reject staged environment drift before compose up.
After success verify exact admin image, unchanged protected services/env/data,
public HTTPS/assets/PWA, and authenticated read-only calendar/review rendering.
Do not approve actual reviews, open actual availability, create bookings/orders,
payments, fiscal documents, shipments, notifications or Sentry test events.
