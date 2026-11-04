# Customer UI 0.4.2

This release replaces active report section placeholders with one four-ring SVG
compass and a progress bar based on the server's completed-section count. Partial
content remains available, terminal failures stop the animation, and opening an
existing report still defaults to its chart. Starting a report explicitly with a
card opens its reading progress. No new model or payment requests are introduced
by the animation.

The account, report list and checkout layouts have smaller vertical spacing.
Account quantities display as `2张` / `0张`, using the same 16px role as their
labels. The birth-date field labels are shorter; the calendar still accepts
solar/lunar dates and minute-precision times.

The backend product catalogue labels the double product `双人八字精批卡`.
New JSAPI prepay requests use `解读卡*1张`, `解读卡*2张` or `解读卡*5张` as
their descriptions, based on the order's stored card count. Existing historical
orders and issued prepay IDs are not rewritten. Product codes, amounts,
discounts, wallets and card accounting are unchanged.

## Deployment scope

- Baseline: deployed UI 0.4.1 plus the reviewed payment-account restriction.
- Keep payment mode `live`, new orders closed, and the test-account list intact.
- Back up affected sources, private configuration, current frontend, API image
  and MySQL before applying. Do not change private configuration.
- Build and validate a separate candidate API image before replacing the API.
- No database migration, worker restart or merchant API call is required.
- Retain old frontend assets; publish index/version only after new assets exist.
- An API restart invalidates existing in-memory admin sessions; sign in again.
- A rollback restores source, frontend entry points and the API image. It must
  not restore an old database over newer orders or reports.
