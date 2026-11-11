# Backoffice iOS Home Screen release

## Scope

Frontend PR https://github.com/mharnichev/sc-fe/pull/25 and the icon-cache fix
https://github.com/mharnichev/sc-fe/pull/26 are merged. Final source is
`1cb381669a756dda89762d497b4c6246219f3f94`.
Admin candidate: `ghcr.io/mharnichev/sc-fe/admin@sha256:5af7fac5cd967e908d1a635e14450141c7ab60aba1df1c6f993e4ea7749cf6f3`.
Built for Linux/amd64 from an archive of that exact commit.
Change only ADMIN_APP_IMAGE and its source comment; all other image pins remain
bytewise unchanged. No backend, migrations, writers, monitoring, credentials,
provider settings or environment changes are part of this release.
Do not merge unrelated checkout PR 41 or use its accounts/reminder work.

The app adds an origin-relative manifest (id/start_url/scope `/`), standalone,
logo-based 180/192/512px opaque PNGs with content-hash URL versions, safe-area protection, and manually opened
UK/EN installation help. Help is hidden on desktop and in standalone. No install
prompt is promised on iOS. No service worker, offline cache, writes/sync or push
is introduced; API/refresh are no-store and transport retries are disabled.
Network failure UI warns about stale data and uncertain in-flight outcomes.
Transient refresh failure preserves credentials; an unverified persisted identity
cannot enter the authenticated shell. Existing session revision guards remain.

## Verification

- 606 backoffice unit tests; typecheck; Nuxt production build passed.
- Eight mobile/desktop Chromium and four mobile WebKit checks passed, using only
  local mocked APIs. No real bookings, payments, email or accounts were created.
- WebKit used an isolated temporary Playwright 1.58.2/WebKit 26.0 installation.
  The project's 1.62.1/macOS14 fallback fails setup on PushAPIEnabled; no project
  dependency, global software or machine security changes were made. Same-origin
  mocks avoid Safari's restricted port9 and history checks await page readiness.
- Independent final review: no findings. sc-fe has no configured CI or required
  branch checks; local validation and the exact source commit are recorded.
- Require green Validate infra on the exact infra head, including native Caddy
  and monitoring integration; local conditional skips do not replace CI.

## Preflight and deployment

The observed previous release is
`/opt/soulcuts/releases/20261023T190454Z-ae269ed`.
Before release, current image IDs matched all eight services, release.lock was
absent and backend-recovery-required was absent. Existing environment-file
mtimes predated their running containers; no environment contents were exported.
Record protected service IDs/image pins before and after and reject unrelated
changes. Do not collect production env/credentials to prove this release.

Use the current Deploy production workflow and scripts/deploy.sh unchanged.
Its frontend-only path holds release.lock, runs read-only schema/owner/identity
checks, updates frontends with --no-deps and exits0. Backend/writers must keep
their identities. Do not invoke backend acceptance or clear recovery markers.
If this frontend release fails, inspect exact runtime state and use the current
rollback.sh with the explicit previous release above, identical backend pin and
normal lock/schema/owner/health gates. Never use an older script to bypass gates.

After success verify exact infra merge/deploy run, admin immutable image digest,
public HTTPS health, manifest MIME/identity/scope/standalone, Apple/PNG 200 and
pixel dimensions, no app SW registration, API no-store in served code and no
private data cache. Check unrelated public/blog/Shop/API health and unchanged
protected container identities. Do not create authenticated production records.

## Remaining physical-device smoke

Actual iPhone installation, system keyboard, notch/home indicator, populated
calendar/modals and long background/token expiry remain manual device checks.
Do not describe browser emulation as a real device installation.

Safari > admin.soulcuts.com.ua > Share > Add to Home Screen > Open as Web App
(if available) > Add. Launch Soul Cuts; internet is required and signing in again
may be necessary. Reference: https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios
