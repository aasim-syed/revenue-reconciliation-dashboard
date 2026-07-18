from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..deps import require_current_user
from ..models.schemas import ImportResponse
from ..services.import_service import import_csvs
from ..services.reconciliation_service import reconcile

router = APIRouter(prefix="/api", tags=["import"])


@router.post("/import", response_model=ImportResponse)
async def upload_csvs(
    orders: UploadFile = File(...),
    payments: UploadFile = File(...),
    user: dict = Depends(require_current_user),
):
    try:
        orders_text = (await orders.read()).decode("utf-8-sig")
        payments_text = (await payments.read()).decode("utf-8-sig")
        order_count, payment_count = import_csvs(user["id"], orders_text, payments_text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"orders": order_count, "payments": payment_count, "dashboard": reconcile(user["id"])}
