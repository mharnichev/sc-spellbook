# Shop Online Payment Release

## Scope

Publish the reviewed Shop, backoffice and backend image digests from
`versions/production.env`. The backend adds
`0137_shop_online_payment -> 0136_category_names_en`: immutable, one-shot invoice
dispatch provenance. Existing canonical Shop ledgers retain ownership of payment,
external mono/Checkbox receipt and physical fulfillment facts.

The customer initiates invoice creation explicitly. A redirect, browser query or
selected checkout method never proves payment. Backoffice uses the verified
`online_monobank` payment channel, not the mutable `card` method. The cabinet
keeps status and receipt visibility after payment normalizes the method to card.

Do not import unrelated dirty checkouts, input-hardening, Sentry, or the separate
dynamic-content translation package. Preserve the accepted English catalog,
Master QR configuration/grants, stock, media and all historical financial facts.
No account, role or consent changes. Public checkout remains disabled; the pilot
remains enabled with its existing single customer allowlist.

## Gates Before Merge

1. Freeze exact source and output manifests; independently review application
   and activation/recovery code. Pass backend, Shop and backoffice regression,
   types/build, offline browser and Linux runtime checks on the final snapshot.
2. Publish immutable images and verify their runtime files and source labels.
   Preserve all other image pins, including the production PostgreSQL engine.
3. Pass the protected production-copy rehearsal with explicit source head
   `0136_category_names_en`. Verify 136 -> 137, all original rows/sequences,
   upgraded dump/restore, and old-image read compatibility. A populated durable
   dispatch must refuse downgrade; never weaken that historical-data guard.
4. Require green mandatory CI on the exact final infrastructure head. Merge
   triggers the normal production workflow; do not merge before these gates.

## Deployment And Activation

The protected 136 -> 137 production-copy rehearsal passed with the exact backend
digest in `versions/production.env`: original rows/sequences unchanged, upgraded
dump restored with equal rows/sequences/raw schema, and previous-image read-only
compatibility passed. Private evidence is retained under
`/opt/soulcuts/backups/shop-rehearsal-935510ab0b9d4d339e228bc8409002da`.
The activation snapshot SQL was separately executed against PostgreSQL 16.15
at schema 137: 173 tables and all 140 sequences, repeated snapshots equal.
Candidate Settings/Gateway readiness passed with production configuration in a
network-none, read-only one-shot process; no environment or business data changed.

Normal deployment stops both writers, seals paired database/media backups,
migrates, checks pinned service health, and retains the backend acceptance fence.
It is not final acceptance. Do not rerun deployment while that fence is present.

Activation is a separate release-locked step. Use the reviewed
`run-shop-online-activation.sh` with the exact pending release and backend pin.
An owned private readiness proof binds the already verified merchant GET to the
existing Shop token fingerprint, intended merchant profile and original env hash.
No activation tool creates an invoice or calls a payment/fiscal provider.

Only the approved Shop feature flags, existing eligible operator ID, production
Shop profile and explicit tax policy may change. The profile uses the same
confirmed merchant, the existing Shop token, and external fiscalization enabled.
The tax policy is `{ "id": "soulcuts-shop-tax8-v1", "tax_codes": [8],
"unit": "\u0448\u0442." }`; it is an explicit mapping, not inferred VAT.
Never print or copy tokens into Git, images, command arguments or public reports.

Keep private, durable before/staged env snapshots and the activation journal.
Before replacing env, both writers must be stopped, the exact schema/pin and
existing operator must match, and pre-existing Shop payment history must satisfy
the first-activation guard. Verify all original database fingerprints and
sequences after the configuration-only change, then restart the same pinned
writers. Preserve both recovery fences through runtime acceptance.

## Safe Acceptance

- Verify all pinned service IDs/health, schema, single background owner, expected
  schedulers, normal reminder process and unchanged Master QR/pilot settings.
- Read local capabilities and payment status only. In Chrome, inspect the
  allowlisted customer's checkout method without submitting checkout or creating
  a payment link. If a temporary cart item is needed, verify no business side
  effects first and restore only that test item to the prior cart state.
- Confirm inaccessible payment IDs and query parameters cannot assert payment.
  Preserve the user's mono/Checkbox tabs and never read credentials or OTP.
- Do not create real orders, invoices, payments, receipts, DPS calls, shipments,
  notifications or shifts. Paid backoffice/receipt scenarios are covered by
  isolated fixtures, not fabricated production history.
- Only after successful runtime/UI verification finalize activation with the
  explicit runtime gate, then perform normal backend manual acceptance for the
  exact release. The activation receipt alone is not infrastructure acceptance.

## Failure And Recovery

Keep writers stopped, protected evidence and the backend fence on failure. Do not
automatically start old images or blindly restore a dump. Unknown invoice dispatch
owns its order until explicit GET-only reconciliation; another idempotency key is
not permission to repeat POST or release stock reserves.

Configuration rollback requires an unchanged database and exact before/after env
compare-and-swap. Restore only the known configuration snapshot, never financial
history or grants. A mixed or foreign state requires investigation.

Finalization writes and fsyncs its receipt before removing the activation fence.
After committed finalization with a lost acknowledgment, the fence may be absent:
preserve the receipt/backend fence, use fresh read-only recovery verification and
never recreate the activation fence or reapply configuration.

To stop new invoice creation while preserving existing reconciliation, use the
separate invoice-create switch through a reviewed configuration change. Disabling
online/link configuration also stops Shop polling and is not an equivalent pause.
No automatic X/Z import or reconciliation is claimed by this release.
