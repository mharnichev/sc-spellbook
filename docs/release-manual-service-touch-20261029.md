# Manual booking service selection

Backoffice source: `8745697dfa37c50bc26e876ac1361a048591a506` (FE PR 38).

Keep the multi-select open when focus temporarily falls back to the page during
a touch interaction, before an option click. Outside pointer presses, focus on
another control, and Escape continue to dismiss it. No API or schema changes.

Verified: backoffice typecheck, 654 unit tests, eight mouse/touch e2e scenarios
at 390/1440 widths in both themes; infra 347 tests (8 skipped). The body-focus
regression fails before the fix and passes afterwards. This event sequence is
synthetic; Chromium touch is tested. Native WebKit cannot start on the installed
macOS 14 frozen engine due a Playwright protocol mismatch.

Update only ADMIN_APP_IMAGE. Preserve API, public/blog/shop, engine pins and all
runtime settings. Check the actual image, then production under an authenticated
master: select/deselect services in the manual-booking modal and verify the
summary and duration. Do not create a real test booking or send notifications.
