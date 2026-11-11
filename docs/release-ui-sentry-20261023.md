# Compact UI And Shop Sentry Release

## Scope And Sources

Frontend PR 24 is merged as `c5772dd3b2049e90989ec6d3292c5bb3f74905f9`.
Shop source: `811381bc304f4dba05d4e30a722dba0f47c1df80`.
Admin source: `bccb567a28ed0f461fc18bc7252954346c640abc`; its runtime,
package and lock inputs are unchanged by the final Shop-only commits.

Only Shop/admin image pins change. Backend remains on source `dac6010f`
and schema `0143_auto_checkout_checkpoint`; public/blog/engine pins, all env,
monitoring and database writers remain unchanged. There is no migration.

Ported compact product forms/details/gallery, catalog/recently-viewed layout,
checkout contact/summary layout, compact navigation and wrapping basket totals.
Shop Sentry is manual-only: no replay, tracing, automatic collection or default
PII. Events are reconstructed from safe fields, bounded and scrubbed; isolation
breadcrumbs clear when customer sessions change. Existing Shop env activates it;
no DSN or token is copied into release evidence.

## Preserved And Excluded

Keep public checkout disabled, private pilot enabled with customer `10` only.
Keep current session revisions, late-response guards, durable retry identity,
recovery fragment privacy and base-aware `/shop/` asset paths. Keep live checkout
service reminders and all current consents/provider settings unchanged.

Disputed compositions and hiding warehouse access from masters are excluded.
Payment-method switching is excluded because its public backend API is not in
the current production contract. Unverified delivery/return promises and stale
auth/backend/config variants are not ported.

## Verification

- 259 Shop and 603 backoffice unit tests passed.
- All four app typechecks and affected production builds passed.
- Six mock checkout/recovery scenarios, four catalog widths including malformed
  stored metadata/long labels, and three role-based catalog scenarios passed.
- Eleven mounted BaseMultiSelect/compact-form checks passed, including mobile
  dark theme, accessible help, price payloads and null/zero mapping.
- Independent reviews closed isolation-scope, malformed metadata and mobile
  overlap findings; a separate simplification pass added no abstractions.
- The installed Sentry SDK serialized scrubbed events through a memory-only
  transport, with no networking or production events.
- Infra unit tests: 347 run successfully, including eight conditional local Caddy skips;
  actual native Caddy/monitoring integration remains a required CI gate.

## Deployment And Acceptance

Use green checks on the exact infra head, immutable Linux image digests and the
normal frontend-only deploy path. No policy, runner, secret, backend env or
recovery-marker edits are authorized. Do not pause/restart backend writers.

Private before/after evidence is under `/opt/soulcuts/backups/ui-sentry-20261023/`:
all thirteen service health/identity/env hashes, schema/business-data hashes,
closed-pilot/reminder gates and exact image pins. Reject staged env drift.

After deployment verify source assets/MIME, authenticated product read/edit
initial values without saving, background ownership and unchanged protected
service identities/env/data. Do not generate real orders, payments, fiscal
documents, shipments, email, SMS, OTP or production Sentry test events.
This document is a runbook, not a substitute for successful CI/deploy evidence.
