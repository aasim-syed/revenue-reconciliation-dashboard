from pathlib import Path
import os
import sys

os.environ["DATABASE_PATH"] = "analysis.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def main():
    app.DB_PATH = "analysis.db"
    app.init_db()
    with app.connect() as db:
        db.execute("DELETE FROM users")
        db.execute("INSERT INTO users (id, email, password_hash) VALUES (1, 'analysis@example.com', 'unused')")
    app.import_csvs(1, Path("orders.csv").read_text(), Path("payments.csv").read_text())
    result = app.reconcile(1)
    print("Summary")
    for key, value in result["summary"].items():
        print(f"{key}: {value}")
    print("\nDiscrepancies by type")
    for key, count in result["by_type"].items():
        print(f"{key}: {count} (${app.money_str(result['risk_by_type'][key])})")
    print("\nTop discrepancies")
    for row in result["rows"][:15]:
        print(
            f"{row['severity']:8} {row['type']:24} "
            f"{row['order_id']:10} expected=${app.money_str(row['expected_amount'])} "
            f"actual=${app.money_str(row['actual_amount'])} risk=${app.money_str(row['amount_at_risk'])}"
        )


if __name__ == "__main__":
    main()
