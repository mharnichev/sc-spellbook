# POS Role Pricing - 2026-11-20

## Release Scope

First stage changes only backend from5b37e104f tocb461c672. Backoffice follows
in a separate promotion after backend acceptance. All public frontend, engine
and unrelated image pins stay unchanged. No migrations, data backfill, existing
order repricing, settings/secret changes or actual payment tests.

Master POS basis is purchase cost times two, or supplier price times two when
cost is absent, followed by the existing optional ending-9 rule. Admin POS and
public checkout retain the shop-price basis. Automatic promotions, promo codes
and selected POS promotions remain active. Example on synthetic data: cost250,
shop720, master basis499; a10% promotion gives449.10 and a mock invoice44910.

Current POS offers, cart validation, quotes and locked preparation share the
same role basis. Existing expected-amount, quote-revision, actor-scope,
idempotency, QR/payment and recovery guards stay intact. Only admins receive
both comparative prices across POS/catalog/product/stock/barcode projections.
Ordinary operators retain their actual sale amount, not the salon comparison.

## Owner Packages And Verification

- Backend source cb461c672f48b45fe033e89b10366534b19bc044, sc-be PR46.
- Owner production-base package SHA256:
  a6c380228a1cb274324286dabeeb111c6cfa7020e29cde7503ada25c19b12fe1.
- Owner global-role delta SHA256:
  9f070e0e0de71017ed1aa06ec47afd14360abd639323f794c97c2f3ae8130431.
- Current-base integration and role gaps corrected by development owner;
  release chat did not rewrite application logic or copy dirty working trees.
- Final independent read-only review: no actionable findings.
- Exact Linux image CI44704425654 passed, including expanded pricing/POS/cart,
  catalog-role, Mono and public-Shop PostgreSQL checks with no skipped tests.
- Required broad backend CI44704428620 must pass before promotion. Its merge
  tree matches exact source0c524fdee7c29143b4d8dd062accf80054cec7ae.
- Compatible Backoffice candidate PR86 must pass all mandatory tests before
  starting this paired release. The first browser run44704448313 failed and is
  being diagnosed by the development owner; no fixture or auth guard bypass.
- User separately approved the minimal local TrashIcon correction that restores
  an existing Backoffice unit gate. All725 candidate unit tests passed.

## Production Gates

Preserve standard release lock/lease, writer pause, paired database/media
backup, migration readiness, recovery and acceptance gates. Acceptance is
server-side read-only; authenticated workflows use CI/staging test accounts.
Do not create bookings, orders, payments, fiscal receipts, shipments or notices
on production to test prices. Preserve exact existing checkout/pilot/session
protections, provider configuration and all other services.
