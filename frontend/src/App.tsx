import { useEffect, useState } from "react";
import { BrowserRouter, Link, NavLink, Outlet, Route, Routes } from "react-router-dom";
import {
  Adjustment, AuditEntry, Exception, decideAdjustment, getAdjustment, getAdjustments, getAudit,
  getException, getExceptions, getSummary, proposeAdjustments, runExceptions, runMatching, Summary,
} from "./api";
import "./styles.css";

const errorText = (error: unknown) => error instanceof Error ? error.message : "Something went wrong.";
function State({ loading, error, empty = false }: { loading: boolean; error: string; empty?: boolean }) {
  if (loading) return <div className="card p-8 text-sm text-white/50">Loading...</div>;
  if (error) return <div className="card border-red-400/20 p-5 text-sm text-red-200">{error}</div>;
  if (empty) return <div className="card p-8 text-sm text-white/50">No records found.</div>;
  return null;
}
function Layout() {
  const links = [["/app", "Overview"], ["/app/exceptions", "Exceptions"], ["/app/adjustments", "Adjustments"], ["/app/audit", "Audit log"]];
  return <div className="min-h-screen md:flex">
    <aside className="border-b border-white/10 p-5 md:min-h-screen md:w-64 md:border-b-0 md:border-r">
      <Link to="/app" className="text-lg font-semibold tracking-tight">Reconcilr<span className="text-white/40">.</span></Link>
      <nav className="mt-8 flex gap-2 overflow-auto md:block md:space-y-1">
        {links.map(([to, label]) => <NavLink key={to} to={to} end={to === "/app"} className={({ isActive }) => `block whitespace-nowrap rounded-lg px-3 py-2 text-sm ${isActive ? "bg-white/10 text-white" : "text-white/50 hover:bg-white/5 hover:text-white"}`}>{label}</NavLink>)}
      </nav>
    </aside>
    <main className="w-full max-w-7xl p-5 md:p-10"><Outlet /></main>
  </div>;
}
function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="mb-8"><h1 className="text-2xl font-semibold">{title}</h1><p className="mt-1 text-sm text-white/45">{subtitle}</p></header>;
}
function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null); const [error, setError] = useState(""); const [running, setRunning] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { getSummary().then(setSummary).catch(e => setError(errorText(e))); }, []);
  const run = async (name: string, action: () => Promise<Record<string, unknown> | Adjustment[]>) => {
    setRunning(name); setError(""); setResult(null);
    try { const value = await action(); setResult(Array.isArray(value) ? { created: value.length } : value); setSummary(await getSummary()); }
    catch (e) { setError(errorText(e)); } finally { setRunning(""); }
  };
  return <><PageTitle title="Overview" subtitle="Keep your reconciliation workspace moving." />
    <State loading={!summary && !error} error={error} />
    {summary && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[
      ["Matches", summary.matches], ["Open exceptions", summary.open_exceptions], ["Resolved exceptions", summary.resolved_exceptions], ["Pending adjustments", summary.pending_adjustments],
    ].map(([label, value]) => <div className="card p-5" key={label as string}><p className="text-sm text-white/45">{label}</p><p className="mt-3 text-3xl font-semibold">{value}</p></div>)}</div>}
    <section className="card mt-8 p-6"><h2 className="font-medium">Run pipeline</h2><p className="mt-1 text-sm text-white/45">Process new records in order, or run an individual stage.</p>
      <div className="mt-5 flex flex-wrap gap-3">
        {[["matching", "Run matching", runMatching], ["exceptions", "Detect exceptions", runExceptions], ["adjustments", "Propose adjustments", proposeAdjustments]].map(([key, label, action]) =>
          <button key={key as string} className="button-primary" disabled={!!running} onClick={() => run(key as string, action as () => Promise<Record<string, unknown> | Adjustment[]>)}>
            {running === key ? "Running..." : label as string}</button>)}
      </div>
      {result && <pre className="mt-5 overflow-auto rounded-lg bg-black/20 p-4 text-xs text-emerald-200">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  </>;
}
function ExceptionsPage() {
  const [items, setItems] = useState<Exception[]>([]); const [selected, setSelected] = useState<Exception | null>(null);
  const [filters, setFilters] = useState({ type: "", status: "", severity: "" }); const [error, setError] = useState(""); const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); getExceptions(Object.fromEntries(Object.entries(filters).filter(([, value]) => value))).then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); };
  useEffect(load, [filters.type, filters.status, filters.severity]);
  return <><PageTitle title="Exceptions" subtitle="Review issues detected across your records." />
    <div className="mb-5 flex flex-wrap gap-2">{(["type", "status", "severity"] as const).map(field => <input key={field} className="field" placeholder={field[0].toUpperCase() + field.slice(1)} value={filters[field]} onChange={e => setFilters({ ...filters, [field]: e.target.value })} />)}</div>
    <State loading={loading} error={error} empty={!loading && !error && !items.length} />
    {!loading && !error && !!items.length && <div className="card overflow-hidden"><table className="w-full text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Type</th><th>Status</th><th>Severity</th><th>Description</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => getException(item.id).then(setSelected).catch(e => setError(errorText(e)))} className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"><td className="p-4 font-medium">{item.type}</td><td>{item.status}</td><td>{item.severity}</td><td className="max-w-md truncate pr-4 text-white/60">{item.description}</td></tr>)}</tbody></table></div>}
    {selected && <div className="card mt-5 p-6"><div className="flex items-start justify-between"><div><p className="text-xs uppercase text-white/40">Exception detail</p><h2 className="mt-1 font-semibold">{selected.type}</h2><p className="mt-2 text-sm text-white/60">{selected.description}</p></div><button className="text-white/50" onClick={() => setSelected(null)}>Close</button></div><h3 className="mt-6 text-sm font-medium">Evidence</h3><div className="mt-3 space-y-2">{selected.evidence.length ? selected.evidence.map(e => <div className="rounded-lg border border-white/10 p-3 text-sm" key={e.id}><span className="text-white/50">{e.record_type} · {e.record_id}</span><p className="mt-1 text-white/70">{e.note}</p></div>) : <p className="text-sm text-white/50">No evidence attached.</p>}</div></div>}
  </>;
}
function AdjustmentsPage() {
  const [items, setItems] = useState<Adjustment[]>([]); const [selected, setSelected] = useState<Adjustment | null>(null);
  const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [role, setRole] = useState(""); const [comment, setComment] = useState(""); const [saving, setSaving] = useState(false);
  const load = () => { setLoading(true); getAdjustments().then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); }; useEffect(load, []);
  const decide = async (decision: "approved" | "rejected") => { if (!selected || !role) return; setSaving(true); setError(""); try { const updated = await decideAdjustment(selected.id, { role, decision, comment }); setSelected(updated); setItems(items.map(item => item.id === updated.id ? updated : item)); } catch (e) { setError(errorText(e)); } finally { setSaving(false); } };
  return <><PageTitle title="Adjustments" subtitle="Approve proposed changes with a clear audit trail." /><State loading={loading} error={error} empty={!loading && !error && !items.length} />
    {!loading && !error && !!items.length && <div className="grid gap-5 lg:grid-cols-[1fr_420px]"><div className="card overflow-hidden"><table className="w-full text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Status</th><th>Proposed amount</th><th>Approvers</th></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => { setSelected(item); setRole(item.required_approvers.find(r => item.approval_steps.find(s => s.role === r)?.decision === "pending") || ""); }} className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"><td className="p-4">{item.status}</td><td>{item.proposed_amount}</td><td>{item.required_approvers.join(", ")}</td></tr>)}</tbody></table></div>
      {selected && <div className="card h-fit p-6"><div className="flex justify-between"><h2 className="font-semibold">Calculation</h2><button className="text-white/50" onClick={() => setSelected(null)}>Close</button></div><div className="mt-4 space-y-2 text-sm"><p className="text-white/50">Formula</p><p>{selected.calculation.formula}</p><p className="pt-2 text-white/50">Result</p><p className="text-xl">{selected.calculation.result}</p><p className="pt-2 text-white/50">Records</p>{selected.calculation.record_ids.map(id => <p key={id}>{id}: {selected.calculation.amounts[id]}</p>)}</div><h3 className="mt-6 text-sm font-medium">Approval steps</h3><div className="mt-3 space-y-2">{selected.approval_steps.map(step => <div className="flex justify-between rounded-lg border border-white/10 p-3 text-sm" key={step.id}><span>{step.role}</span><span className="text-white/50">{step.decision}</span></div>)}</div>{selected.status === "pending" && <><select className="field mt-5 w-full" value={role} onChange={e => setRole(e.target.value)}><option value="">Select role</option>{selected.required_approvers.map(r => <option key={r}>{r}</option>)}</select><input className="field mt-2 w-full" placeholder="Comment (optional)" value={comment} onChange={e => setComment(e.target.value)} /><div className="mt-3 flex gap-2"><button className="button-primary flex-1" disabled={saving || !role} onClick={() => decide("approved")}>Approve</button><button className="button-secondary flex-1" disabled={saving || !role} onClick={() => decide("rejected")}>Reject</button></div></>}</div>}</div>}
  </>;
}
function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]); const [error, setError] = useState(""); const [loading, setLoading] = useState(true); const [filter, setFilter] = useState("");
  useEffect(() => { setLoading(true); getAudit(filter).then(setItems).catch(e => setError(errorText(e))).finally(() => setLoading(false)); }, [filter]);
  return <><PageTitle title="Audit log" subtitle="Every pipeline decision, in one place." /><input className="field mb-5" placeholder="Filter by entity type" value={filter} onChange={e => setFilter(e.target.value)} /><State loading={loading} error={error} empty={!loading && !error && !items.length} />{!loading && !error && !!items.length && <div className="card overflow-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-white/40"><tr><th className="p-4">Time</th><th>Action</th><th>Entity</th><th>Actor</th><th>Formula</th></tr></thead><tbody>{items.map(item => <tr key={item.id} className="border-b border-white/5 last:border-0"><td className="p-4 text-white/50">{new Date(item.timestamp).toLocaleString()}</td><td>{item.action}</td><td>{item.entity_type} · {item.entity_id}</td><td>{item.actor}</td><td className="text-white/60">{item.formula}</td></tr>)}</tbody></table></div>}</>;
}
function Landing() { return <div className="flex min-h-screen items-center justify-center p-6"><div className="text-center"><p className="text-sm uppercase tracking-[0.3em] text-white/40">Reconcilr</p><h1 className="mt-5 text-4xl font-semibold">Reconciliation, clarified.</h1><Link className="button-primary mt-8 inline-block" to="/app">Open app</Link></div></div>; }
function App() { return <BrowserRouter><Routes><Route path="/" element={<Landing />} /><Route path="/app" element={<Layout />}><Route index element={<Dashboard />} /><Route path="exceptions" element={<ExceptionsPage />} /><Route path="adjustments" element={<AdjustmentsPage />} /><Route path="audit" element={<AuditPage />} /></Route></Routes></BrowserRouter>; }
export default App;
