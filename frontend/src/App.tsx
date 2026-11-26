import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import {
  acceptAgentRun,
  Adjustment,
  AgentRun,
  AuditEntry,
  AuthUser,
  clearAuthSession,
  decideAdjustment,
  Exception,
  getAdjustments,
  getAgentRuns,
  getAudit,
  getAuthToken,
  getAuthUser,
  getException,
  getExceptions,
  getMatches,
  getSummary,
  investigateAgent,
  login,
  onUnauthorized,
  overrideAgentRun,
  proposeAdjustments,
  runExceptions,
  runMatching,
  signup,
  Summary,
} from "./api";
import LandingCta from "./components/LandingCta";
import AgentPage, { parseAgentExplanation } from "./pages/AgentPage";
import EvaluationPage from "./pages/EvaluationPage";
import ImportPage from "./pages/ImportPage";
import UsersPage from "./pages/UsersPage";
import "./styles.css";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

const useCountUp = (value: number) => {
  const [displayValue, setDisplayValue] = useState(0);
  const animated = useRef(false);
  useEffect(() => {
    if (animated.current || value === 0) {
      setDisplayValue(value);
      return;
    }
    animated.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplayValue(value);
      return;
    }
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
  ["created", "existing"].forEach((key) => {
    if (typeof result[key] === "number") chips.push(`${key} ${result[key]}`);
  });
  if (Array.isArray(result.unmatched_invoice_ids)) {
    chips.push(`unmatched ${result.unmatched_invoice_ids.length}`);
  }
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

function State({
  loading,
  error,
  empty = false,
}: {
  loading: boolean;
  error: string;
  empty?: boolean;
}) {
  if (loading) return <div className="card p-8 text-sm text-white/50">Loading...</div>;
  if (error) return <div className="card border-red-400/20 p-5 text-sm text-red-200">{error}</div>;
  if (empty) return <div className="card p-8 text-sm text-white/50">No records found.</div>;
  return null;
}

function AuthPage({ initialMode = "signin" }: { initialMode?: "signin" | "signup" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { message?: string; from?: string } | null;
  const [mode, setMode] = useState<"signin" | "signup">(initialMode);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(state?.message || "");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setMode(initialMode);
  }, [initialMode]);

  if (getAuthToken() && getAuthUser()) {
    return <Navigate to="/app" replace />;
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (mode === "signup" && password.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "signin") {
        await login(username.trim(), password);
      } else {
        await signup(username.trim(), email.trim(), password);
      }
      navigate(state?.from || "/app", { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell">
      <div className="card auth-card">
        <Link to="/" className="auth-brand">
          Reconcilr<span>.</span>
        </Link>
        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signin"}
            className={mode === "signin" ? "auth-tab active" : "auth-tab"}
            onClick={() => {
              setMode("signin");
              setError("");
            }}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "signup"}
            className={mode === "signup" ? "auth-tab active" : "auth-tab"}
            onClick={() => {
              setMode("signup");
              setError("");
            }}
          >
            Sign up
          </button>
        </div>
        <h1>{mode === "signin" ? "Sign in" : "Create account"}</h1>
        <p className="auth-sub">
          {mode === "signin"
            ? "Authenticate with your Reconcilr account to open the control room."
            : "Create an analyst account to start importing and reconciling immediately."}
        </p>
        {error && <div className="auth-alert">{error}</div>}
        <form onSubmit={handleSubmit} className="auth-form">
          <label className="auth-label">
            <span>Username</span>
            <input
              className="field w-full"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={mode === "signin" ? "admin" : "yourname"}
              required
            />
          </label>
          {mode === "signup" && (
            <label className="auth-label">
              <span>Email</span>
              <input
                className="field w-full"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
                required
              />
            </label>
          )}
          <label className="auth-label">
            <span>{mode === "signin" ? "Password" : "Password (min 8 characters)"}</span>
            <input
              className="field w-full"
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              minLength={mode === "signup" ? 8 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              required
            />
          </label>
          <button className="button-primary w-full" type="submit" disabled={submitting}>
            {submitting
              ? mode === "signin"
                ? "Signing in..."
                : "Creating account..."
              : mode === "signin"
                ? "Sign in"
                : "Sign up"}
          </button>
        </form>
        <div className="auth-footer-links">
          <Link to="/">← Back to landing</Link>
          <button
            type="button"
            className="auth-switch-link"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError("");
            }}
          >
            {mode === "signin" ? "Need an account? Sign up" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RequireAuth() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = getAuthToken();

  useEffect(() => {
    return onUnauthorized((reason) => {
      navigate("/login", { replace: true, state: { message: reason, from: location.pathname } });
    });
  }, [navigate, location.pathname]);

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Layout />;
}

function Layout() {
  const navigate = useNavigate();
  const user: AuthUser | null = getAuthUser();
  const links: [string, string, string][] = [
    ["/app", "Overview", "⌂"],
    ["/app/import", "Import", "↑"],
    ["/app/exceptions", "Exceptions", "◇"],
    ["/app/adjustments", "Adjustments", "＋"],
    ["/app/agent", "Agent runs", "✦"],
    ["/app/evaluation", "Evaluation", "◎"],
    ["/app/audit", "Audit log", "≡"],
    ...(user?.role === "admin" ? ([["/app/users", "Users", "◈"]] as [string, string, string][]) : []),
  ];

  const handleSignOut = () => {
    clearAuthSession();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen md:flex">
      <aside className="app-sidebar border-b border-white/10 p-5 md:flex md:min-h-screen md:w-64 md:flex-col md:justify-between md:border-b-0 md:border-r">
        <div>
          <Link to="/app" className="text-lg font-semibold tracking-tight">
            Reconcilr<span className="text-white/40">.</span>
          </Link>
          <nav className="app-nav mt-8 flex gap-2 overflow-auto md:block md:space-y-1">
            {links.map(([to, label, icon]) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/app"}
                className={({ isActive }) =>
                  `block whitespace-nowrap rounded-lg px-3 py-2 text-sm ${
                    isActive ? "bg-white/10 text-white" : "text-white/50 hover:bg-white/5 hover:text-white"
                  }`
                }
              >
                <span className="nav-icon" aria-hidden="true">
                  {icon}
                </span>
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        {user && (
          <div className="sidebar-user mt-6 border-t border-white/15 pt-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-white">{user.username}</p>
                <span className="status-badge mt-1 inline-block" data-status={user.role}>
                  {user.role}
                </span>
              </div>
              <button className="button-secondary px-3 py-1.5 text-xs" onClick={handleSignOut}>
                Sign out
              </button>
            </div>
          </div>
        )}
      </aside>
      <main className="app-main w-full max-w-7xl p-5 md:p-10">
        <Outlet />
      </main>
    </div>
  );
}

function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="app-page-title mb-8">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-1 text-sm text-white/45">{subtitle}</p>
    </header>
  );
}

function Dashboard() {
  const user = getAuthUser();
  const canRunPipeline = user?.role === "analyst" || user?.role === "admin";
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [rawOpen, setRawOpen] = useState(false);
  const [matches, setMatches] = useState<Record<string, unknown>[]>([]);
  const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [activity, setActivity] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const refreshAll = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [nextSummary, nextMatches, nextExceptions, nextActivity] = await Promise.all([
        getSummary(),
        getMatches(),
        getExceptions({}),
        getAudit("", 5),
      ]);
      setSummary(nextSummary);
      setMatches(nextMatches);
      setExceptions(nextExceptions.slice(-5).reverse());
      setActivity(nextActivity.slice(0, 5));
      setError("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAll(true);
  }, [refreshAll]);

  const run = async (name: string, action: () => Promise<Record<string, unknown> | Adjustment[]>) => {
    setRunning(name);
    setError("");
    setResult(null);
    try {
      const value = await action();
      setResult(Array.isArray(value) ? { created: value.length } : value);
      await refreshAll(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setRunning("");
    }
  };

  const matchCount = useCountUp(summary?.matches || 0);
  const openCount = useCountUp(summary?.open_exceptions || 0);
  const pendingCount = useCountUp(summary?.pending_adjustments || 0);
  const tiers = matches.reduce<Record<string, number>>((counts, match) => {
    const tier = String(match.tier || "unknown");
    counts[tier] = (counts[tier] || 0) + 1;
    return counts;
  }, {});
  const pipelineActions: [
    string,
    string,
    string,
    () => Promise<Record<string, unknown> | Adjustment[]>,
  ][] = [
    ["matching", "Match", "Run matching", runMatching],
    ["exceptions", "Detect exceptions", "Detect exceptions", runExceptions],
    ["adjustments", "Propose adjustments", "Propose adjustments", proposeAdjustments],
  ];

  return (
    <>
      <div className="dashboard-hero">
        <div>
          <p className="dashboard-kicker">Reconciliation control room</p>
          <h1>Overview</h1>
          <p>Keep your reconciliation workspace moving.</p>
        </div>
        <div className="dashboard-hero-stat">
          <strong>{matchCount} matches reconciled</strong>
          <span>{openCount} open exceptions</span>
          <button
            className="button-secondary mt-3 px-3 py-1 text-xs"
            disabled={loading || !!running}
            onClick={() => refreshAll(true)}
          >
            Refresh live data
          </button>
        </div>
      </div>
      <State loading={loading} error={error} />
      {summary && (
        <div className="dashboard-summary">
          <div className="card dashboard-card dashboard-card-matches">
            <p className="dashboard-label">Matches</p>
            <strong>{matchCount}</strong>
            <div className="match-bar">
              <span
                style={{
                  width: `${summary.matches ? ((tiers.exact || 0) / summary.matches) * 100 : 0}%`,
                }}
              />
              <span
                style={{
                  width: `${summary.matches ? ((tiers.tolerance || 0) / summary.matches) * 100 : 0}%`,
                }}
              />
            </div>
            <div className="match-legend">
              <span>Exact {tiers.exact || 0}</span>
              <span>Tolerance {tiers.tolerance || 0}</span>
              <span>Fuzzy {tiers.fuzzy || 0}</span>
            </div>
          </div>
          <div className="card dashboard-card dashboard-card-exceptions">
            <p className="dashboard-label">Open exceptions</p>
            <strong>{openCount}</strong>
            <p>
              <i />
              {summary.resolved_exceptions} resolved
            </p>
          </div>
          <div className="card dashboard-card dashboard-card-resolved">
            <p className="dashboard-label">Resolved exceptions</p>
            <strong>{summary.resolved_exceptions}</strong>
            <p>Evidence attached to every decision</p>
          </div>
          <div className="card dashboard-card dashboard-card-adjustments">
            <p className="dashboard-label">Pending adjustments</p>
            <strong>{pendingCount}</strong>
            <Link to="/app/adjustments">
              Review <span>↗</span>
            </Link>
          </div>
        </div>
      )}
      <section className="card pipeline-card">
        <div className="section-heading">
          <div>
            <p className="dashboard-kicker">Workflow</p>
            <h2>Run pipeline</h2>
          </div>
          <span className="section-note">
            {canRunPipeline ? "Process stages in order" : "Analyst or admin role required to run"}
          </span>
        </div>
        <div className="pipeline-steps">
          <div className="pipeline-step">
            <span className="pipeline-number">01</span>
            <strong>Import</strong>
            <Link to="/app/import" className="text-xs text-coral underline">
              Upload files ↗
            </Link>
          </div>
          <span className="pipeline-arrow">→</span>
          {pipelineActions.map(([key, title, label, action]) => (
            <div className="pipeline-step pipeline-runnable" key={key}>
              <span className="pipeline-number">
                {key === "matching" ? "02" : key === "exceptions" ? "03" : "04"}
              </span>
              <strong>{title}</strong>
              <button
                className="button-primary"
                disabled={!!running || !canRunPipeline}
                onClick={() => run(key, action)}
              >
                {running === key ? "Running..." : label}
              </button>
            </div>
          ))}
          <span className="pipeline-arrow">→</span>
          <div className="pipeline-step">
            <span className="pipeline-number">05</span>
            <strong>Route approval</strong>
            <Link to="/app/adjustments" className="text-xs text-coral underline">
              Review queue ↗
            </Link>
          </div>
        </div>
        {result && (
          <div className="pipeline-result">
            <div className="result-chips">
              {resultChips(result).map((chip) => (
                <span key={chip}>{chip}</span>
              ))}
            </div>
            <button className="raw-toggle" onClick={() => setRawOpen(!rawOpen)}>
              {rawOpen ? "Hide raw JSON" : "View raw JSON"}
            </button>
            {rawOpen && <pre>{JSON.stringify(result, null, 2)}</pre>}
          </div>
        )}
      </section>
      <div className="dashboard-lower">
        <section className="card activity-card">
          <div className="section-heading">
            <h2>Recent exceptions</h2>
            <Link to="/app/exceptions">View all ↗</Link>
          </div>
          {exceptions.length ? (
            <div className="recent-list">
              {exceptions.map((item) => (
                <div className="recent-row" key={item.id}>
                  <div>
                    <strong>{item.type}</strong>
                    <span>{item.description}</span>
                  </div>
                  <span className="status-badge" data-status={item.status}>
                    {item.status}
                  </span>
                  <span className="status-badge" data-status={item.severity}>
                    {item.severity}
                  </span>
                  <Link to={`/app/exceptions?id=${encodeURIComponent(item.id)}`}>Detail ↗</Link>
                </div>
              ))}
            </div>
          ) : (
            <State loading={loading} error="" empty={!loading} />
          )}
        </section>
        <section className="card activity-card">
          <div className="section-heading">
            <h2>Recent activity</h2>
            <Link to="/app/audit">View audit ↗</Link>
          </div>
          {activity.length ? (
            <div className="recent-list">
              {activity.map((item) => (
                <div className="activity-row" key={item.id}>
                  <span className="activity-dot" />
                  <div>
                    <strong>{item.action}</strong>
                    <span>
                      {item.entity_type} · {item.entity_id}
                    </span>
                  </div>
                  <time>{new Date(item.timestamp).toLocaleDateString()}</time>
                </div>
              ))}
            </div>
          ) : (
            <State loading={loading} error="" empty={!loading} />
          )}
        </section>
      </div>
    </>
  );
}

function ExceptionsPage() {
  const user = getAuthUser();
  const canUseAgent = user?.role !== "auditor";
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<Exception[]>([]);
  const [selected, setSelected] = useState<Exception | null>(null);
  const [agentRun, setAgentRun] = useState<AgentRun | null>(null);
  const [highlightedRecordId, setHighlightedRecordId] = useState<string>("");
  const [agentLoading, setAgentLoading] = useState(false);
  const [agentSaving, setAgentSaving] = useState(false);
  const [agentNote, setAgentNote] = useState("");
  const [agentError, setAgentError] = useState("");
  const [filters, setFilters] = useState({ type: "", status: "", severity: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const loadSelected = useCallback(async (id: string) => {
    setError("");
    setAgentError("");
    setHighlightedRecordId("");
    try {
      const [detail, runs] = await Promise.all([getException(id), getAgentRuns()]);
      setSelected(detail);
      setAgentRun(runs.find((r) => r.exception_id === id) || null);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    getExceptions(Object.fromEntries(Object.entries(filters).filter(([, value]) => value)))
      .then(setItems)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [filters.type, filters.status, filters.severity]);

  const queryId = searchParams.get("id");
  useEffect(() => {
    if (queryId && (!selected || selected.id !== queryId)) {
      loadSelected(queryId);
    }
  }, [queryId, selected, loadSelected]);

  const handleInvestigate = async () => {
    if (!selected || !canUseAgent) return;
    setAgentLoading(true);
    setAgentError("");
    try {
      const runs = await investigateAgent(selected.id);
      if (runs.length > 0) setAgentRun(runs[0]);
    } catch (e) {
      setAgentError(errorText(e));
    } finally {
      setAgentLoading(false);
    }
  };

  const handleAgentDecision = async (action: "accept" | "override") => {
    if (!agentRun || !canUseAgent) return;
    setAgentSaving(true);
    setAgentError("");
    try {
      const updated =
        action === "accept"
          ? await acceptAgentRun(agentRun.id, agentNote)
          : await overrideAgentRun(agentRun.id, agentNote);
      setAgentRun(updated);
      setAgentNote("");
    } catch (e) {
      setAgentError(errorText(e));
    } finally {
      setAgentSaving(false);
    }
  };

  const parsedAgent = agentRun ? parseAgentExplanation(agentRun.explanation) : null;

  return (
    <>
      <PageTitle title="Exceptions" subtitle="Review issues detected across your records." />
      <div className="mb-5 flex flex-wrap gap-2">
        {(["type", "status", "severity"] as const).map((field) => (
          <input
            key={field}
            className="field"
            placeholder={field[0].toUpperCase() + field.slice(1)}
            value={filters[field]}
            onChange={(e) => setFilters({ ...filters, [field]: e.target.value })}
          />
        ))}
      </div>
      <State loading={loading} error={error} empty={!loading && !error && !items.length} />
      {!loading && !error && !!items.length && (
        <div className="card overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/10 text-xs uppercase text-white/40">
              <tr>
                <th className="p-4">Type</th>
                <th>Status</th>
                <th>Severity</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => {
                    setSearchParams({ id: item.id });
                    loadSelected(item.id);
                  }}
                  className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"
                >
                  <td className="p-4 font-medium">{item.type}</td>
                  <td>
                    <span className="status-badge" data-status={item.status}>
                      {item.status}
                    </span>
                  </td>
                  <td>
                    <span className="status-badge" data-status={item.severity}>
                      {item.severity}
                    </span>
                  </td>
                  <td className="max-w-md truncate pr-4 text-white/60">{item.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <div className="detail-panel card mt-5 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase text-white/40">Exception detail</p>
              <h2 className="mt-1 font-semibold">{selected.type}</h2>
              <p className="mt-2 text-sm text-white/60">{selected.description}</p>
            </div>
            <div className="flex items-center gap-3">
              {canUseAgent && (
                <button
                  className="button-primary"
                  disabled={agentLoading}
                  onClick={handleInvestigate}
                >
                  {agentLoading ? "Investigating..." : "Investigate with agent"}
                </button>
              )}
              <button
                className="text-white/50"
                onClick={() => {
                  setSelected(null);
                  setAgentRun(null);
                  setSearchParams({});
                }}
              >
                Close
              </button>
            </div>
          </div>

          <h3 className="mt-6 text-sm font-medium">Evidence</h3>
          <div className="mt-3 space-y-2">
            {selected.evidence.length ? (
              selected.evidence.map((e) => (
                <div
                  className={`rounded-lg border p-3 text-sm ${
                    highlightedRecordId === e.record_id
                      ? "evidence-highlight"
                      : "border-white/10"
                  }`}
                  key={e.id}
                >
                  <span className="text-white/50">
                    {e.record_type} · {e.record_id}
                  </span>
                  <p className="mt-1 text-white/70">{e.note}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-white/50">No evidence attached.</p>
            )}
          </div>

          <div className="mt-6 border-t border-white/10 pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Grounded AI investigation</h3>
              <Link to="/app/agent" className="text-xs text-coral underline">
                All agent runs ↗
              </Link>
            </div>
            {agentError && <div className="auth-alert mt-3">{agentError}</div>}
            {!agentRun ? (
              <p className="mt-2 text-sm text-white/45">
                {canUseAgent
                  ? 'Click "Investigate with agent" to run a verified investigation citing only real record IDs.'
                  : "No agent investigation recorded for this exception yet."}
              </p>
            ) : (
              <div className="mt-3 space-y-4">
                <div className="flex flex-wrap gap-2">
                  <span className="status-badge" data-status={agentRun.verdict}>
                    verdict: {agentRun.verdict}
                  </span>
                  <span className="status-badge">source: {agentRun.source}</span>
                  <span className="status-badge" data-status={agentRun.verification_status}>
                    {agentRun.verification_status}
                  </span>
                  <span className="status-badge" data-status={agentRun.status}>
                    {agentRun.status}
                  </span>
                </div>

                {parsedAgent?.proposed_action && (
                  <div className="rounded-lg border border-white/10 p-3 text-sm">
                    <span className="text-xs uppercase text-white/45">Proposed action</span>
                    <p className="mt-1 font-medium">{parsedAgent.proposed_action}</p>
                    {parsedAgent.draft_note && (
                      <p className="mt-1 text-xs text-white/65">{parsedAgent.draft_note}</p>
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  {agentRun.claims.map((claim, idx) => (
                    <div key={idx} className="rounded-lg border border-white/10 p-3 text-sm">
                      <p className="text-white/85">{claim.text}</p>
                      {claim.record_ids.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {claim.record_ids.map((rid) => (
                            <button
                              type="button"
                              key={rid}
                              className="record-chip"
                              onClick={() => setHighlightedRecordId(rid)}
                              title="Highlight matching evidence record"
                            >
                              {rid}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {canUseAgent && (
                  <div className="space-y-2">
                    <input
                      className="field w-full"
                      placeholder="Decision note (optional)"
                      value={agentNote}
                      disabled={agentSaving}
                      onChange={(e) => setAgentNote(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <button
                        className="button-primary flex-1"
                        disabled={agentSaving}
                        onClick={() => handleAgentDecision("accept")}
                      >
                        Accept recommendation
                      </button>
                      <button
                        className="button-secondary flex-1"
                        disabled={agentSaving}
                        onClick={() => handleAgentDecision("override")}
                      >
                        Override
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function AdjustmentsPage() {
  const user = getAuthUser();
  const canDecide = user?.role === "approver" || user?.role === "admin";
  const [items, setItems] = useState<Adjustment[]>([]);
  const [selected, setSelected] = useState<Adjustment | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    getAdjustments()
      .then(setItems)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const decide = async (decision: "approved" | "rejected") => {
    if (!selected || !canDecide) return;
    setSaving(true);
    setError("");
    try {
      const updated = await decideAdjustment(selected.id, { decision, comment });
      setSelected(updated);
      setItems(items.map((item) => (item.id === updated.id ? updated : item)));
      setComment("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageTitle
        title="Adjustments"
        subtitle="Approve proposed changes with a clear audit trail."
      />
      <State loading={loading} error={error} empty={!loading && !error && !items.length} />
      {!loading && !!items.length && (
        <div className="grid gap-5 lg:grid-cols-[1fr_420px]">
          <div className="card overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                <tr>
                  <th className="p-4">Status</th>
                  <th>Proposed amount</th>
                  <th>Approvers</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => {
                      setSelected(item);
                      setError("");
                    }}
                    className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"
                  >
                    <td className="p-4">
                      <span className="status-badge" data-status={item.status}>
                        {item.status}
                      </span>
                    </td>
                    <td>{item.proposed_amount}</td>
                    <td>{item.required_approvers.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected && (
            <div className="detail-panel card h-fit p-6">
              <div className="flex justify-between">
                <h2 className="font-semibold">Calculation</h2>
                <button className="text-white/50" onClick={() => setSelected(null)}>
                  Close
                </button>
              </div>
              <div className="mt-4 space-y-2 text-sm">
                <p className="text-white/50">Formula</p>
                <p>{selected.calculation.formula}</p>
                <p className="pt-2 text-white/50">Result</p>
                <p className="text-xl">{selected.calculation.result}</p>
                <p className="pt-2 text-white/50">Records</p>
                {selected.calculation.record_ids.map((id) => (
                  <p key={id}>
                    {id}: {selected.calculation.amounts[id]}
                  </p>
                ))}
              </div>
              <h3 className="mt-6 text-sm font-medium">Approval steps</h3>
              <div className="mt-3 space-y-2">
                {selected.approval_steps.map((step) => (
                  <div
                    className="flex justify-between rounded-lg border border-white/10 p-3 text-sm"
                    key={step.id}
                  >
                    <span>{step.role}</span>
                    <span className="status-badge" data-status={step.decision}>
                      {step.decision}
                    </span>
                  </div>
                ))}
              </div>
              {selected.status === "pending" && (
                <>
                  {!canDecide && (
                    <p className="mt-4 text-xs text-white/50">
                      Signed in as {user?.role || "viewer"}. Approver or admin role is required to
                      approve or reject adjustments.
                    </p>
                  )}
                  <input
                    className="field mt-4 w-full"
                    placeholder="Comment (optional)"
                    value={comment}
                    disabled={!canDecide || saving}
                    onChange={(e) => setComment(e.target.value)}
                  />
                  <div className="mt-3 flex gap-2">
                    <button
                      className="button-primary flex-1"
                      disabled={saving || !canDecide}
                      onClick={() => decide("approved")}
                    >
                      Approve
                    </button>
                    <button
                      className="button-secondary flex-1"
                      disabled={saving || !canDecide}
                      onClick={() => decide("rejected")}
                    >
                      Reject
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    getAudit(filter)
      .then(setItems)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <>
      <PageTitle title="Audit log" subtitle="Every pipeline decision, in one place." />
      <input
        className="field mb-5"
        placeholder="Filter by entity type"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <State loading={loading} error={error} empty={!loading && !error && !items.length} />
      {!loading && !error && !!items.length && (
        <div className="card overflow-auto">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="border-b border-white/10 text-xs uppercase text-white/40">
              <tr>
                <th className="p-4">Time</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Actor</th>
                <th>Formula</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-white/5 last:border-0">
                  <td className="p-4 text-white/50">
                    {new Date(item.timestamp).toLocaleString()}
                  </td>
                  <td>{item.action}</td>
                  <td>
                    {item.entity_type} · {item.entity_id}
                  </td>
                  <td>{item.actor}</td>
                  <td className="text-white/60">{item.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Landing() {
  return <LandingCta />;
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<AuthPage initialMode="signin" />} />
        <Route path="/signup" element={<AuthPage initialMode="signup" />} />
        <Route path="/app" element={<RequireAuth />}>
          <Route index element={<Dashboard />} />
          <Route path="import" element={<ImportPage />} />
          <Route path="exceptions" element={<ExceptionsPage />} />
          <Route path="adjustments" element={<AdjustmentsPage />} />
          <Route path="agent" element={<AgentPage />} />
          <Route path="evaluation" element={<EvaluationPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="users" element={<UsersPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
