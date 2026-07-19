# Revenue Audit

A monorepo revenue reconciliation app with a Python API backend and a React + TypeScript frontend styled with shadcn-inspired components.

## Structure

```text
backend/
  app/
    main.py        FastAPI app: CORS, lifespan (DB init), routers, error shaping
    config.py       Env vars and derived settings, .env loading
    deps.py          Auth dependencies (current user / require-login)
    db/
      connection.py    SQLite/Postgres connection + schema
      repositories.py  All raw SQL, one function per query
    models/
      schemas.py       Pydantic request/response models
    services/
      security.py             Password hashing, session token signing
      auth_service.py          Signup/login/logout orchestration
      import_service.py        CSV parsing/normalization
      reconciliation_service.py Deterministic matching engine
      llm_service.py            LLM explanation calls, fallback, caching
    routes/
      auth_routes.py, dashboard_routes.py, import_routes.py, explain_routes.py
  scripts/           smoke_test.py, analyze_data.py (exercise the services directly)
frontend/  React + TypeScript + Vite dashboard
```

Routes only parse the request and call a service; services hold business logic and call
repositories; repositories are the only place that touches SQL. This keeps the reconciliation
engine and the LLM layer independently testable from the HTTP layer (see `backend/scripts/`).

## Run locally

Backend:

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend, in another terminal:

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173`, sign up, then import `orders.csv` and `payments.csv`. Interactive API
docs are available at `http://127.0.0.1:8000/docs` while the backend is running.

Useful checks:

```bash
python backend/scripts/smoke_test.py
python backend/scripts/analyze_data.py
npm run build
```

## Tests

Backend (pytest, 39 tests: auth, session expiry, rate limiting, per-user data isolation, every
discrepancy type including the amount-tolerance boundary, the golden-dataset regression against the
real CSVs, and the explain-endpoint row-signature check):

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Frontend (Playwright, end-to-end against a real backend + Vite dev server it starts itself): signup →
import → dashboard → severity-filter → explain, the dashboard-fetch-failure retry path, and a
second account seeing no data. Needs `pip install -r backend/requirements-dev.txt`-level backend deps
on `PATH` as `python`, plus a Chromium install the first time (`npx playwright install chromium`):

```bash
cd frontend
npm run test:e2e
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
- `SESSION_MAX_AGE_DAYS`: how long a session cookie stays valid. Defaults to `7`.
- `RATE_LIMIT_WINDOW_SECONDS` / `RATE_LIMIT_MAX_ATTEMPTS`: login/signup rate limit window and cap. Defaults to `300` seconds / `8` attempts.

## Architecture

The backend is a FastAPI app under `backend/app/`, layered as routes → services → repositories → db:

- `POST /api/signup`, `POST /api/login`, `POST /api/logout`, `GET /api/me`
- `POST /api/import` for the two CSV files
- `GET /api/dashboard` for deterministic reconciliation output
- `POST /api/explain` for backend-only LLM explanations

Pydantic models in `app/models/schemas.py` validate every request body and shape every response,
so the API contract is enforced (and self-documented at `/docs`) rather than assembled by hand.
A global exception handler reshapes FastAPI's default `{"detail": ...}` errors to `{"error": ...}`
to match the frontend's existing error handling.

Tables (`users`, `sessions`, `orders`, `payments`, `explanations`) are scoped by `user_id`, so users
only see their own imports and explanation cache entries. Authentication uses PBKDF2-HMAC-SHA256
password hashing, random server-side sessions, and HMAC-signed HTTP-only cookies. Sessions expire
after `SESSION_MAX_AGE_DAYS` (default 7) — checked and the row deleted on read, so a stale or stolen
cookie stops working instead of being valid forever. `/api/login` and `/api/signup` are rate-limited
per IP+email (in-memory sliding window, `RATE_LIMIT_MAX_ATTEMPTS` per `RATE_LIMIT_WINDOW_SECONDS`) to
slow down credential stuffing; this is process-local, so a multi-instance deployment would need a
shared store (Redis) instead. `/api/explain` treats the client-supplied row list as untrusted input:
it cross-checks every row against that user's current server-computed reconciliation and drops
anything that doesn't match a real discrepancy before it reaches the LLM prompt, rather than trusting
whatever the request body contains.

The frontend is a Vite React app written in TypeScript. It uses small local shadcn-style primitives for buttons, cards, inputs, selects, and badges, plus Lucide icons. The dashboard includes headline metrics, a risk-by-type chart, a severity-breakdown chart (both clickable to filter the drill-down table, with removable filter chips), upload state, search, a discrepancy table, and LLM loading/error states. A failed `/api/dashboard` fetch shows an explicit error with a Retry action instead of spinning forever. The login screen's decorative 3D background (Spline) is wrapped in a React error boundary: a blocked or failed request to that third-party CDN falls back to a static background instead of crashing the entire auth screen — found while writing the Playwright suite, which blocks that CDN call to keep the tests hermetic.

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
- `partially_refunded`: refunded or returned order still has unreturned charge value outstanding.
- `over_refunded`: refunded or returned order was refunded for more than it was charged.
- `orphan_payment`: payment references an order missing from the order export.
- `orphan_refund`: refund references an order missing from the order export.
- `duplicate_order_id`: order export contains repeated order IDs.
- `duplicate_transaction_ref`: payment export contains repeated transaction references.
- `unexpected_status`: order status is outside the recognized set (`completed`, `cancelled`/`canceled`,
  `refunded`, `returned`). Flagged at `medium` severity instead of being silently skipped, so an
  unfamiliar export value can't make an order vanish from both the reconciled and disputed totals.

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
- `partially_refunded`: 1 issue, `$120.00` at risk.
- `underpaid`: 3 issues, `$117.52` at risk.
- `unsettled_payment`: 2 issues, `$377.00` at risk.

Business meaning: the store has both revenue leakage and customer-risk issues. Missing and underpaid payments suggest orders fulfilled without full collection. Overpayments, duplicate charges, and cancelled-order charges create refund and support exposure. Orphan payments suggest processor activity that the order system does not know about. Currency mismatches need immediate review because the numeric amount may look correct while the settlement currency is wrong.

## LLM Approach

The LLM explains deterministic results only. It never decides matches, classifications, severities, or amounts.

The backend sends the currently filtered discrepancy rows (capped at 12) to Groq when `GROQ_API_KEY` is present, falling back to OpenAI if Groq is not configured or its call fails. It asks for JSON with `summary`, `likely_causes`, and `recommended_actions`. Temperature is `0.2` because the output should be stable and operational, not creative. The backend requests JSON output, validates the shape defensively (`render_llm_json`), and handles malformed responses, non-2xx responses, and network failures by falling through to the next provider.

If no provider is configured, or every provider call fails, the backend returns a **deterministic, locally-computed explanation** (`deterministic_explanation`) built from the same rows — counts by type/severity and the largest amounts at risk — so the dashboard never shows a dead end, and it's obvious from the wording that it's a fallback rather than a model-generated explanation.

Explanations are cached per user using a SHA-256 fingerprint of the selected discrepancy rows; a cached fallback explanation is treated as stale and retried rather than returned again.

## Deployment Notes

Deployed architecture: a free Neon Postgres database, a free Render web service running the FastAPI backend (`uvicorn app.main:app`), and a free Render static site serving the Vite build. Data lives in Postgres rather than on the backend's local disk, since free compute instances are not guaranteed to keep local files across restarts.

- Set `DATABASE_URL` on the backend to the Neon connection string.
- Set `FRONTEND_ORIGIN` on the backend to the deployed frontend's `https://` URL (this also switches the session cookie to `SameSite=None; Secure`, which cross-origin credentialed requests require).
- Set `VITE_API_BASE` at frontend build time to the deployed backend's URL.
- `runtime.txt` / the platform's Python version setting pins the backend to 3.12.

## AI Tool Usage

AI assistance was used to generate and iterate on the implementation. The deterministic reconciliation totals were verified with the included smoke test and analyzer.

## What I Would Improve Next

- Move the rate limiter from in-memory to a shared store (Redis) before running more than one backend
  instance, since the current sliding window is per-process.
- Add a "logout everywhere" action that revokes all of a user's sessions, not just the current one.
- Preserve raw imported rows alongside normalized fields for audit trails.
- Add downloadable discrepancy reports.
- Move repositories from a connection-per-query pattern to a request-scoped connection or pool.

