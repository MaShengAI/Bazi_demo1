# Checkout coupon selection

- The purchase page lists available coupons and their expiry times. Its initial selection follows the existing earliest-expiry recommendation; users can choose a different coupon or choose no coupon.
- An explicit selection sends `coupon_id` together with `use_coupon=true`. The server checks ownership, availability, reservation and expiry inside the existing user-locked order transaction. A rejected selection is never silently replaced by a different coupon.
- Legacy clients may omit `coupon_id` and keep the existing automatic selection behavior. `use_coupon=false` must not include a coupon ID.
- Prices are calculated in integer cents on the server. Existing minimum payment remains one cent: a CNY 88 coupon applied to a CNY 88 product discounts CNY 87.99.
- Pending orders retain their original coupon and amount. The checkout hides new package quotes until that order is closed or paid. Changing a coupon requires closing the pending order first; an eligible unspent coupon is released through the existing close-order flow.
- No schema migration or changes to weekly issuance, redemption rewards, refunds, payment callbacks or card grants are required.

Validation covers explicit CNY 88 selection alongside a CNY 50 coupon, no-coupon orders, retry identity, foreign/expired/used/reserved coupons, and eight simultaneous requests reserving the selected coupon only once. MySQL integration uses only the dedicated `bazi_payment_test` schema with the restricted `bazi_payment_tester` account; it must be run on the server before production deployment.
