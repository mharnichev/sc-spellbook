# Backoffice Pricing Stage - 2026-11-20

Promote only Backoffice after successful backend pricing acceptance. Required
backend source iscb461c672; this release keeps that backend pin unchanged.
Shop, Barbershop, Blog, engines, secrets and runtime flags are unchanged.

- Backoffice source:b34cfbd0c939e85af89951aa7f00f6c9b2c9ad0e, sc-fe PR86.
- Exact Linux type/unit/build/image/browser CI44708961514: success.
- 725 unit tests passed. Exact-image browser gates:17 booking/inventory,
  100 POS/sales,12 PWA including mobile Chromium and WebKit, all passed.
- Owner mock connected smoke on clean production bases verified master499,
  a10% promotion449.10/mock invoice44910, and admin shop-basis720.
- Final independent source review: no actionable findings.

Owner-prepared current-base UI deltas cover current POS search, details, cart,
product pages and inventory surfaces, preserving sessions and existing actions.
Only admins compare both price fields. Masters see their server-owned salon
price. Ordinary operators retain their actual sale price without comparisons.

User separately approved the minimal existing local solid TrashIcon correction
in General Balance; deletion handlers, texts and access rules are unchanged.
Pre-existing test drift was fixed by the owner: seven synthetic profiles gained
their required email, and a PWA test checks the current accessible navigation
dialog instead of its old DOM ID. Assertions were preserved/strengthened; no
app/auth/session/PWA guard or test was disabled. All full gates were rerun.

Only the admin image pin changes, using standard admin-app scope. Do not merge
before backend deployment44710554227 is accepted. Verify exact running revision,
all service health and unchanged backend/writer start timestamps after promotion.
Use read-only production acceptance, never a real payment, receipt or test order.
