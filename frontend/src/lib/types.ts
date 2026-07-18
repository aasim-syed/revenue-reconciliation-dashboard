export type User = { id: number; email: string };

export type Summary = {
  total_orders: number;
  total_payments: number;
  total_reconciled: string;
  total_dispute: string;
  money_at_risk: string;
  net_collected: string;
  discrepancy_count: number;
};

export type Discrepancy = {
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  order_id: string;
  order_status: string;
  payment_refs: string;
  payment_statuses: string;
  expected_amount: string;
  actual_amount: string;
  amount_at_risk: string;
  currency: string;
  note: string;
};

export type Dashboard = {
  summary: Summary;
  by_type: Record<string, number>;
  risk_by_type: Record<string, string>;
  by_severity: Record<string, number>;
  risk_by_severity: Record<string, string>;
  rows: Discrepancy[];
  has_data: boolean;
};

export type Explanation = {
  summary: string;
  likely_causes: string[];
  recommended_actions: string[];
};
