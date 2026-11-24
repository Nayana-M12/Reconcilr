import { FormEvent, useEffect, useRef, useState } from "react";
import { BrowserRouter, Link, Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  AgentRun, Adjustment, AuditEntry, Exception, ExtractionResult, Insights,
  acceptRun, clearAuthToken, decideAdjustment, extractDocument,
  getAdjustments, getAgentRuns, getAudit, getException, getExceptions,
  getInsights, getMatches, getSummary, importRecords, investigateException,
  overrideRun, proposeAdjustments, runExceptions, runMatching, Summary,
  getAuthToken, getAuthUser, login,
} from "./api";
import LandingCta from "./components/LandingCta";
import "./styles.css";

const errorText = (error: unknown) => error instanceof Error ? error.message : "Something went wrong.";
const navIcons = ["⌂", "◇", "＋", "≡", "✦", "⬆"];

const useCountUp = (value: number) => {
  const [displayValue, setDisplayValue] = useState(0);
  const animated = useRef(false);
  useEffect(() => {
    if (animated.current || value === 0) { setDisplayValue(value); return; }
    animated.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { setDisplayValue(value); return; }
    const started = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - started) / 700, 1);
      setDisplayValue(Math.round(value * (1 - Math.pow(1 - progress, 3))));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [value]);
  return displayValue;
};
const resultChips = (result: Record<string, unknown>) => {
  const chips: string[] = [];
  ["created", "existing"].forEach(key => {
    if (typeof result[key] === "number") chips.push(`${key} ${result[key]}`);
  });
  if (Array.isArray(result.unmatched_invoice_ids)) chips.push(`unmatched ${result.unmatched_invoice_ids.length}`);
  if (result.tier_counts && typeof result.tier_counts === "object") {
    Object.entries(result.tier_counts as Record<string, unknown>).forEach(([key, value]) => {
      if (typeof value === "number") chips.push(`${key} ${value}`);
    });
  }
  if (result.by_type && typeof result.by_type === "object") {
    Object.entries(result.by_type as Record<string, unknown>).forEach(([key, value]) => {
      if (typeof value === "number") chips.push(`${key} ${value}`);
    });
  }
  return chips;
};
function State({ loading, error, empty = false }: { loading: boolean; error: string; empty?: boolean }) {
  if (loading) return <div className="card p-8 text-sm text-white/50">Loading...</div>;
  if (error) return <div className="card border-red-400/20 p-5 text-sm text-red-200">{error}</div>;
  if (empty) return <div className="card p-8 text-sm text-white/50">No records found.</div>;
  return null;
}
function Layout() {
  const links = [["/app", "Overview"], ["/app/exceptions", "Exceptions"], ["/app/adjustments", "Adjustments"], ["/app/audit", "Audit log"], ["/app/extract", "Extract"], ["/app/insights", "AI Insights"]];
  const navigate = useNavigate();
  const user = getAuthUser();
  const signOut = () => { clearAuthToken(); navigate("/login"); };
  return <div className="min-h-screen md:flex">
    <aside className="app-sidebar border-b border-white/10 p-5 md:min-h-screen md:w-64 md:border-b-0 md:border-r">
      <Link to="/app" className="text-lg font-semibold tracking-tight">Reconcilr<span className="text-white/40">.</span></Link>
      <nav className="app-nav mt-8 flex gap-2 overflow-auto md:block md:space-y-1">
        {links.map(([to, label], index) => <NavLink key={to} to={to} end={to === "/app"} className={({ isActive }) => `block whitespace-nowrap rounded-lg px-3 py-2 text-sm ${isActive ? "bg-white/10 text-white" : "text-white/50 hover:bg-white/5 hover:text-white"}`}><span className="nav-icon" aria-hidden="true">{navIcons[index]}</span>{label}</NavLink>)}
      </nav>
      {user && <div className="sidebar-account">
        <div><strong>{user.username}</strong><span>{user.role}</span></div>
        <button type="button" onClick={signOut}>Sign out</button>
      </div>}
    </aside>
    <main className="app-main w-full max-w-7xl p-5 md:p-10"><Outlet /></main>
  </div>;
}
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return getAuthToken() ? <>{children}</> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}
function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [username, setUsername] = useState(""); const [password, setPassword] = useState("");
  const [error, setError] = useState(searchParams.get("message") || ""); const [submitting, setSubmitting] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSubmitting(true); setError("");
    try { await login(username, password); navigate("/app", { replace: true }); }
    catch (e) { setError(errorText(e)); } finally { setSubmitting(false); }
  };
  return <main className="login-page"><section className="login-card card">
    <Link to="/" className="login-brand">Reconcilr<span>.</span></Link>
    <p className="dashboard-kicker">Secure workspace</p><h1>Sign in</h1>
    <p className="login-subtitle">Access your reconciliation control room.</p>
    {error && <div className="login-error">{error}</div>}
    <form onSubmit={submit} className="login-form">
      <label>Username<input className="field" value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required /></label>
      <label>Password<input className="field" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required /></label>
      <button className="button-primary" type="submit" disabled={submitting}>{submitting ? "Signing in..." : "Sign in"}</button>
    </form>
    <Link to="/" className="login-back">Back to home</Link>
  </section></main>;
}
function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="app-page-title mb-8"><h1 className="text-2xl font-semibold">{title}</h1><p className="mt-1 text-sm text-white/45">{subtitle}</p></header>;
}
function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null); const [error, setError] = useState(""); const [running, setRunning] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null); const [rawOpen, setRawOpen] = useState(false);
  const [matches, setMatches] = useState<Record<string, unknown>[]>([]); const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [activity, setActivity] = useState<AuditEntry[]>([]); const [loading, setLoading] = useState(true);
  useEffect(() => {
    Promise.all([getSummary(), getMatches(), getExceptions({}), getAudit("", 5)])
      .then(([nextSummary, nextMatches, nextExceptions, nextActivity]) => {
        setSummary(nextSummary); setMatches(nextMatches); setExceptions(nextExceptions.slice(-5).reverse()); setActivity(nextActivity.slice(0, 5));
      })
      .catch(e => setError(errorText(e))).finally(() => setLoading(false));
  }, []);
  const run = async (name: string, action: () => Promise<Record<string, unknown> | Adjustment[]>) => {
    setRunning(name); setError(""); setResult(null);
    try { const value = await action(); setResult(Array.isArray(value) ? { created: value.length } : value); setSummary(await getSummary()); }
    catch (e) { setError(errorText(e)); } finally { setRunning(""); }
  };
  const matchCount = useCountUp(summary?.matches || 0); const openCount = useCountUp(summary?.open_exceptions || 0);
  const pendingCount = useCountUp(summary?.pending_adjustments || 0);
  const tiers = matches.reduce<Record<string, number>>((counts, match) => { const tier = String(match.tier || "unknown"); counts[tier] = (counts[tier] || 0) + 1; return counts; }, {});
  const pipelineActions: [string, string, string, () => Promise<Record<string, unknown> | Adjustment[]>][] = [
    ["matching", "Match", "Run matching", runMatching],
    ["exceptions", "Detect exceptions", "Detect exceptions", runExceptions],
    ["adjustments", "Propose adjustments", "Propose adjustments", proposeAdjustments],
  ];
  const exceptionAmount = (item: Exception) => {
    const withAmount = item as Exception & { amount?: string | number };
    return withAmount.amount == null ? "—" : String(withAmount.amount);
  };
  return <><div className="dashboard-hero">
      <div><p className="dashboard-kicker">Reconciliation control room</p><h1>Overview</h1><p>Keep your reconciliation workspace moving.</p></div>
      <div className="dashboard-hero-stat"><strong>{matchCount} matches reconciled</strong><span>{openCount} open exceptions</span></div>
    </div>
    <State loading={loading} error={error} />
    {summary && <div className="dashboard-summary">
      <div className="card dashboard-card dashboard-card-matches"><p className="dashboard-label">Matches</p><strong>{matchCount}</strong><div className="match-bar"><span style={{ width: `${summary.matches ? (tiers.exact || 0) / summary.matches * 100 : 0}%` }} /><span style={{ width: `${summary.matches ? (tiers.tolerance || 0) / summary.matches * 100 : 0}%` }} /></div><div className="match-legend"><span>Exact {tiers.exact || 0}</span><span>Tolerance {tiers.tolerance || 0}</span><span>Fuzzy {tiers.fuzzy || 0}</span></div></div>
      <div className="card dashboard-card dashboard-card-exceptions"><p className="dashboard-label">Open exceptions</p><strong>{openCount}</strong><p><i />{summary.resolved_exceptions} resolved</p></div>
      <div className="card dashboard-card dashboard-card-resolved"><p className="dashboard-label">Resolved exceptions</p><strong>{summary.resolved_exceptions}</strong><p>Evidence attached to every decision</p></div>
      <div className="card dashboard-card dashboard-card-adjustments"><p className="dashboard-label">Pending adjustments</p><strong>{pendingCount}</strong><Link to="/app/adjustments">Review <span>↗</span></Link></div>
    </div>}
    <section className="card pipeline-card">
      <div className="section-heading"><div><p className="dashboard-kicker">Workflow</p><h2>Run pipeline</h2></div><span className="section-note">Process stages in order</span></div>
      <div className="pipeline-steps">
        <div className="pipeline-step"><span className="pipeline-number">01</span><strong>Import</strong><small>Source records</small></div><span className="pipeline-arrow">→</span>
        {pipelineActions.map(([key, title, label, action]) =>
          <div className="pipeline-step pipeline-runnable" key={key}><span className="pipeline-number">{key === "matching" ? "02" : key === "exceptions" ? "03" : "04"}</span><strong>{title}</strong><button className="button-primary" disabled={!!running} onClick={() => run(key, action)}>{running === key ? "Running..." : label}</button></div>)}
        <span className="pipeline-arrow">→</span><div className="pipeline-step"><span className="pipeline-number">05</span><strong>Route approval</strong><small>Review queue</small></div>
      </div>
      {result && <div className="pipeline-result"><div className="result-chips">{resultChips(result).map(chip => <span key={chip}>{chip}</span>)}</div><button className="raw-toggle" onClick={() => setRawOpen(!rawOpen)}>{rawOpen ? "Hide raw JSON" : "View raw JSON"}</button>{rawOpen && <pre>{JSON.stringify(result, null, 2)}</pre>}</div>}
    </section>
    <div className="dashboard-lower">
      <section className="card activity-card"><div className="section-heading"><h2>Recent exceptions</h2><Link to="/app/exceptions">View all ↗</Link></div>{exceptions.length ? <div className="recent-list">{exceptions.map(item => <div className="recent-row" key={item.id}><div><strong>{item.type}</strong><span>{item.description}</span></div><span className="status-badge" data-status={item.status}>{item.status}</span><span className="recent-amount">{exceptionAmount(item)}</span><Link to="/app/exceptions">Detail ↗</Link></div>)}</div> : <State loading={loading} error="" empty={!loading} />}</section>
      <section className="card activity-card"><div className="section-heading"><h2>Recent activity</h2><Link to="/app/audit">View audit ↗</Link></div>{activity.length ? <div className="recent-list">{activity.map(item => <div className="activity-row" key={item.id}><span className="activity-dot" /><div><strong>{item.action}</strong><span>{item.entity_type} · {item.entity_id}</span></div><time>{new Date(item.timestamp).toLocaleDateString()}</time></div>)}</div> : <State loading={loading} error="" empty={!loading} />}</section>
    </div>
  </>;
}
function ExceptionsPage() {
  const [items, setItems] = useState<Exception[]>([]); const [selected, setSelected] = useState<Exception | null>(null);
  const [aiTarget, setAiTarget] = useState<string | null>(null);
  const [filters, setFilters] = useState({ type: "", status: "", severity: "" }); const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); getExceptions(Object.fromEntries(Object.entries(filters).filter(([, value]) => value))).then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); };
  useEffect(load, [filters.type, filters.status, filters.severity]);
  return <><PageTitle title="Exceptions" subtitle="Review issues detected across your records." />
    <div className="mb-5 flex flex-wrap gap-2">{(["type", "status", "severity"] as const).map(field => <input key={field} className="field" placeholder={field[0].toUpperCase() + field.slice(1)} value={filters[field]} onChange={e => setFilters({ ...filters, [field]: e.target.value })} />)}</div>
    <State loading={loading} error={error} empty={!loading && !error && !items.length} />
    {!loading && !error && !!items.length && <div className="card overflow-auto"><table className="w-full text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Type</th><th>Status</th><th>Severity</th><th>Invoice #</th><th>Vendor</th><th>Inv. Amount</th><th>PO #</th><th>Payment</th><th>Pay. Date</th><th>Description</th><th></th></tr></thead><tbody>{items.map(item => {
      const inv = item.related?.invoice; const po = item.related?.purchase_order; const pay = item.related?.payment;
      return <tr key={item.id} className="border-b border-white/5 last:border-0 hover:bg-white/5">
        <td className="p-4 font-medium cursor-pointer" onClick={() => getException(item.id).then(setSelected).catch(e => setError(errorText(e)))}>{item.type}</td>
        <td><span className="status-badge" data-status={item.status}>{item.status}</span></td>
        <td><span className="status-badge" data-status={item.severity}>{item.severity}</span></td>
        <td className="pr-4">{inv ? inv.invoice_number : "-"}</td>
        <td className="pr-4">{inv ? inv.vendor_name : "-"}</td>
        <td className="pr-4">{inv ? `${inv.amount} ${inv.currency}` : "-"}</td>
        <td className="pr-4">{po ? po.po_number : "-"}</td>
        <td className="pr-4">{pay ? `${pay.amount} ${pay.currency}` : "-"}</td>
        <td className="pr-4 text-white/60">{pay ? pay.payment_date : "-"}</td>
        <td className="max-w-xs truncate pr-4 text-white/60">{item.description}</td>
        <td className="pr-3"><button className="text-xs text-blue-400 hover:text-blue-200 whitespace-nowrap" onClick={() => setAiTarget(aiTarget === item.id ? null : item.id)}>🤖 AI</button></td>
      </tr>;
    })}</tbody></table></div>}
    {selected && <div className="detail-panel card mt-5 p-6"><div className="flex items-start justify-between"><div><p className="text-xs uppercase text-white/40">Exception detail</p><h2 className="mt-1 font-semibold">{selected.type}</h2><p className="mt-2 text-sm text-white/60">{selected.description}</p></div><button className="text-white/50" onClick={() => setSelected(null)}>Close</button></div>
      <h3 className="mt-6 text-sm font-medium">Related records</h3><div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">{[
        ["Invoice", selected.related?.invoice ? `${selected.related.invoice.invoice_number} · ${selected.related.invoice.vendor_name} · ${selected.related.invoice.amount} ${selected.related.invoice.currency}` : null],
        ["Purchase order", selected.related?.purchase_order ? `${selected.related.purchase_order.po_number} · ${selected.related.purchase_order.amount} ${selected.related.purchase_order.currency}` : null],
        ["Payment", selected.related?.payment ? `${selected.related.payment.amount} ${selected.related.payment.currency} · ${selected.related.payment.payment_date}` : null],
      ].map(([label, value]) => <div className="rounded-lg border border-white/10 p-3" key={String(label)}><p className="text-xs text-white/40">{label}</p><p className="mt-1 text-white/80">{value ?? "-"}</p></div>)}</div>
      <h3 className="mt-6 text-sm font-medium">Evidence</h3><div className="mt-3 space-y-2">{selected.evidence.length ? selected.evidence.map(e => <div className="rounded-lg border border-white/10 p-3 text-sm" key={e.id}><span className="text-white/50">{e.record_type} · {e.record_id}</span><p className="mt-1 text-white/70">{e.note}</p></div>) : <p className="text-sm text-white/50">No evidence attached.</p>}</div></div>}
    {aiTarget && <AiAgentPanel exceptionId={aiTarget} onClose={() => setAiTarget(null)} />}
  </>;
}
function AdjustmentsPage() {
  const [items, setItems] = useState<Adjustment[]>([]); const [selected, setSelected] = useState<Adjustment | null>(null);
  const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [comment, setComment] = useState(""); const [saving, setSaving] = useState(false);
  const user = getAuthUser(); const canApprove = user?.role === "approver" || user?.role === "admin";
  const load = () => { setLoading(true); getAdjustments().then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); }; useEffect(load, []);
  const decide = async (decision: "approved" | "rejected") => { if (!selected || !canApprove || !user) return; setSaving(true); setError(""); try { const updated = await decideAdjustment(selected.id, { role: user.role, decision, comment }); setSelected(updated); setItems(items.map(item => item.id === updated.id ? updated : item)); } catch (e) { setError(errorText(e)); } finally { setSaving(false); } };
  return <><PageTitle title="Adjustments" subtitle="Approve proposed changes with a clear audit trail." /><State loading={loading} error={error} empty={!loading && !error && !items.length} />
    {!loading && !error && !!items.length && <div className="grid gap-5 lg:grid-cols-[1fr_420px]"><div className="card overflow-hidden"><table className="w-full text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Status</th><th>Proposed amount</th><th>Approvers</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => { setSelected(item); setComment(""); }} className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"><td className="p-4"><span className="status-badge" data-status={item.status}>{item.status}</span></td><td>{item.proposed_amount}</td><td>{item.required_approvers.join(", ")}</td></tr>)}</tbody></table></div>
      {selected && <div className="detail-panel card h-fit p-6"><div className="flex justify-between"><h2 className="font-semibold">Calculation</h2><button className="text-white/50" onClick={() => setSelected(null)}>Close</button></div><div className="mt-4 space-y-2 text-sm"><p className="text-white/50">Formula</p><p>{selected.calculation.formula}</p><p className="pt-2 text-white/50">Result</p><p className="text-xl">{selected.calculation.result}</p><p className="pt-2 text-white/50">Records</p>{selected.calculation.record_ids.map(id => <p key={id}>{id}: {selected.calculation.amounts[id]}</p>)}</div><h3 className="mt-6 text-sm font-medium">Approval steps</h3><div className="mt-3 space-y-2">{selected.approval_steps.map(step => <div className="flex justify-between rounded-lg border border-white/10 p-3 text-sm" key={step.id}><span>{step.role}</span><span className="status-badge" data-status={step.decision}>{step.decision}</span></div>)}</div>{selected.status === "pending" && <><input className="field mt-5 w-full" placeholder="Comment (optional)" value={comment} onChange={e => setComment(e.target.value)} />{!canApprove && <p className="mt-3 text-sm text-red-200">You do not have permission for this action.</p>}<div className="mt-3 flex gap-2"><button className="button-primary flex-1" disabled={saving || !canApprove} onClick={() => decide("approved")}>Approve</button><button className="button-secondary flex-1" disabled={saving || !canApprove} onClick={() => decide("rejected")}>Reject</button></div></>}</div>}</div>}
  </>;
}
function ExtractPage() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [importStatus, setImportStatus] = useState("");

  const confidenceColor = (c: number) => c >= 0.75 ? "text-green-400" : c >= 0.5 ? "text-yellow-400" : "text-red-400";

  const extract = async () => {
    if (!file) return;
    setLoading(true); setError(""); setResult(null); setImportStatus("");
    try { setResult(await extractDocument(file)); }
    catch (e) { setError(errorText(e)); }
    finally { setLoading(false); }
  };

  const saveAsInvoice = async () => {
    if (!file) return;
    setImportStatus("Saving...");
    try {
      await importRecords("invoice", file);
      setImportStatus("✓ Saved as invoice record.");
    } catch (e) { setImportStatus("Error: " + errorText(e)); }
  };

  return <>
    <PageTitle title="Document Extraction" subtitle="Upload an invoice, PO, or payment document to extract structured fields." />
    <div className="card p-6 mb-5">
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="block text-xs text-white/40 mb-1">Document (PDF, PNG, JPG, TIFF)</label>
          <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff,.bmp,.webp"
            className="field text-sm"
            onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); setImportStatus(""); }} />
        </div>
        <button className="button-primary" disabled={!file || loading} onClick={extract}>
          {loading ? "Extracting…" : "Extract fields"}
        </button>
      </div>
    </div>
    <State loading={loading} error={error} />
    {result && <>
      <div className="card p-6 mb-5">
        <div className="flex justify-between items-start mb-4">
          <div>
            <p className="text-xs text-white/40">Extraction method: <span className="text-white/70">{result.method}</span></p>
            <p className="text-xs mt-1">Confidence: <span className={`font-semibold ${confidenceColor(result.confidence)}`}>{Math.round(result.confidence * 100)}%</span></p>
          </div>
          <button className="button-primary text-sm" onClick={saveAsInvoice} disabled={importStatus === "Saving..."}>
            Save as Invoice
          </button>
        </div>
        {result.warnings.length > 0 && <div className="mb-4 space-y-1">
          {result.warnings.map((w, i) => <p key={i} className="text-xs text-yellow-300 bg-yellow-900/20 rounded px-3 py-1">⚠ {w}</p>)}
        </div>}
        {importStatus && <p className="text-sm mb-4 text-green-300">{importStatus}</p>}
        <h3 className="text-sm font-medium mb-3">Extracted Fields</h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {([
            ["Invoice Number", "invoice_number"], ["PO Number", "po_number"], ["Vendor Name", "vendor_name"],
            ["Invoice Date", "invoice_date"], ["Due Date", "due_date"], ["Payment Date", "payment_date"],
            ["Invoice Amount", "invoice_amount"], ["Tax Amount", "tax_amount"], ["Payment Amount", "payment_amount"],
            ["Reference", "reference"], ["Description", "description"],
          ] as [string, string][]).map(([label, key]) => {
            const val = result.fields[key as keyof typeof result.fields];
            return <div key={key} className={`rounded-lg border p-3 text-sm ${val ? "border-white/10" : "border-red-500/30 bg-red-900/10"}`}>
              <p className="text-xs text-white/40">{label}</p>
              <p className={`mt-1 ${val ? "text-white/90" : "text-red-400 italic"}`}>{val ?? "Not found"}</p>
            </div>;
          })}
        </div>
      </div>
    </>}
  </>;
}

function InsightsPage() {
  const [data, setData] = useState<Insights | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getInsights(), getAgentRuns()])
      .then(([ins, r]) => { setData(ins); setRuns(r.slice(0, 10)); })
      .catch(e => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, []);

  const verdictColor = (v: string) => v === "explained" ? "text-green-400" : v === "unresolved" ? "text-yellow-400" : "text-white/50";
  const statusColor = (s: string) => s === "accepted" ? "text-green-400" : s === "overridden" ? "text-orange-400" : "text-blue-400";

  return <>
    <PageTitle title="AI Insights" subtitle="Real-time statistics calculated from your reconciliation records." />
    <State loading={loading} error={error} />
    {data && <>
      {/* Volume */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-white/40 uppercase mb-3">Transaction Volume</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Total Records", data.volume.total_transactions],
            ["Invoices", data.volume.invoices],
            ["Purchase Orders", data.volume.purchase_orders],
            ["Payments", data.volume.payments],
          ].map(([label, val]) => <div key={String(label)} className="card p-5">
            <p className="text-xs text-white/40">{label}</p>
            <p className="text-3xl font-semibold mt-1">{val}</p>
          </div>)}
        </div>
      </section>

      {/* Matching */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-white/40 uppercase mb-3">Matching</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Total Matches", data.matching.total_matches],
            ["Matched Invoices", data.matching.matched_invoices],
            ["Unmatched Invoices", data.matching.unmatched_invoices],
            ["Match Rate", `${data.matching.match_rate_pct}%`],
          ].map(([label, val]) => <div key={String(label)} className="card p-5">
            <p className="text-xs text-white/40">{label}</p>
            <p className="text-3xl font-semibold mt-1">{val}</p>
          </div>)}
        </div>
        <div className="card p-5 mt-4">
          <p className="text-xs text-white/40 mb-2">Matches by tier</p>
          <div className="flex gap-6">
            {Object.entries(data.matching.by_tier).map(([tier, n]) => <div key={tier}>
              <p className="text-lg font-semibold">{n}</p>
              <p className="text-xs text-white/50 capitalize">{tier}</p>
            </div>)}
          </div>
        </div>
      </section>

      {/* Exceptions */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-white/40 uppercase mb-3">Exceptions</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Total", data.exceptions.total],
            ["Open", data.exceptions.open],
            ["Resolved", data.exceptions.resolved],
            ["High Risk Open", data.exceptions.high_risk_open],
          ].map(([label, val]) => <div key={String(label)} className="card p-5">
            <p className="text-xs text-white/40">{label}</p>
            <p className="text-3xl font-semibold mt-1">{val}</p>
          </div>)}
        </div>
        <div className="grid gap-4 sm:grid-cols-2 mt-4">
          <div className="card p-5">
            <p className="text-xs text-white/40 mb-3">Exceptions by type</p>
            <div className="space-y-2">
              {Object.entries(data.exceptions.by_type).map(([type, n]) => {
                const pct = data.exceptions.total ? Math.round(n / data.exceptions.total * 100) : 0;
                return <div key={type}>
                  <div className="flex justify-between text-xs mb-1"><span>{type}</span><span>{n}</span></div>
                  <div className="h-1.5 w-full rounded bg-white/10"><div className="h-1.5 rounded bg-blue-500" style={{ width: `${pct}%` }} /></div>
                </div>;
              })}
            </div>
          </div>
          <div className="card p-5">
            <p className="text-xs text-white/40 mb-3">Most frequent exceptions</p>
            <div className="space-y-3">
              {data.exceptions.recurring_types.map((item, i) => <div key={item.type} className="flex items-center gap-3">
                <span className="text-2xl font-bold text-white/20">0{i + 1}</span>
                <div><p className="text-sm font-medium">{item.type}</p><p className="text-xs text-white/40">{item.count} occurrences</p></div>
              </div>)}
            </div>
          </div>
        </div>
      </section>

      {/* AI & Adjustments */}
      <section className="mb-6">
        <h2 className="text-sm font-medium text-white/40 uppercase mb-3">AI Activity & Adjustments</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            ["Agent Investigations", data.ai.agent_runs],
            ["Explained by AI", data.ai.agent_explained],
            ["Pending AI Review", data.ai.agent_pending_review],
            ["AI Suggestions", data.ai.ai_suggestions],
            ["Suggestions Accepted", data.ai.ai_suggestions_accepted],
            ["Pending Adjustments", data.adjustments.pending],
          ].map(([label, val]) => <div key={String(label)} className="card p-5">
            <p className="text-xs text-white/40">{label}</p>
            <p className="text-3xl font-semibold mt-1">{val}</p>
          </div>)}
        </div>
      </section>

      {/* Recent investigations */}
      {runs.length > 0 && <section className="card overflow-hidden">
        <div className="p-5 border-b border-white/10"><h2 className="font-medium">Recent AI Investigations</h2></div>
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 text-xs uppercase text-white/40">
            <tr><th className="p-4">Exception</th><th>Verdict</th><th>Review status</th><th>Source</th><th>When</th></tr>
          </thead>
          <tbody>
            {runs.map(r => {
              const parsed = (() => { try { return JSON.parse(r.explanation); } catch { return {}; } })();
              return <tr key={r.id} className="border-b border-white/5 last:border-0">
                <td className="p-4 font-mono text-xs text-white/60">{r.exception_id.slice(0, 8)}…</td>
                <td><span className={`font-medium ${verdictColor(r.verdict)}`}>{r.verdict}</span></td>
                <td><span className={`text-xs ${statusColor(r.status)}`}>{r.status}</span></td>
                <td className="text-xs text-white/50">{r.source}</td>
                <td className="text-xs text-white/50">{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
              </tr>;
            })}
          </tbody>
        </table>
      </section>}
    </>}
  </>;
}

function AiAgentPanel({ exceptionId, onClose }: { exceptionId: string; onClose: () => void }) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [acting, setActing] = useState("");
  const user = getAuthUser();
  const canApprove = user?.role === "approver" || user?.role === "admin";

  const load = () => {
    setLoading(true);
    getAgentRuns()
      .then(all => setRuns(all.filter(r => r.exception_id === exceptionId).slice(0, 5)))
      .catch(e => setError(errorText(e)))
      .finally(() => setLoading(false));
  };
  useEffect(load, [exceptionId]);

  const investigate = async () => {
    setRunning(true); setError("");
    try { await investigateException(exceptionId); load(); }
    catch (e) { setError(errorText(e)); }
    finally { setRunning(false); }
  };

  const act = async (runId: string, action: "accept" | "override") => {
    setActing(runId + action);
    try {
      if (action === "accept") await acceptRun(runId);
      else await overrideRun(runId);
      load();
    } catch (e) { setError(errorText(e)); }
    finally { setActing(""); }
  };

  const latestPending = runs.find(r => r.status === "pending");
  const verdictColor = (v: string) => v === "explained" ? "text-green-400" : v === "unresolved" ? "text-yellow-400" : "text-white/50";

  return <div className="card mt-5 p-6">
    <div className="flex items-center justify-between mb-4">
      <h3 className="font-semibold">🤖 AI Exception Analyst</h3>
      <div className="flex gap-2">
        <button className="button-primary text-xs" disabled={running} onClick={investigate}>
          {running ? "Investigating…" : "Run AI Investigation"}
        </button>
        <button className="text-white/50 text-xs" onClick={onClose}>Close</button>
      </div>
    </div>
    {error && <p className="text-sm text-red-300 mb-3">{error}</p>}
    {loading && <p className="text-sm text-white/40">Loading…</p>}
    {!loading && runs.length === 0 && <p className="text-sm text-white/40">No investigations yet. Click "Run AI Investigation" to analyse this exception.</p>}
    {runs.map(run => {
      const parsed = (() => { try { return JSON.parse(run.explanation); } catch { return {}; } })();
      const claims: { text: string; record_ids: string[] }[] = Array.isArray(parsed.claims) ? parsed.claims : [];
      return <div key={run.id} className="mb-5 border border-white/10 rounded-xl p-4">
        <div className="flex justify-between items-start mb-2">
          <div>
            <span className={`font-semibold ${verdictColor(run.verdict)}`}>{run.verdict.toUpperCase()}</span>
            <span className="text-xs text-white/40 ml-2">{run.source} · {run.verification_status}</span>
          </div>
          <span className="text-xs text-white/30">{run.status}</span>
        </div>
        {claims.map((claim, i) => <div key={i} className="mb-3">
          <p className="text-sm text-white/80 leading-relaxed">{claim.text}</p>
          {claim.record_ids?.length > 0 && <p className="text-xs text-white/40 mt-1">Records: {claim.record_ids.join(", ")}</p>}
        </div>)}
        {parsed.proposed_action && <p className="text-xs text-blue-300 mt-2">Suggested action: <strong>{parsed.proposed_action}</strong></p>}
        {run.errors?.length > 0 && <div className="mt-2">{run.errors.map((e: string, i: number) => <p key={i} className="text-xs text-red-300">⚠ {e}</p>)}</div>}
        {run.status === "pending" && canApprove && <div className="mt-3 flex gap-2">
          <button className="button-primary text-xs flex-1" disabled={!!acting} onClick={() => act(run.id, "accept")}>
            {acting === run.id + "accept" ? "…" : "Accept"}
          </button>
          <button className="button-secondary text-xs flex-1" disabled={!!acting} onClick={() => act(run.id, "override")}>
            {acting === run.id + "override" ? "…" : "Override"}
          </button>
        </div>}
      </div>;
    })}
  </div>;
}
function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [filter, setFilter] = useState("");
  useEffect(() => { setLoading(true); getAudit(filter).then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); }, [filter]);
  return <><PageTitle title="Audit log" subtitle="Every pipeline decision, in one place." /><input className="field mb-5" placeholder="Filter by entity type" value={filter} onChange={e => setFilter(e.target.value)} /><State loading={loading} error={error} empty={!loading && !error && !items.length} />{!loading && !error && !!items.length && <div className="card overflow-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Time</th><th>Action</th><th>Entity</th><th>Actor</th><th>Formula</th></tr></thead><tbody>{items.map(item => <tr key={item.id} className="border-b border-white/5 last:border-0"><td className="p-4 text-white/50">{new Date(item.timestamp).toLocaleString()}</td><td>{item.action}</td><td>{item.entity_type} · {item.entity_id}</td><td>{item.actor}</td><td className="text-white/60">{item.formula}</td></tr>)}</tbody></table></div>}</>;
}
function Landing() { return <LandingCta />; }
function App() { return <BrowserRouter><Routes><Route path="/" element={<Landing />} /><Route path="/login" element={<LoginPage />} /><Route path="/app" element={<ProtectedRoute><Layout /></ProtectedRoute>}><Route index element={<Dashboard />} /><Route path="exceptions" element={<ExceptionsPage />} /><Route path="adjustments" element={<AdjustmentsPage />} /><Route path="audit" element={<AuditPage />} /><Route path="extract" element={<ExtractPage />} /><Route path="insights" element={<InsightsPage />} /></Route></Routes></BrowserRouter>; }
export default App;
