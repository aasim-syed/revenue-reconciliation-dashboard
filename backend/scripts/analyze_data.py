from pathlib import Path
import os
import sys

os.environ["DATABASE_PATH"] = "analysis.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
config.DB_PATH = "analysis.db"

from app.db.connection import connect, init_db  # noqa: E402
from app.services.import_service import import_csvs  # noqa: E402
from app.services.reconciliation_service import reconcile  # noqa: E402


def main():
    init_db()
    with connect() as db:
        db.execute("DELETE FROM users")
        db.execute("INSERT INTO users (id, email, password_hash) VALUES (1, 'analysis@example.com', 'unused')")
    import_csvs(1, Path("orders.csv").read_text(), Path("payments.csv").read_text())
    result = reconcile(1)
    print("Summary")
    for key, value in result["summary"].items():
        print(f"{key}: {value}")
    print("\nDiscrepancies by type")
    for key, count in result["by_type"].items():
        print(f"{key}: {count} (${float(result['risk_by_type'][key]):,.2f})")
    print("\nTop discrepancies")
    for row in result["rows"][:15]:
        print(
            f"{row['severity']:8} {row['type']:24} "
            f"{row['order_id']:10} expected=${float(row['expected_amount']):,.2f} "
            f"actual=${float(row['actual_amount']):,.2f} risk=${float(row['amount_at_risk']):,.2f}"
        )


if __name__ == "__main__":
    main()
