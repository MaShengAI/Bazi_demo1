# Free chart history and automatic WeChat login

Opening the customer app inside WeChat checks the existing session. If WeChat
login is enabled and the visitor is logged out, it starts OAuth with
`scope=snsapi_base`. Manual profile sharing keeps the configured scope.
The callback follows the scope actually granted by WeChat; base login does not
request profile data or erase an existing nickname/avatar.

Automatic login attempts once per tab until a successful session is established.
Explicit logout pauses automatic login in that tab; the login button remains
available. A non-WeChat browser does not automatically redirect. If storage is
blocked or OAuth does not establish a session, manual login remains available.

## Archive and unlock

- Authenticated `POST /api/v1/charts` calculates and saves an owned `charts` row.
  The result adds `saved_chart_id` and nullable `analysis_job_id`.
  With WeChat auth enabled, a missing/expired session returns 401 before saving;
  it cannot silently produce an unsaved guest chart. Auth-disabled local
  calculation remains supported without a database.
- `GET /api/v1/me/reports` lists up to 100 owned chart records, including free
  charts (`status=locked`, `job_id=null`). Legacy paid history is included.
  The older `/me/analyses` API remains available for job-only consumers.
- `GET /api/v1/charts/{chart_id}` restores basic chart facts and original birth
  calendar metadata for its owner. It never returns another account's data.
- `#/chart/{chart_id}` restores a free chart on refresh or from the report list.
  The report is one continuous page: birth facts, four pillars, luck timeline,
  then the eight locked reading previews. There are no chart/reading tabs.
- `#/report/{job_id}` shows the same chart facts followed by reading preparation
  or unlocked content on the same page. Reopening starts at the top; a new
  explicit unlock scrolls to preparation once its chart/result has loaded.
- Explicit card use calls `POST /api/v1/charts/{chart_id}/analyses`. The server
  uses stored birth facts, attaches the analysis to the same chart, and performs
  the existing card debit in the same transaction. A user-row lock serializes
  repeated free saves and unlock requests. Existing jobs are restored without
  another debit, including after model configuration changes.
- Free saving never creates analysis jobs/sections, calls a model, creates an
  order, or consumes cards/coupons. Login's existing new-account coupon rule is
  unchanged.

The existing tables suffice; no schema migration is required. Deploy both API
and frontend together. Previously calculated free charts that were never stored
cannot be recovered retroactively. Existing saved charts/reports are retained.

Tests: `tests/test_saved_charts.py`, `frontend/src/SavedReports.test.tsx`,
`frontend/src/wechatLogin.test.ts`, plus the existing auth/payment/customer flows.
Live phone WeChat OAuth must still be verified after deployment; local mock
authorization cannot validate WeChat's actual redirect/session behavior.
