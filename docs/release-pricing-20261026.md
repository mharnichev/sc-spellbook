# Conservative Shop Pricing Release

## Scope

Backend source `5236980d58c54e9b7d8d7325f5835c64430e037c` adds an optional
Decimal recommendation and an audited operator-only CLI; no runtime endpoint,
dependency, scheduler or migration changes. Frontend source
`fa1ee20c26e66bce64b535e49838545dca8c9825` adds an explicit apply suggestion to
ProductForm on current main, preserving the released calendar and theme.
Keep public-site, blog, Shop, engine and monitoring pins unchanged. Preserve
session protection, closed Shop pilot/customer 10, Sentry privacy/durable storage,
and existing live approved two-hour reminders. Exclude disputed compositions,
warehouse visibility and other WIP. No real test orders, payments, documents,
shipments, OTP, notifications or production Sentry events.

## Price Policy And Data Gate

Suggest the nearest lower whole-UAH price ending in 9, never increase, reduce
by no more than 2%. Manual entry remains allowed. Only shop_price and its ORM
updated_at change; supplier/base price, RRP, inventory and historical orders stay
unchanged. No invented discount or reference price is created.

Production preview: 552 products; 443 reductions; maximum 9 UAH; no resulting
price below stored base; two existing zero prices unchanged. Store the complete
private preview and before/after fingerprints under
`/opt/soulcuts/backups/pricing-release-20261026/`.
After release acceptance, take a fresh verified database backup, then apply with
the exact reviewed preview. A five-second bounded table lock prevents product
write/insert races. Any identity/price drift refuses the update. The precommit
intent report and directory are synced. Report existence is not commit evidence;
verify every persisted value and idempotence after success or ambiguity. Never
blindly repeat an uncertain update or restore an entire live database.

## Verification And Release Gates

84 focused backend tests passed using isolated PostgreSQL, including drift,
audit-write/sync and commit failures, unchanged stock/base/RRP and idempotence.
649 backoffice tests, typecheck, build and mock-only browser checks passed.
Backend source bytes/dependencies match commit/runtime; admin output has 305
matching files, manifest SHA256
`ac1a1e27c659e6b0966018d4040b5ba8206ee140a035d0e6dd71977c67f36f1a`.
Production-copy backup/restore/schema/old-image rehearsal passed at
`/opt/soulcuts/backups/shop-rehearsal-b5c89fd0022145a687c8e10117825acd`.
Schema stays `0143_auto_checkout_checkpoint`.

Require independent review, exact-head green infra CI and immutable digests.
Use normal backend deployment with writer grace, paired backup, schema/owner
checks and retained manual-acceptance marker. Before acceptance verify existing
authenticated diagnostics, schedulers, queues, reminder health, all 13 services,
unchanged env and data fingerprints. After acceptance finish the existing CI
workflow without another deployment. Price update has a separate fresh backup
and exact-value verification. These gates are requirements, not completion claims.
