import React from "react";
import { createRoot } from "react-dom/client";
import { AlertCircle, ArrowDownUp, Banknote, FileCheck2, Filter, Loader2, LogOut, Search, ShieldCheck, Sparkles, TriangleAlert, UploadCloud, X } from "lucide-react";
import { api } from "./lib/api";
import type { Dashboard, Discrepancy, Explanation, User } from "./lib/types";
import { currency, labelize } from "./lib/utils";
import { Badge, Button, Card, Input, Select } from "./components/ui";
import { HeroAuthScreen } from "./components/hero-auth";
import "./styles.css";

function DropZone({ label, file, onFile }: { label: string; file: File | null; onFile: (file: File | null) => void }) {
  const [dragOver, setDragOver] = React.useState(false);
  const [error, setError] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement>(null);

  function accept(picked: File | undefined) {
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith(".csv")) {
      setError("Only .csv files are accepted.");
      return;
    }
    setError("");
    onFile(picked);
  }

  return (
    <div
      className={`dropzone ${dragOver ? "dropzone-active" : ""} ${file ? "dropzone-filled" : ""}`}
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        accept(e.dataTransfer.files?.[0]);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        onChange={(e) => accept(e.target.files?.[0])}
      />
      {file ? <FileCheck2 size={20} /> : <UploadCloud size={20} />}
      <div className="dropzone-text">
        <strong>{file ? file.name : label}</strong>
        <span>{file ? `${(file.size / 1024).toFixed(1)} KB` : error || "Drag & drop, or click to browse"}</span>
      </div>
      {file && (
        <button
          type="button"
          className="dropzone-remove"
          aria-label={`Remove ${file.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onFile(null);
          }}
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
}

function ImportPanel({ onImported }: { onImported: (dashboard: Dashboard) => void }) {
  const [orders, setOrders] = React.useState<File | null>(null);
  const [payments, setPayments] = React.useState<File | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!orders || !payments) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await api.importCsvs(orders, payments);
      setMessage(`Imported ${result.orders} orders and ${result.payments} payments.`);
      onImported(result.dashboard);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="import-card">
      <div>
        <h2>Import exports</h2>
        <p>Replace your current workspace data with a fresh pair of CSV exports.</p>
      </div>
      <form onSubmit={upload} className="upload-grid">
        <DropZone label="orders.csv" file={orders} onFile={setOrders} />
        <DropZone label="payments.csv" file={payments} onFile={setPayments} />
        <Button disabled={loading || !orders || !payments}>{loading ? <Loader2 className="spin" size={16} /> : <UploadCloud size={16} />}Import</Button>
      </form>
      {message && <p className="success">{message}</p>}
      {error && <p className="form-error"><AlertCircle size={16} />{error}</p>}
    </Card>
  );
}

function Metric({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return <Card className="metric"><span>{icon}{label}</span><strong>{value}</strong></Card>;
}

function RiskChart({ dashboard, setType }: { dashboard: Dashboard; setType: (value: string) => void }) {
  const entries = Object.entries(dashboard.risk_by_type).sort((a, b) => Number(b[1]) - Number(a[1]));
  const max = Math.max(1, ...entries.map(([, value]) => Number(value)));
  return (
    <Card>
      <div className="panel-head"><h2>Risk by type</h2><Badge>{dashboard.summary.discrepancy_count} issues</Badge></div>
      <div className="bars">
        {entries.length === 0 && <p className="empty">No discrepancy risk to chart.</p>}
        {entries.map(([type, value]) => (
          <button className="bar-row" key={type} onClick={() => setType(type)}>
            <span>{labelize(type)}</span>
            <div className="bar-track"><i style={{ width: `${(Number(value) / max) * 100}%` }} /></div>
            <strong>{currency(value)}</strong>
          </button>
        ))}
      </div>
    </Card>
  );
}

function ExplanationPanel({ rows }: { rows: Discrepancy[] }) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [explanation, setExplanation] = React.useState<Explanation | null>(null);

  async function explain() {
    setLoading(true);
    setError("");
    try {
      const result = await api.explain(rows.slice(0, 12));
      setExplanation(result.explanation);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Explanation failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <div className="panel-head"><h2>Operator explanation</h2><Sparkles size={18} /></div>
      <p className="muted">Summarizes the currently filtered discrepancies. The backend calls the model and never exposes keys to the browser.</p>
      <Button onClick={explain} disabled={loading || rows.length === 0}>{loading ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}Explain current view</Button>
      {error && <p className="form-error"><AlertCircle size={16} />{error}</p>}
      {explanation && <div className="explanation"><p>{explanation.summary}</p>{explanation.likely_causes.length > 0 && <><h3>Likely causes</h3><ul>{explanation.likely_causes.map((item) => <li key={item}>{item}</li>)}</ul></>}{explanation.recommended_actions.length > 0 && <><h3>Recommended actions</h3><ul>{explanation.recommended_actions.map((item) => <li key={item}>{item}</li>)}</ul></>}</div>}
    </Card>
  );
}

function DiscrepancyTable({ rows }: { rows: Discrepancy[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Priority</th><th>Type</th><th>Order</th><th>Payment refs</th><th>Expected</th><th>Actual</th><th>At risk</th><th>Reason</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={8} className="empty">No discrepancies match this view.</td></tr>}
          {rows.map((row, index) => (
            <tr key={`${row.type}-${row.order_id}-${row.payment_refs}-${index}`}>
              <td><Badge tone={row.severity}>{labelize(row.severity)}</Badge></td>
              <td>{labelize(row.type)}</td>
              <td className="mono">{row.order_id || "-"}</td>
              <td className="mono muted-cell">{row.payment_refs || "-"}</td>
              <td>{currency(row.expected_amount)}</td>
              <td>{currency(row.actual_amount)}</td>
              <td className="risk">{currency(row.amount_at_risk)}</td>
              <td>{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DashboardScreen({ user, dashboard, setDashboard, onLogout }: { user: User; dashboard: Dashboard | null; setDashboard: (d: Dashboard) => void; onLogout: () => void }) {
  const [query, setQuery] = React.useState("");
  const [type, setType] = React.useState("");
  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    return (dashboard?.rows ?? []).filter((row) => (!type || row.type === type) && (!q || JSON.stringify(row).toLowerCase().includes(q)));
  }, [dashboard, query, type]);
  const types = Object.keys(dashboard?.by_type ?? {}).sort();

  if (!dashboard) return <main className="loading"><Loader2 className="spin" />Loading dashboard</main>;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><h1>Revenue Audit</h1><p>{user.email}</p></div>
        <Button variant="outline" onClick={onLogout}><LogOut size={16} />Log out</Button>
      </header>
      <ImportPanel onImported={setDashboard} />
      {!dashboard.has_data && <Card className="empty-state"><TriangleAlert size={22} /><div><h2>No data imported</h2><p>Upload both CSVs to calculate reconciliation totals and populate the drill-down table.</p></div></Card>}
      <section className="metrics-grid">
        <Metric label="Total orders" value={dashboard.summary.total_orders} icon={<ArrowDownUp size={16} />} />
        <Metric label="Total payments" value={dashboard.summary.total_payments} icon={<Banknote size={16} />} />
        <Metric label="Value reconciled" value={currency(dashboard.summary.total_reconciled)} icon={<ShieldCheck size={16} />} />
        <Metric label="Value in dispute" value={currency(dashboard.summary.total_dispute)} icon={<TriangleAlert size={16} />} />
        <Metric label="Money at risk" value={currency(dashboard.summary.money_at_risk)} icon={<AlertCircle size={16} />} />
      </section>
      <section className="two-col">
        <RiskChart dashboard={dashboard} setType={setType} />
        <ExplanationPanel rows={rows} />
      </section>
      <Card>
        <div className="table-toolbar">
          <div><h2>Discrepancy drill-down</h2><p>{rows.length} visible of {dashboard.rows.length}</p></div>
          <div className="filters"><div className="search-box"><Search size={16} /><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search order, transaction, reason" /></div><Select value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option>{types.map((item) => <option key={item} value={item}>{labelize(item)}</option>)}</Select><Button variant="ghost" onClick={() => { setQuery(""); setType(""); }}><Filter size={16} />Reset</Button></div>
        </div>
        <DiscrepancyTable rows={rows} />
      </Card>
    </main>
  );
}

function App() {
  const [user, setUser] = React.useState<User | null>(null);
  const [dashboard, setDashboard] = React.useState<Dashboard | null>(null);
  const [booting, setBooting] = React.useState(true);

  async function loadDashboard() {
    const data = await api.dashboard();
    setDashboard(data);
  }

  React.useEffect(() => {
    api.me().then(async ({ user }) => {
      setUser(user);
      if (user) await loadDashboard();
    }).finally(() => setBooting(false));
  }, []);

  async function onAuthed(nextUser: User) {
    setUser(nextUser);
    await loadDashboard();
  }

  async function logout() {
    await api.logout();
    setUser(null);
    setDashboard(null);
  }

  if (booting) return <main className="loading"><Loader2 className="spin" />Starting workspace</main>;
  if (!user) return <HeroAuthScreen onAuthed={onAuthed} />;
  return <DashboardScreen user={user} dashboard={dashboard} setDashboard={setDashboard} onLogout={logout} />;
}

createRoot(document.getElementById("root")!).render(<App />);
