import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  acceptAgentRun,
  AgentRun,
  getAgentRuns,
  getAuthUser,
  investigateAgent,
  overrideAgentRun,
  ResolutionPlan,
} from "../api";
import ResolutionPlanView from "../components/ResolutionPlanView";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

type ParsedExplanation = {
  verdict?: string;
  proposed_action?: string;
  draft_note?: string;
  claims?: { text: string; record_ids: string[]; tool_call_refs: string[] }[];
  resolution_plan?: ResolutionPlan | null;
};

export function parseAgentExplanation(raw: string): ParsedExplanation | null {
  try {
    return JSON.parse(raw) as ParsedExplanation;
  } catch {
    return null;
  }
}

export default function AgentPage() {
  const user = getAuthUser();
  const canAct = user?.role !== "auditor";
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selected, setSelected] = useState<AgentRun | null>(null);
  const [selectedSolutionId, setSelectedSolutionId] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const selectRun = (run: AgentRun | null) => {
    setSelected(run);
    setError("");
    if (!run) {
      setSelectedSolutionId("");
      return;
    }
    const plan = run.resolution_plan || parseAgentExplanation(run.explanation)?.resolution_plan;
    setSelectedSolutionId(
      run.selected_solution_id ||
        plan?.recommended_solution_id ||
        plan?.possible_solutions?.[0]?.id ||
        "",
    );
  };

  const load = () => {
    setLoading(true);
    setError("");
    getAgentRuns()
      .then((data) => {
        setRuns(data);
        if (selected) {
          const fresh = data.find((r) => r.id === selected.id) || null;
          selectRun(fresh);
        }
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleInvestigateAll = async () => {
    if (!canAct) return;
    setRunning(true);
    setError("");
    try {
      const created = await investigateAgent();
      const updated = await getAgentRuns();
      setRuns(updated);
      if (created.length > 0) selectRun(created[0]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setRunning(false);
    }
  };

  const handleDecision = async (action: "accept" | "override") => {
    if (!selected || !canAct) return;
    setSaving(true);
    setError("");
    try {
      const updated =
        action === "accept"
          ? await acceptAgentRun(selected.id, note, selectedSolutionId || undefined)
          : await overrideAgentRun(selected.id, note);
      selectRun(updated);
      setRuns((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setNote("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const parsed = selected ? parseAgentExplanation(selected.explanation) : null;
  const activePlan = selected?.resolution_plan || parsed?.resolution_plan || null;

  return (
    <>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <header className="app-page-title">
          <h1 className="text-2xl font-semibold">Agent runs</h1>
          <p className="mt-1 text-sm text-white/45">
            Grounded AI investigations with actionable resolution options verified against database records.
          </p>
        </header>
        {canAct && (
          <button
            className="button-primary"
            disabled={running}
            onClick={handleInvestigateAll}
          >
            {running ? "Investigating..." : "Investigate all open exceptions"}
          </button>
        )}
      </div>

      {error && <div className="card mb-5 border-red-400/20 p-5 text-sm text-red-200">{error}</div>}
      {loading && <div className="card p-8 text-sm text-white/50">Loading...</div>}
      {!loading && !error && !runs.length && (
        <div className="card p-8 text-sm text-white/50">
          No agent runs yet. Run an investigation from here or from any exception detail drawer.
        </div>
      )}

      {!loading && !!runs.length && (
        <div className="grid gap-5 lg:grid-cols-[1fr_540px]">
          <div className="card h-fit overflow-auto">
            <table className="w-full min-w-[540px] text-left text-sm">
              <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                <tr>
                  <th className="p-4">Verdict</th>
                  <th>Source</th>
                  <th>Verification</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => selectRun(run)}
                    className="cursor-pointer border-b border-white/5 last:border-0 hover:bg-white/5"
                  >
                    <td className="p-4 font-medium">
                      <span className="status-badge" data-status={run.verdict}>
                        {run.verdict}
                      </span>
                    </td>
                    <td>{run.source}</td>
                    <td>
                      <span className="status-badge" data-status={run.verification_status}>
                        {run.verification_status}
                      </span>
                    </td>
                    <td>
                      <span className="status-badge" data-status={run.status}>
                        {run.status}
                      </span>
                    </td>
                    <td className="text-white/50">
                      {new Date(run.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {selected && (
            <div className="detail-panel card h-fit p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase text-white/40">AI Exception Analyst</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span className="status-badge" data-status={selected.verdict}>
                      {selected.verdict}
                    </span>
                    <span className="status-badge" data-status={selected.verification_status}>
                      {selected.verification_status}
                    </span>
                    <span className="status-badge" data-status={selected.status}>
                      {selected.status}
                    </span>
                    <span className="status-badge">{selected.source}</span>
                  </div>
                </div>
                <button className="text-white/50" onClick={() => selectRun(null)}>
                  Close
                </button>
              </div>

              <div className="mt-4 text-xs text-white/55">
                Exception:{" "}
                <Link
                  to={`/app/exceptions?id=${encodeURIComponent(selected.exception_id)}`}
                  className="text-coral underline"
                >
                  {selected.exception_id} ↗
                </Link>
              </div>

              <h3 className="mt-5 text-sm font-medium">Verified claims &amp; cited records</h3>
              <div className="mt-2 space-y-2">
                {selected.claims.length ? (
                  selected.claims.map((claim, idx) => (
                    <div key={idx} className="rounded-lg border border-white/10 p-3 text-sm">
                      <p className="text-white/85">{claim.text}</p>
                      {claim.record_ids.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {claim.record_ids.map((rid) => (
                            <Link
                              key={rid}
                              to={`/app/exceptions?id=${encodeURIComponent(selected.exception_id)}`}
                              className="record-chip"
                            >
                              {rid}
                            </Link>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-white/50">No claims recorded.</p>
                )}
              </div>

              {activePlan && (
                <div className="mt-5">
                  <ResolutionPlanView
                    plan={activePlan}
                    selectedSolutionId={selectedSolutionId}
                    onSelectSolution={setSelectedSolutionId}
                    selectable={canAct && selected.status === "pending"}
                    committedSolutionId={selected.selected_solution_id}
                  />
                </div>
              )}

              {selected.errors.length > 0 && (
                <div className="auth-alert mt-4">
                  <strong>Verification fallback notes:</strong>
                  <ul className="mt-1 list-disc pl-4">
                    {selected.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {canAct && selected.status === "pending" && (
                <div className="mt-5 border-t border-white/10 pt-4">
                  <input
                    className="field w-full"
                    placeholder="Analyst note / supporting document reference (optional)"
                    value={note}
                    disabled={saving}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <div className="mt-3 flex gap-2">
                    <button
                      className="button-primary flex-1"
                      disabled={saving}
                      onClick={() => handleDecision("accept")}
                    >
                      Submit selected solution for approval
                    </button>
                    <button
                      className="button-secondary flex-1"
                      disabled={saving}
                      onClick={() => handleDecision("override")}
                    >
                      Override
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
