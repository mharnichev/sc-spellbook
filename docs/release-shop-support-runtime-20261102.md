# Shop support runtime activation

Follow-up to release 20261102T135113Z-9a4e916. Its Shop image is healthy and
all other twelve services and unrelated environment files stayed unchanged.
Acceptance found that Compose's literal false overrode the approved shop.env
flag, so the widget was still disabled. Do not claim activation from env alone.

Remove only the Shop-level NUXT_PUBLIC_DOBRODESK_ENABLED false override. Keep
all image pins unchanged and let the existing env file supply the owner's
approved opt-in. Application default remains off when that key is absent.

The admin-shop guard permits only this exact unique line removal inside the
Shop block. All other shared configuration and image restrictions remain.
Positive, unchanged-pin and negative scope/configuration tests are required,
alongside synthetic Docker Compose enabled/unset runtime checks and full CI.

Deploy using the ordinary admin-shop pipeline. No backend/writer restart,
migration, order, payment, message, Sentry event or account change. Verify all
thirteen services healthy, the other twelve identities/start times unchanged,
approved env delta only, and actual runtime true before browser acceptance.

Recovery requires restoring the previous Compose override or the privately
backed-up Shop env value. Reverting only the image is insufficient to disable
the approved runtime flag. Never overwrite concurrent environment edits.
