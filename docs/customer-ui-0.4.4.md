# Customer release 0.4.4

This cumulative release follows the deployed 0.4.3 refund-gift build.

- Automatic base WeChat login on entry and owned free chart archives; a free
  calculation appears in Reports before any card is used. Owner-only restore and
  explicit stored-chart unlock share the existing transactional card accounting.
- One continuous report: basic information, four pillars, luck timeline, reading
  preview/preparation/content. No chart/reading category tabs.
- Original twelve zodiac images in basic information, selected by the displayed
  lunar birth year (Spring Festival boundary), with the image left of birth facts.
- Consistent element colours, compact chart rows and typography, framed birth
  information and the three section headings; updated coupon labels and spacing.
- Silent account/report refresh with account isolation; removed redundant purchase
  history/continue-unlock/balance displays from the requested customer pages.
- Existing compass preparation and server-backed progress are retained.

No schema migration, worker restart, price change, payment/refund request or model
call is needed for installation. The API and frontend must be deployed together.
The installer validates the exact 0.4.3 runtime and static baseline, takes private
source/configuration/image/database/frontend backups, and preserves the current
live payment mode, paused new purchases, account restriction and enabled refunds.

Validation: 103 frontend tests, the complete backend pytest suite, TypeScript,
production build verification, and mobile viewport review. Live WeChat automatic
login and the free-chart history flow require phone acceptance after deployment.
SQLite/local tests do not replace the separate existing MySQL transaction tests.

Previously free calculations that were never stored cannot be recovered. Existing
stored charts, paid reports, orders, card balances and coupons are retained.

Rollback restores only code, the API image and static assets. It never restores an
older database dump, deletes financial records or changes payment/refund settings.
