# Booking time editing release

Frontend source: `af27834ab922b29aa56b6c57c77819ca89647dbe` (FE PR 35).
Backend source: `00e753f018eca310ca1ebde2c467ebb21cebbb05` (BE PR 18).

Synchronize start/end/duration, display start and end in one mobile row, preserve
rejected drafts and show localized errors. Allow an unchanged past booking start
when changing its end; newly selected past starts remain forbidden. Ownership,
completion, business hours, availability and overlap checks remain in force.
No dependencies or migrations change; schema remains `0143_auto_checkout_checkpoint`.

Validation: frontend typecheck, 653 unit tests, 19 mocked e2e scenarios; backend
174 booking tests and production-image import checks; infra 347 tests (8 skipped).
Run the linked-time e2e cases against the built image and production with API mocks.

Retain all other image pins, runtime flags, public-checkout closure, customer-10
pilot, approved two-hour reminders and monitoring. Use the paired backup/owner
fence and pending-acceptance procedure. Accept only after healthy services,
read-only queue and scheduler checks, authenticated operations watch, exact image
verification, and unchanged environment hashes. No real test bookings or messages.
