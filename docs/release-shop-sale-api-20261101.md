# Sale API Release

Backend source: 781215ded85b7374a37d5138dee3df906cc74479, BE PR 22.
Image and PostgreSQL CI: 41348080271, successful with 137 tests and no skips.
Independent review found no issues. No migration is added; schema remains 0144.

Only the backend pin changes. Existing backend-admin scope preserves mandatory
writer quiescence, paired database/media backup, schema/image/owner checks and
explicit manual acceptance. The admin image and all other pins, Compose and
Caddy bytes remain identical. No production environment values are changed.

Acceptance must verify the authenticated operations watch (15 running scheduler
names observed before rollout, no owner error), queue state, reminder worker,
paired backup integrity, closed pilot and exact image identity. GET Sale API
smoke checks discount membership, pagination and category facets. Do not create
orders, payments, invoices, receipts, shipments, notifications or Sentry events.

The public Shop quote request currently traverses the barbershop BFF, which
intentionally drops Authorization. A separate frontend/ingress release will
route only the exact public quote endpoint directly; do not broaden BFF auth
forwarding or expose other promotion/backoffice routes.
