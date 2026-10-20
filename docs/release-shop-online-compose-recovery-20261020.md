# Shop Online Compose Recovery

## Failure

Release `20261020T183341Z-5326656` reached schema 137 and pending acceptance.
Guarded environment activation completed with the approved Shop settings, but
three backend Compose environment entries forced `false` over the env file:
`SHOP_ORDER_OPERATIONS_ENABLED`, `SHOP_PAYMENTS_ENABLED`, and
`SHOP_MONOBANK_LIVE_TRANSPORT_ENABLED`. Local capabilities correctly returned
`enabled: false`; Chrome did not display the online-card option. Neither
activation nor infrastructure was falsely accepted.

Only those three overrides are removed for future releases. Public checkout,
internal Checkbox, sandbox, mocks, returns and unrelated switches remain pinned
closed. The existing singleton pilot is still customer 10. No image pins change.

## Recovery Gates

The old pending release, activation journal and hashed tools are immutable.
Require independent review and green CI on the exact recovery source before
executing a private snapshot, even though its PR cannot be merged/deployed while
the older release is still fenced.

Use the separate release-locked recovery tool against that exact pending release
and backend digest. Bind the original Compose, desired env, activation state and
reviewed recovery tool hashes. Persist the private journal and three-value
overlay durably. Compare complete resolved Compose JSON: the only allowed delta
is the three backend values `false` to `true`. Never dump resolved configuration
or secrets into public logs.

Stop both writers, take fresh read-only snapshots and preserve grants/operator,
schema and financial facts. Legitimate activity since activation must not be
erased or mistaken for an unchanged whole-database baseline. No Shop order,
payment, invoice dispatch, confirmation or receipt may exist for this recovery.
Recheck bindings immediately before pinned no-pull/no-build restart. On failure
or unknown acknowledgment retain both fences and inspect actual state instead
of blindly repeating restart. No env rewrite, migration or business operation
belongs in this recovery.

## Acceptance Order

1. Verify actual running container images and environment, local capabilities,
   health, owner and scheduler names. The pure Settings check alone is not proof
   of Compose precedence.
2. In Chrome inspect the allowlisted customer's online-card option without
   submitting checkout, invoice creation or payment. Restore any temporary cart
   item and verify zero orders/payment/receipt facts.
3. Finalize the original activation with explicit runtime verification, then
   perform normal backend acceptance for the old pending release.
4. Only then merge this Compose hotfix and run its normal frontend-only workflow.
   Compare backend/reminder container IDs, environment and start times before
   and after: this follow-up must not restart either writer.

Until that final hotfix is accepted, retain the private overlay and do not run
ordinary recreation/deployment from the old Compose file: it would force the
three flags closed again. Never clear either acceptance marker manually.
