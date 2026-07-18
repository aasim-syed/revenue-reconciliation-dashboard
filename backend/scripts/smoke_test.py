from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB = Path("smoke_test.db")
if DB.exists():
    DB.unlink()

os.environ["DATABASE_PATH"] = str(DB)
import app

app.DB_PATH = str(DB)
app.init_db()
with app.connect() as db:
    db.execute("INSERT INTO users (id, email, password_hash) VALUES (1, 'smoke@example.com', 'unused')")
imported = app.import_csvs(1, Path("orders.csv").read_text(), Path("payments.csv").read_text())
result = app.reconcile(1)

assert imported == (185, 187), imported
assert result["summary"]["total_orders"] == 185
assert result["summary"]["total_payments"] == 187
assert result["summary"]["discrepancy_count"] == 22
assert result["summary"]["money_at_risk"] == "2233.13"
assert result["by_type"]["missing_payment"] == 4
assert result["by_type"]["orphan_payment"] == 3

print("smoke test passed")
