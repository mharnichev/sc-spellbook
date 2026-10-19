# Monday availability release

## Scope and sources

- Backend source: `b203c0d3c323f8b1e025da949b381e885ed82014`.
- Frontend source: `cf498f731f2d24802c1b953eaa1b207c6dafdb60`.
- Remove the hard-coded Monday closure. Public booking still requires a
  published master window, working hours and conflict checks. Existing admin
  permissions and explicit overrides are unchanged.
- Align Ukrainian/English hours in barbershop, backoffice, Shop and Blog.
- Preserve the existing support sandbox/CSP, customer session isolation,
  checkout idempotency, pilot policy, noindex and root `/blog/` footer link.
- Exclude unrelated original working-copy changes, SDK updates and inventory WIP.
- No migration files change; head remains `0129_shop_ingress_limits`.
- Caddy and PostgreSQL engine pins are unchanged.

## Verification before rollout

- 254 booking tests passed against an isolated PostgreSQL instance, no skips.
- 134 additional pilot, ownership, scheduler, reminder and Telegram tests passed.
- The strengthened real PostgreSQL Monday test passed separately: unpublished
  window rejected, published window bookable, occupied slot rejected, later
  slots still available. No real SMS, OTP, orders or provider calls were made.
- Frontend: 543 backoffice tests plus a new Monday calendar test; 141 barbershop,
  142 Shop and 16 Blog tests passed. All-app type checks and builds passed.
- Independent read-only backend and frontend review found no runtime blockers.
- Chrome local smoke: rendered public/Shop/Blog pages and protected backoffice
  login redirect using synthetic GET-only API data. This is not a real purchase.

## Image packaging evidence

The admin image uses the repository Dockerfile. Public/Blog/Shop use the
already verified native Nuxt `.output` artifacts in the same `node:20-alpine`
runtime stage; slow emulated rebuild attempts were cancelled, not reported as
successful. Artifact-only contexts contain no source tree or host node_modules.
Blog runtime retains all three existing base URL/site/API environment defaults.

Read-only independent artifact inspection found no native executable formats,
native extension files or symlinks. Target images passed offline amd64 startup,
SSR, deep-link, asset-prefix and copied-file manifest checks.

Frozen output manifest SHA-256 (sorted relative paths plus content hashes):

- Public: `8ac302b464c9a64c29e7e5a4efea0b58a5979d80fe97cc745659d28a6541451c`.
- Blog: `db4f28faaca690fed791e3d3f0872868c9342845525259fea4cacf6ad43f249e`.
- Shop: `95b56d8e4e8673924ef2f829ea97c0b83fbf32da64ccc3bfc49802b2ed08c638`.

## Production acceptance procedure

Follow `docs/shop-pilot-release.md` and the existing deploy/accept scripts.
Changing the backend digest must use the full paired-backup, writer shutdown,
migration-readiness and manual acceptance path, even though schema is unchanged.
Do not force the frontend-only branch or clear a recovery marker manually.

Before cutover, production was on `56a2cfe`, schema `0129_shop_ingress_limits`,
with zero orders and SMS queue aggregate counts accepted=2955, delivered=247,
failed=20. These are observations, not an instruction to replay any messages.

Public checkout remains false; pilot checkout is restricted to customer ID 10
after normal authenticated/verified login. Financial, mock and shipment
transport flags remain unchanged. After rollout verify all eight image IDs,
the sole owner and expected scheduler set, the separate reminder process,
queue state and public SEO before accepting the exact release directory.

## Live acceptance and runtime correction

Release `20261019T124136Z-4fe5e42` reached the expected pending-acceptance gate.
The first complete SEO check found Blog sitemap HTTP 500: the native artifact
had the root site URL baked in. `NUXT_PUBLIC_BLOG_SITE_URL` is a Nuxt-config
build-time alias, while `runtimeConfig.public.siteUrl` requires the runtime key
`NUXT_PUBLIC_SITE_URL`. Initial home/deep-link/asset checks missed this sitemap
case; the offline image test was extended to request and validate the sitemap.

Under the release mutex, only Blog's private env received
`NUXT_PUBLIC_SITE_URL=https://soulcuts.com.ua/blog`, with an atomic write and
private backup. Only Blog was recreated from the exact pending release/pin;
the recovery marker was not changed or bypassed. This follow-up makes the same
runtime key explicit in Blog's Compose environment and adds a regression test.

After correction: both sitemaps and canonical redirects passed; all eight
image IDs matched; owner13 and reminder utility were healthy; schema remained
0129 and queue aggregates were unchanged. The paired backup at
`/opt/soulcuts/backups/pilot-BgeFUaZ1` passed private-permission, size and SHA-256
verification. Normal explicit acceptance completed for that exact release.
The follow-up has identical image pins and must use the frontend-only path.
