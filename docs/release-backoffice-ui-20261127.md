# Backoffice UI Release - 2026-11-27

Only Backoffice changes; keep all other image pins and shared/runtime config.
Source: 43302337a0f965cd4cdb45d2e70de39caad62919 (sc-fe PR #92).
Digest: sha256:3ad6d12392dfdcfbc3cd91d9857062df83cc3cc299420f280a1b2866384bce28.

Includes compact dashboard sections, no-slot history BaseTable, master profile
avatar/modal, loaders, general balance layout/filters and standard 32px buttons.
Owner fixed a reviewed keyboard focus escape with opt-in BaseSelect focus return
for three balance fields, preserving other controls and modal/session guards.

Exact-source Linux CI 46067705839 succeeded:
- types, 725 unit tests, production build and Linux image build;
- exact image artifact: 36 UI/booking/inventory, 100 POS/sales, 12 PWA tests,
  including WebKit; zero retries;
- immutable digest publication after all gates and preview cleanup.

Independent code review and re-review: no remaining actionable findings.
No backend/schema/API contract, session, role, Shop pricing or permission change.
All original dirty work excluded. Only the development-owner commits are used.

Deploy through the standard pipeline with admin-app scope guard. Read-only
production acceptance: exact runtime image IDs, health, schema/owner/reminders,
admin login HTTP and unchanged non-admin start times and env checksums.
No production orders, payments, receipts or notifications used for tests.
