# Shop Hero And Product Controls Release - 2026-11-28

Depends on infra PR147 public-only deployment completing successfully first.
This commit changes only Shop image relative to that accepted release and sets
admin-shop scope. Backoffice pin/config unchanged; confirm it is not restarted.

Source042ec03027256db79b4463ec9f0aa1f91e10311f; sc-fe PR95 merged to main.
Owner five-file UI patch: video hero with black brand strip, dark/hover logos,
updated copy, mobile height and photo pagination/control alignment. Owner
test-only followup adapts old absolute-layout assertion to the intended grid,
adds measured pill-bottom alignment, retains hit-area/touch/click/keyboard gates.

Linux CI46189156037 succeeded:413unit,13mounted Chromium/WebKit scenarios,
72mocked payment/Sale scenarios against exact Docker artifact and offline static
asset plus SSR404/noindex smoke. Local WebKit hang did not reproduce in Linux.
Digest af4f8cc5a53630add8f49cddea45aeb4c0e9ce3294b945191ce7a218f092ee09.

No backend/other image changes, runtime env, checkout/pilot/session protections,
roles or permissions modified. No production bookings, orders, payments,
receipts or notifications created. Preserve original dirty work and all WIP.
Read-only acceptance checks exact image IDs, health/schema/owner/reminders,
HTTP entry points, other service start times and protected env checksums.
