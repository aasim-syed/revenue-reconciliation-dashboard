# Revenue Audit

A compact full-stack web app for reconciling store orders against payment processor exports. It supports sign-up, login, per-user CSV imports, deterministic reconciliation, a dashboard with charts and drill-down filtering, and backend-only LLM explanations.

## Run locally

Requirements: Python 3.9 or newer.

```bash
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:8000`, sign up, then import `orders.csv` and `payments.csv`.

No package install is required. The app uses only the Python standard library and stores data in SQLite. Configuration is read from environment variables:

- `APP_SECRET`: long random value used to sign session cookies.
- `DATABASE_PATH`: SQLite file path. Defaults to `./revenue_audit.db`.
- `OPENAI_API_KEY`: optional. Enables discrepancy explanations.
- `OPENAI_MODEL`: optional. Defaults to `gpt-4.1-mini`.
- `PORT`: optional. Defaults to `8000`.

## Architecture

`app.py` contains the HTTP server, routing, authentication, CSV ingestion, reconciliation engine, dashboard rendering, and LLM integration. SQLite tables are scoped by `user_id`, so each user only sees their own imports and explanations.

Authentication uses email/password sign-up, PBKDF2-HMAC-SHA256 password hashing with a per-password salt, random session tokens, HMAC-signed HTTP-only cookies, and server-side session storage.

CSV ingestion validates the expected columns, normalizes dates, amounts, currencies, statuses, and order references, then replaces only the current user's previous import. The reconciliation is computed on demand from database records, making it deterministic and repeatable.

## Reconciliation Logic

Matching is by normalized order identifier: `orders.order_id` to `payments.order_reference`. Matching is case-insensitive because the sample data contains processor references such as lowercase order IDs that clearly refer to existing orders. Amount comparisons use a `$0.01` tolerance to avoid cent-level formatting noise.

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

Severity is deterministic: missing money, duplicate captures, currency mismatches, orphan charges, and cancelled-order captures are critical; smaller amount issues and duplicate source identifiers are high unless otherwise specified. `amount_at_risk` is the amount that should be investigated first, usually the absolute expected-versus-actual difference.

## What the Data Shows

Running `python scripts/analyze_data.py` on the supplied files gives:

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

The LLM is used only to explain deterministic reconciliation output. It never decides matches, discrepancy types, severity, or money at risk.

The backend sends the currently filtered discrepancy rows to OpenAI and asks for JSON with `summary`, `likely_causes`, and `recommended_actions`. `temperature` is set to `0.2` because the output should be consistent and operational, not creative. The app requests JSON output and handles malformed responses, missing keys, network failures, and missing API keys by showing a clear fallback message while keeping the deterministic dashboard available.

Explanations are cached by a SHA-256 fingerprint of the selected discrepancy rows for the current user.

## Deployment Notes

This can run on any host that supports a long-running Python process and persistent disk for SQLite, such as Render, Fly.io, Railway, or a small VPS. For production, set a strong `APP_SECRET`, configure `OPENAI_API_KEY` if explanations are required, and use a persistent `DATABASE_PATH` volume.

For heavier concurrent use, the same schema and reconciliation logic can be moved to Postgres with minimal application changes.

## AI Tool Usage

I used AI assistance to generate and iterate on the implementation, then verified the reconciliation logic with the included analysis script and Python compilation.

## What I Would Improve Next

- Add automated HTTP-level tests for auth, imports, and filtered explanations.
- Preserve raw imported rows alongside normalized fields for audit trails.
- Add downloadable discrepancy reports.
- Move rendering to templates once the UI grows beyond this compact scope.
- Add deployment-specific config files for the chosen hosting provider.
