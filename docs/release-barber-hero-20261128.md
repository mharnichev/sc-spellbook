# Public Barbershop Hero Release - 2026-11-28

Image source 1f52c3df857c082a7f387e95f9a96e3c0ca1dd54; sc-fe PR96 targets
frozen exact production base508540f, not main. Main lacks active production-only
mobile bottom bar and Dobrodesk lifecycle. Both remain byte-identical here.
Runtime diff: outer90vh mobile /100vh md+, remove conflicting inner100vh.

Development owner supplied runtime fix and geometry regression. Independent
review/re-review found no remaining actionable issues. Owner test-only followup
identifies lazy rating CSS separately from shared recruitment modal CSS.

Linux exact-source CI46189217835 succeeded: types,173unit, production/Linux
image build,12booking browser scenarios, full homepageSSR/no-JS/hydration/
sliders/anchor checks. Hero measured375x667 and1440x1000. Immutable image digest
sha256:2ea02187e4497e1d2d2a7aeebcdf52586973e49dec0dfd129aa42a168693ba51.

Only PUBLIC_SITE_IMAGE changes. Existing public-admin deployment scope retained;
Backoffice pin and configuration unchanged. Confirm no Backoffice or other
service restart with read-only acceptance. No env/checkout/session/role changes,
no real bookings/orders/payments/notifications during testing.
Shop update follows in a separate scope-guarded image-pin release.
