from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuthRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str


class AuthResponse(BaseModel):
    user: UserOut


class MeResponse(BaseModel):
    user: Optional[UserOut]


class LogoutResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    ok: bool


class DiscrepancyOut(BaseModel):
    type: str
    severity: str
    order_id: str
    order_status: str
    payment_refs: str
    payment_statuses: str
    expected_amount: str
    actual_amount: str
    amount_at_risk: str
    currency: str
    note: str


class DashboardSummary(BaseModel):
    total_orders: int
    total_payments: int
    total_reconciled: str
    total_dispute: str
    money_at_risk: str
    net_collected: str
    discrepancy_count: int


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    by_type: Dict[str, int]
    risk_by_type: Dict[str, str]
    rows: List[DiscrepancyOut]
    has_data: bool


class ImportResponse(BaseModel):
    orders: int
    payments: int
    dashboard: DashboardResponse


class ExplainRequest(BaseModel):
    rows: Optional[List[Dict[str, Any]]] = None


class ExplanationOut(BaseModel):
    summary: str
    likely_causes: List[str]
    recommended_actions: List[str]


class ExplainResponse(BaseModel):
    cached: bool
    explanation: ExplanationOut
