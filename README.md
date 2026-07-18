# Revenue Audit

A monorepo revenue reconciliation app with a Python API backend and a React + TypeScript frontend styled with shadcn-inspired components.

## Structure

```text
backend/   Python API, SQLite persistence, auth, CSV import, reconciliation, LLM explanations
frontend/  React + TypeScript + Vite dashboard
```

## Run locally

Backend:

```bash
python backend/app.py
```

Frontend, in another terminal:

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173`, sign up, then import `orders.csv` and `payments.csv`.

Useful checks:

```bash
python -m py_compile backend/app.py backend/scripts/analyze_data.py backend/scripts/smoke_test.py
python backend/scripts/smoke_test.py
python backend/scripts/analyze_data.py
npm run build
```

## Environment

Copy `.env.example` to `.env` for deployment or local process configuration.

- `APP_SECRET`: long random value used to sign session cookies.
- `DATABASE_PATH`: SQLite file path, used when `DATABASE_URL` is not set. Defaults to `./backend/revenue_audit.db`.
- `DATABASE_URL`: optional Postgres connection string (e.g. a Neon project). When set, the backend uses Postgres instead of SQLite. Local dev and the smoke test leave this unset and use SQLite.
- `FRONTEND_ORIGIN`: allowed browser origin for credentialed CORS. Also controls the session cookie: an `https://` value switches it to `SameSite=None; Secure` for cross-origin deployments, otherwise it stays `SameSite=Lax` for local http dev.
- `EXTRA_ALLOWED_ORIGINS`: optional comma-separated extra origins to allow (rarely needed).
- `GROQ_API_KEY` / `GROQ_MODEL`: optional. Tried first for discrepancy explanations.
- `OPENAI_API_KEY` / `OPENAI_MODEL`: optional. Used if Groq is not configured or fails.
- `PORT`: backend port. Defaults to `8000`.
- `VITE_API_BASE`: frontend build-time API base URL.

## Architecture

The backend exposes JSON routes under `/api/*`:

- `POST /api/signup`, `POST /api/login`, `POST /api/logout`, `GET /api/me`
- `POST /api/import` for the two CSV files
- `GET /api/dashboard` for deterministic reconciliation output
- `POST /api/explain` for backend-only LLM explanations

SQLite tables are scoped by `user_id`, so users only see their own imports and explanation cache entries. Authentication uses PBKDF2-HMAC-SHA256 password hashing, random server-side sessions, and HMAC-signed HTTP-only cookies.

The frontend is a Vite React app written in TypeScript. It uses small local shadcn-style primitives for buttons, cards, inputs, selects, and badges, plus Lucide icons. The dashboard includes headline metrics, risk-by-type bars, upload state, filters, search, a discrepancy table, and LLM loading/error states.

## Reconciliation Logic

Matching is deterministic by normalized order identifier: `orders.order_id` to `payments.order_reference`. Matching is case-insensitive because the source files include processor references that differ only by case. Amount comparisons use a `$0.01` tolerance to avoid cent-level formatting noise.

Completed orders should have exactly one settled charge in the same currency for the order `net_amount`. Refunds reduce the matched payment total. Cancelled orders should not have captured charge activity. Refunded or returned orders should net to zero.

Discrepancy types implemented:

- `missing_payment`: completed order with no matching processor activity.
- `missing_charge`: order has payment activity, but no settled charge.
- `unsettled_payment`: payment exists but is pending, failed, or otherwise not settled.
- `underpaid`: settled payment total is below the completed order value.
- `overpaid`: settled payment total is above the completed order value.
- `duplicate_charge`: multiple settled charges point to one order.
- `currency_mismatch`: order and payment currencies differ.
- `charged_cancelled_order`: cancelled order has captured payment activity.
- `refund_not_balanced`: refunded or returned order does not net to zero.
- `orphan_payment`: payment references an order missing from the order export.
- `orphan_refund`: refund references an order missing from the order export.
- `duplicate_order_id`: order export contains repeated order IDs.
- `duplicate_transaction_ref`: payment export contains repeated transaction references.

`amount_at_risk` is the amount that should be investigated first, usually the absolute expected-versus-actual difference. Critical issues include missing money, duplicate captures, currency mismatches, orphan charges, and cancelled-order captures.

## What the Data Shows

Running `python backend/scripts/analyze_data.py` on the supplied files gives:

- Total orders: `185`
- Total payments: `187`
- Value reconciled: `$39,867.29`
- Value in dispute / money at risk: `$2,233.13`
- Discrepancies: `22`

Breakdown by type:

- `charged_cancelled_order`: 1 issue, `$175.00` at risk.
- `currency_mismatch`: 2 issues, `$355.00` at risk.
- `duplicate_charge`: 2 issues, `$248.58` at risk.
- `duplicate_order_id`: 2 issues, `$54.68` at risk.
- `missing_payment`: 4 issues, `$392.35` at risk.
- `orphan_payment`: 3 issues, `$308.00` at risk.
- `overpaid`: 2 issues, `$85.00` at risk.
- `refund_not_balanced`: 1 issue, `$120.00` at risk.
- `underpaid`: 3 issues, `$117.52` at risk.
- `unsettled_payment`: 2 issues, `$377.00` at risk.

Business meaning: the store has both revenue leakage and customer-risk issues. Missing and underpaid payments suggest orders fulfilled without full collection. Overpayments, duplicate charges, and cancelled-order charges create refund and support exposure. Orphan payments suggest processor activity that the order system does not know about. Currency mismatches need immediate review because the numeric amount may look correct while the settlement currency is wrong.

## LLM Approach

The LLM explains deterministic results only. It never decides matches, classifications, severities, or amounts.

The backend sends the currently filtered discrepancy rows (capped at 12) to Groq when `GROQ_API_KEY` is present, falling back to OpenAI if Groq is not configured or its call fails. It asks for JSON with `summary`, `likely_causes`, and `recommended_actions`. Temperature is `0.2` because the output should be stable and operational, not creative. The backend requests JSON output, validates the shape defensively (`render_llm_json`), and handles malformed responses, non-2xx responses, and network failures by falling through to the next provider.

If no provider is configured, or every provider call fails, the backend returns a **deterministic, locally-computed explanation** (`deterministic_explanation`) built from the same rows — counts by type/severity and the largest amounts at risk — so the dashboard never shows a dead end, and it's obvious from the wording that it's a fallback rather than a model-generated explanation.

Explanations are cached per user using a SHA-256 fingerprint of the selected discrepancy rows; a cached fallback explanation is treated as stale and retried rather than returned again.

## Deployment Notes

Deployed architecture: a free Neon Postgres database, a free Render web service running the Python backend (`python backend/app.py`), and a free Render static site serving the Vite build. Data lives in Postgres rather than on the backend's local disk, since free compute instances are not guaranteed to keep local files across restarts.

- Set `DATABASE_URL` on the backend to the Neon connection string.
- Set `FRONTEND_ORIGIN` on the backend to the deployed frontend's `https://` URL (this also switches the session cookie to `SameSite=None; Secure`, which cross-origin credentialed requests require).
- Set `VITE_API_BASE` at frontend build time to the deployed backend's URL.
- Pin the backend's Python version to 3.11 or 3.12 (see `runtime.txt` / the platform's Python version setting) because `backend/app.py` uses the stdlib `cgi` module, which is removed in Python 3.13.

## AI Tool Usage

AI assistance was used to generate and iterate on the implementation. The deterministic reconciliation totals were verified with the included smoke test and analyzer.

## What I Would Improve Next

- Add Playwright coverage for auth, import, filtering, and explanation states.
- Preserve raw imported rows alongside normalized fields for audit trails.
- Add downloadable discrepancy reports.
- Add a provider-specific deployment config once hosting is selected.

