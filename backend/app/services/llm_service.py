import hashlib
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from decimal import Decimal

from ..db.repositories import delete_cached_explanation, get_cached_explanation, save_explanation
from .reconciliation_service import money


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def render_llm_json(parsed):
    summary = parsed.get("summary", "")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Model response 'summary' was not a non-empty string")
    causes = parsed.get("likely_causes", [])
    actions = parsed.get("recommended_actions", [])
    if not isinstance(causes, list):
        causes = [str(causes)]
    if not isinstance(actions, list):
        actions = [str(actions)]
    return {"summary": summary.strip(), "likely_causes": [str(c) for c in causes[:5]], "recommended_actions": [str(a) for a in actions[:5]]}


def humanize(value):
    return str(value or "").replace("_", " ").strip()


def deterministic_explanation(rows, prefix=None):
    selected = rows[:12]
    if not selected:
        summary = "No discrepancies are visible in the current view."
        if prefix:
            summary = f"{prefix} {summary}"
        return {"summary": summary, "likely_causes": [], "recommended_actions": []}

    total_risk = sum((money(row.get("amount_at_risk")) for row in selected), Decimal("0.00"))
    by_type = Counter(row.get("type", "unknown") for row in selected)
    by_severity = Counter(row.get("severity", "unknown") for row in selected)
    top_type, top_count = by_type.most_common(1)[0]
    critical_count = by_severity.get("critical", 0)
    high_count = by_severity.get("high", 0)
    summary = (
        f"Current view contains {len(selected)} discrepancy records with {money(total_risk)} at risk. "
        f"The most common issue is {humanize(top_type)} ({top_count} records), with "
        f"{critical_count} critical and {high_count} high-priority records in scope."
    )
    if prefix:
        summary = f"{prefix} {summary}"

    causes = []
    for dtype, _ in by_type.most_common(5):
        notes = [row.get("note", "") for row in selected if row.get("type") == dtype and row.get("note")]
        cause = notes[0] if notes else f"{humanize(dtype).capitalize()} appears in the filtered records."
        causes.append(f"{humanize(dtype).capitalize()}: {cause}")

    actions = [
        "Start with critical records and the largest amount-at-risk values.",
        "Compare each affected order against the payment processor timeline before issuing refunds or capture adjustments.",
        "Export or save the filtered discrepancy list as the audit work queue for finance review.",
    ]
    if any(row.get("type") in {"duplicate_charge", "overpaid", "charged_cancelled_order"} for row in selected):
        actions.insert(1, "Prioritize customer-impacting overcollection issues before revenue leakage items.")
    if any(row.get("type") in {"missing_payment", "underpaid", "unsettled_payment"} for row in selected):
        actions.insert(1, "Verify fulfillment status before retrying collection or contacting customers.")

    return {"summary": summary, "likely_causes": causes, "recommended_actions": actions[:5]}


def _configured_providers():
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    providers = []
    if groq_key:
        providers.append({
            "api_key": groq_key,
            "endpoint": os.environ.get("GROQ_CHAT_COMPLETIONS_URL", "https://api.groq.com/openai/v1/chat/completions"),
            "model": os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
            "name": "Groq",
        })
    if openai_key:
        providers.append({
            "api_key": openai_key,
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "name": "OpenAI",
        })
    return providers


def _call_provider(provider, selected):
    body = {
        "model": provider["model"],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You explain deterministic revenue reconciliation results using {provider['name']}. "
                    "Do not change classifications, severities, or amounts - only describe them in plain language. "
                    "Return a JSON object with exactly these keys: "
                    '"summary" (a single plain-language string, 2-3 sentences, never an object or array), '
                    '"likely_causes" (an array of short plain-language strings), '
                    '"recommended_actions" (an array of short plain-language strings). '
                    'Example shape: {"summary": "...", "likely_causes": ["...", "..."], "recommended_actions": ["...", "..."]}'
                ),
            },
            {"role": "user", "content": json.dumps({"discrepancies": selected}, indent=2)},
        ],
    }
    req = urllib.request.Request(
        provider["endpoint"],
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {provider['api_key']}", "Content-Type": "application/json", "User-Agent": "revenue-audit-local-dev/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    return render_llm_json(json.loads(payload["choices"][0]["message"]["content"]))


def explain_with_llm(user_id, rows):
    selected = rows[:12]
    fp = fingerprint(selected)
    cached = get_cached_explanation(user_id, fp)
    if cached is not None:
        content = json.loads(cached)
        summary = str(content.get("summary", ""))
        stale_error = "explanation service returned" in summary.lower() or "http error 403" in summary.lower()
        if not stale_error:
            return content, True
        delete_cached_explanation(user_id, fp)

    providers = _configured_providers()
    if not providers:
        return deterministic_explanation(selected, "AI explanations are not configured; showing a deterministic summary."), False

    for provider in providers:
        try:
            parsed = _call_provider(provider, selected)
            save_explanation(user_id, fp, json.dumps(parsed))
            return parsed, False
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError, ValueError):
            continue

    return deterministic_explanation(selected, "AI explanation is temporarily unavailable; showing a deterministic summary."), False
