# Customer typography

`frontend/src/typography.css` owns the customer application's font rules. Layout
styles in `customer.css`, `CardShop.css` and `LuckTimeline.css` no longer assign
individual fonts. Rules are scoped under `.customer-app`; the independent admin
application is outside this change.

| Role | Size | Usage |
| --- | --- | --- |
| Brand | 32px | Measure and report-list mastheads |
| Page | 24px | Other page names and the account nickname |
| Heading | 20px | Cards, reading sections and dialog headings |
| Body | 16px | Reading text, fields, buttons, tabs and directory labels |
| Metadata | 13px | Dates, status, captions and dense chart facts |

Headings and reading paragraphs use a shared Chinese serif fallback stack;
controls, dates and ordinary interface text use the shared system sans stack.
Normal weight is 400 and emphasis is 500. No external fonts are downloaded.
Body line height is 1.6, metadata 1.7 and reading paragraphs 1.95.

Explicit data exceptions are 26px pillar symbols, 32px account counts/package
prices, and 48px coupon face values. Timeline glyphs reuse the 20px heading role;
their ten-god labels and chart shen-sha use the 13px metadata role.

Text does not shrink at small breakpoints. Long packages reflow vertically below
360px; date wheels allocate extra space to the year and lunar month. Scrollable
wheel rows retain their 44px geometry, so changing typography does not alter the
selected date. Report metadata wraps rather than overflowing a narrow column.

Verification: production build, all 75 frontend tests, and browser checks on
320px/390px customer pages. The browser checks include a long leap-month label,
available coupon, canceled deletion dialog and unobstructed reading shortcuts.
No server deployment, payment, report generation or record deletion is performed
as part of these typography checks.
