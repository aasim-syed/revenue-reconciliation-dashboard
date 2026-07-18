from fastapi import APIRouter, Depends

from ..deps import require_current_user
from ..models.schemas import DashboardResponse
from ..services.reconciliation_service import reconcile

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(user: dict = Depends(require_current_user)):
    return reconcile(user["id"])
