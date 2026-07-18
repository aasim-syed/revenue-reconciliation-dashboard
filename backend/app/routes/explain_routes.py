from fastapi import APIRouter, Depends

from ..deps import require_current_user
from ..models.schemas import ExplainRequest, ExplainResponse
from ..services.llm_service import explain_with_llm
from ..services.reconciliation_service import reconcile

router = APIRouter(prefix="/api", tags=["explain"])


def _row_signature(row):
    return (row.get("type"), row.get("order_id"), row.get("payment_refs"), row.get("amount_at_risk"))


@router.post("/explain", response_model=ExplainResponse)
def explain(payload: ExplainRequest, user: dict = Depends(require_current_user)):
    current_rows = reconcile(user["id"])["rows"]
    if payload.rows:
        # The client only ever sends its current filtered view, but the request body is
        # still attacker-controlled input: verify each row matches a real, currently
        # computed discrepancy before it reaches the LLM prompt, instead of trusting
        # whatever the caller posts. Anything that doesn't match a live row is dropped.
        valid_signatures = {_row_signature(row) for row in current_rows}
        rows = [row for row in payload.rows if _row_signature(row) in valid_signatures]
        if not rows:
            rows = current_rows
    else:
        rows = current_rows
    explanation, cached = explain_with_llm(user["id"], rows)
    return {"cached": cached, "explanation": explanation}
