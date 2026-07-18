from fastapi import APIRouter, Depends

from ..deps import require_current_user
from ..models.schemas import ExplainRequest, ExplainResponse
from ..services.llm_service import explain_with_llm
from ..services.reconciliation_service import reconcile

router = APIRouter(prefix="/api", tags=["explain"])


@router.post("/explain", response_model=ExplainResponse)
def explain(payload: ExplainRequest, user: dict = Depends(require_current_user)):
    rows = payload.rows or reconcile(user["id"])["rows"]
    explanation, cached = explain_with_llm(user["id"], rows)
    return {"cached": cached, "explanation": explanation}
