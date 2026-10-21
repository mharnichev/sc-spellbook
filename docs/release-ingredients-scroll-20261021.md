# Shop Ingredients Scroll

Only Shop changes. Source `3453375e65cc3b3f4a42a562d60654dcde640e76`
updates product-page CSS: badge outside the scrolling viewport, long text starts
at the top, short text remains bottom-aligned, thin scrollbar and long-word wrap.
Script/template and payment, session, visibility and English logic are unchanged.

## Evidence

- Shop 172 tests, typecheck and build passed; no skipped tests.
- 18 offline browser cases: desktop, mobile and narrow; UK/EN; long, short and
  empty ingredients; native wheel reaches the end and returns to the start.
- Independent exact-source review: no findings.
- Linux Node 20.20.2 amd64, network disabled and read-only: 681 output files,
  54 HTTP assets and six SSR cases verified, zero business mutations.
- Built image repeated the same hash/SSR/CSS checks successfully before push.
- Immutable Shop digest:
  `sha256:9a31677eaf6f248998eddddf9fc35c69b9eb8e185b224d08e75a71d5968e5f9f`.

The separate English ingredients data operation already completed under the
normal production mutex with verified paired backup: dry 230, committed 230,
idempotent zero. All 279 original ingredients and the full 552-product source
vector were preserved. Do not repeat that operation during this image rollout.
49 English translation holds, nine original-source quarantines and 264 missing
source ingredients remain untouched. Private inputs/ledgers are not image assets.

## Acceptance

Require green infrastructure CI on the exact PR head before merge. Use the
normal frontend-only deployment; no migration or backend/reminder restart.
Preserve all other pins, environment bytes, closed customer-10 pilot and checkout
flags. Verify current release, all service health, exact Shop digest and unchanged
writer identities/start times. Check real long ingredients in Chrome at start
and end, UK/EN, desktop/mobile, without orders or notifications. No security/cache
policy changes or provider calls are part of this release.
