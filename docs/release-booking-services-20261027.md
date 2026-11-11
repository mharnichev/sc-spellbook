# Booking service editing fix

API source: `49801383b7dde66a7a83fe9c9ab09ede93695c1c` (BE PR 19).
Backoffice source: `3c5d328ae629db5f2ce1c071e766aa5a9b14795a` (FE PR 36).

Reload the booking's primary service and ordered service items after replacement,
before promotion validation and serialization. The previous loaded relationship
could retain old services despite committed replacement rows. Existing price,
promotion, ownership, completed-booking and availability safeguards remain.

Keep service selections after a rejected save, show localized reasons inline,
disable selection during saving and close unchanged selections without a PATCH.

Verified: API 177 tests including three real SQLAlchemy route regressions with an
existing promotion; frontend typecheck, 654 unit tests and 21 master editing e2e;
infra 347 tests (8 skipped). Verify service cases on the built image and production
with API mocks. No real test bookings or notifications.

Update only API/admin immutable image pins. No migration/dependency/config changes;
schema stays `0143_auto_checkout_checkpoint`. Preserve checkout closure, pilot
customer 10, approved two-hour reminders, scheduler ownership and monitoring.
Use paired backups, pending acceptance and exact-release verification. Compare
queue snapshots and environment hashes before accepting; verify operations watch.
