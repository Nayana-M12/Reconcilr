import { useEffect, useState } from "react";
import { EvaluationReport, getEvaluationReport } from "../api";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

const pct = (value: number | null | undefined) =>
  value == null ? "N/A" : `${(value * 100).toFixed(1)}%`;

export default function EvaluationPage() {
  const [report, setReport] = useState<EvaluationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    getEvaluationReport()
      .then(setReport)
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <header className="app-page-title mb-8">
        <h1 className="text-2xl font-semibold">Evaluation</h1>
        <p className="mt-1 text-sm text-white/45">
          Benchmark metrics from labeled synthetic records and document extraction fixtures.
        </p>
      </header>

      {loading && <div className="card p-8 text-sm text-white/50">Loading evaluation report...</div>}
      {error && <div className="card border-red-400/20 p-5 text-sm text-red-200">{error}</div>}

      {!loading && !error && report && (
        <div className="space-y-6">
          <div className="dashboard-summary">
            <div className="card dashboard-card">
              <p className="dashboard-label">Matching precision / recall</p>
              <strong>{pct(report.matching.precision)}</strong>
              <p>
                Recall {pct(report.matching.recall)} ({report.matching.actual_count}/
                {report.matching.expected_count})
              </p>
            </div>
            <div className="card dashboard-card">
              <p className="dashboard-label">Duplicate detection</p>
              <strong>{pct(report.duplicates.detection_rate)}</strong>
              <p>False positives: {report.duplicates.false_positives}</p>
            </div>
            <div className="card dashboard-card">
              <p className="dashboard-label">Hallucination rate</p>
              <strong>{pct(report.hallucination_rate)}</strong>
              <p>Unresolved correctness: {pct(report.unresolved_correctness)}</p>
            </div>
            <div className="card dashboard-card">
              <p className="dashboard-label">Extraction accuracy</p>
              <strong>{pct(report.extraction_accuracy)}</strong>
              <p>Status: {report.extraction_status}</p>
            </div>
          </div>

          <section className="card p-6">
            <h2 className="text-base font-semibold">Exception detection by type</h2>
            <div className="mt-4 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                  <tr>
                    <th className="p-3">Type</th>
                    <th className="p-3">Expected</th>
                    <th className="p-3">Detected</th>
                    <th className="p-3">Precision</th>
                    <th className="p-3">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(report.exceptions.by_type).map(([type, metrics]) => (
                    <tr key={type} className="border-b border-white/5 last:border-0">
                      <td className="p-3 font-medium">{type}</td>
                      <td className="p-3">{metrics.expected}</td>
                      <td className="p-3">{metrics.detected}</td>
                      <td className="p-3">{pct(metrics.precision)}</td>
                      <td className="p-3">{pct(metrics.recall)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {report.extraction_by_field && Object.keys(report.extraction_by_field).length > 0 && (
            <section className="card p-6">
              <h2 className="text-base font-semibold">Document extraction accuracy by field</h2>
              <div className="mt-4 overflow-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                    <tr>
                      <th className="p-3">Field</th>
                      <th className="p-3">Correct</th>
                      <th className="p-3">Total</th>
                      <th className="p-3">Accuracy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.extraction_by_field).map(([field, metrics]) => (
                      <tr key={field} className="border-b border-white/5 last:border-0">
                        <td className="p-3 font-medium">{field}</td>
                        <td className="p-3">{metrics.correct}</td>
                        <td className="p-3">{metrics.total}</td>
                        <td className="p-3">{pct(metrics.accuracy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {report.similarity && Object.keys(report.similarity).length > 0 && (
            <section className="card p-6">
              <h2 className="text-base font-semibold">AI similarity suggestions</h2>
              <div className="mt-4 overflow-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                    <tr>
                      <th className="p-3">Suggestion type</th>
                      <th className="p-3">Expected</th>
                      <th className="p-3">Detected</th>
                      <th className="p-3">Precision</th>
                      <th className="p-3">Recall</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(report.similarity).map(([kind, metrics]) => (
                      <tr key={kind} className="border-b border-white/5 last:border-0">
                        <td className="p-3 font-medium">{kind}</td>
                        <td className="p-3">{metrics.expected_count}</td>
                        <td className="p-3">{metrics.actual_count}</td>
                        <td className="p-3">{pct(metrics.precision)}</td>
                        <td className="p-3">{pct(metrics.recall)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}
