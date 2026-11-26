import { useState } from "react";
import {
  DocumentImportResponse,
  getAuthUser,
  importDocuments,
  importMapped,
  ImportPreviewResponse,
  importRecords,
  ImportResponse,
  MappedImportResponse,
  previewImport,
} from "../api";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

const RECORD_TYPES = [
  { value: "vendor", label: "Vendors" },
  { value: "purchase_order", label: "Purchase orders" },
  { value: "invoice", label: "Invoices" },
  { value: "payment", label: "Payments" },
];

const DATE_FORMATS = [
  { value: "auto", label: "Auto (ISO or unambiguous slash date)" },
  { value: "YYYY-MM-DD", label: "YYYY-MM-DD" },
  { value: "DD/MM/YYYY", label: "DD/MM/YYYY" },
  { value: "MM/DD/YYYY", label: "MM/DD/YYYY" },
];

export default function ImportPage() {
  const user = getAuthUser();
  const canImport = user?.role === "analyst" || user?.role === "admin";
  const [mode, setMode] = useState<"tabular" | "document">("tabular");

  // Tabular CSV/Excel state
  const [recordType, setRecordType] = useState("invoice");
  const [tabularFile, setTabularFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [dateFormat, setDateFormat] = useState("auto");
  const [mappedResult, setMappedResult] = useState<MappedImportResponse | null>(null);
  const [directResult, setDirectResult] = useState<ImportResponse | null>(null);

  // Document PDF/TXT state
  const [docFiles, setDocFiles] = useState<File[]>([]);
  const [docResult, setDocResult] = useState<DocumentImportResponse | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handlePreview = async () => {
    if (!tabularFile || !canImport) return;
    setLoading(true);
    setError("");
    setMappedResult(null);
    setDirectResult(null);
    try {
      const res = await previewImport(tabularFile, recordType);
      setPreview(res);
      setMapping({ ...res.suggested_mapping });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDirectImport = async () => {
    if (!tabularFile || !canImport) return;
    setLoading(true);
    setError("");
    setMappedResult(null);
    try {
      const res = await importRecords(recordType, tabularFile);
      setDirectResult(res);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const handleMappedImport = async () => {
    if (!tabularFile || !preview || !canImport) return;
    setLoading(true);
    setError("");
    try {
      const res = await importMapped(tabularFile, recordType, mapping, dateFormat);
      setMappedResult(res);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDocumentImport = async () => {
    if (!docFiles.length || !canImport) return;
    setLoading(true);
    setError("");
    setDocResult(null);
    try {
      const res = await importDocuments(docFiles);
      setDocResult(res);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  };

  const missingRequired = preview
    ? preview.required_fields.filter((field) => !mapping[field])
    : [];

  return (
    <>
      <header className="app-page-title mb-8">
        <h1 className="text-2xl font-semibold">Import data</h1>
        <p className="mt-1 text-sm text-white/45">
          Upload CSV/Excel files with column mapping or extract structured records from PDF and text documents.
        </p>
      </header>

      {!canImport && (
        <div className="card mb-6 p-5 text-sm text-white/70">
          Signed in as <strong>{user?.role}</strong>. Analyst or admin role is required to upload or import files.
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2">
        <button
          className={mode === "tabular" ? "button-primary" : "button-secondary"}
          onClick={() => {
            setMode("tabular");
            setError("");
          }}
        >
          CSV / Excel (Column mapping)
        </button>
        <button
          className={mode === "document" ? "button-primary" : "button-secondary"}
          onClick={() => {
            setMode("document");
            setError("");
          }}
        >
          PDF / TXT Documents
        </button>
      </div>

      {error && <div className="card mb-6 border-red-400/20 p-5 text-sm text-red-200">{error}</div>}
      {loading && <div className="card mb-6 p-6 text-sm text-white/50">Processing file...</div>}

      {mode === "tabular" && (
        <div className="space-y-6">
          <section className="card p-6">
            <h2 className="text-base font-semibold">1. Choose file &amp; record type</h2>
            <p className="mt-1 text-xs text-white/45">
              Import order for clean linking: Vendors → Purchase orders → Invoices → Payments.
            </p>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              <label className="auth-label">
                <span>Record type</span>
                <select
                  className="field"
                  value={recordType}
                  disabled={!canImport || loading}
                  onChange={(e) => {
                    setRecordType(e.target.value);
                    setPreview(null);
                    setMappedResult(null);
                    setDirectResult(null);
                  }}
                >
                  {RECORD_TYPES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="auth-label md:col-span-2">
                <span>CSV or Excel file (.csv, .xlsx, .xls)</span>
                <input
                  className="field"
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  disabled={!canImport || loading}
                  onChange={(e) => {
                    setTabularFile(e.target.files?.[0] || null);
                    setPreview(null);
                    setMappedResult(null);
                    setDirectResult(null);
                    setError("");
                  }}
                />
              </label>
            </div>
            {canImport && (
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  className="button-primary"
                  disabled={!tabularFile || loading}
                  onClick={handlePreview}
                >
                  Preview &amp; map columns
                </button>
                <button
                  className="button-secondary"
                  disabled={!tabularFile || loading}
                  onClick={handleDirectImport}
                >
                  Direct import (standard columns)
                </button>
              </div>
            )}
          </section>

          {preview && (
            <section className="card p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold">
                    2. Confirm column mapping ({preview.filename})
                  </h2>
                  <p className="mt-1 text-xs text-white/45">
                    {preview.total_rows} rows detected. Unmapped required fields are never guessed.
                  </p>
                </div>
                <label className="auth-label min-w-[240px]">
                  <span>Date format</span>
                  <select
                    className="field"
                    value={dateFormat}
                    onChange={(e) => setDateFormat(e.target.value)}
                  >
                    {DATE_FORMATS.map((fmt) => (
                      <option key={fmt.value} value={fmt.value}>
                        {fmt.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {missingRequired.length > 0 && (
                <div className="auth-alert mt-4">
                  Missing required mappings: <strong>{missingRequired.join(", ")}</strong>
                </div>
              )}

              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {[...preview.required_fields, ...preview.optional_fields].map((field) => {
                  const isReq = preview.required_fields.includes(field);
                  return (
                    <label key={field} className="auth-label">
                      <span>
                        {field} {isReq ? <strong className="text-red-300">*</strong> : "(optional)"}
                      </span>
                      <select
                        className="field"
                        value={mapping[field] || ""}
                        onChange={(e) => setMapping({ ...mapping, [field]: e.target.value })}
                      >
                        <option value="">— Not mapped —</option>
                        {preview.columns.map((col) => (
                          <option key={col} value={col}>
                            {col}
                          </option>
                        ))}
                      </select>
                    </label>
                  );
                })}
              </div>

              {canImport && (
                <div className="mt-5">
                  <button
                    className="button-primary"
                    disabled={loading || missingRequired.length > 0}
                    onClick={handleMappedImport}
                  >
                    Import mapped {recordType} rows
                  </button>
                </div>
              )}

              <h3 className="mt-6 text-sm font-medium text-white/75">
                Preview (first {preview.preview_rows.length} rows)
              </h3>
              {preview.preview_rows.length === 0 ? (
                <p className="mt-2 text-sm text-white/50">File contains no data rows.</p>
              ) : (
                <div className="mt-3 overflow-auto rounded-xl border border-white/10">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-white/10 uppercase text-white/40">
                      <tr>
                        {preview.columns.map((col) => (
                          <th key={col} className="p-3">
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.preview_rows.map((row, idx) => (
                        <tr key={idx} className="border-b border-white/5 last:border-0">
                          {preview.columns.map((col) => (
                            <td key={col} className="p-3 text-white/75">
                              {row[col] || "—"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {mappedResult && (
            <section className="card p-6">
              <h2 className="text-base font-semibold">Mapped import results</h2>
              <div className="result-chips mt-4">
                <span>imported {mappedResult.imported}</span>
                <span>duplicates {mappedResult.duplicates}</span>
                <span>rejected {mappedResult.rejected}</span>
              </div>
              {mappedResult.rejected_rows.length > 0 && (
                <div className="mt-5 overflow-auto rounded-xl border border-white/10">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                      <tr>
                        <th className="p-3">Row</th>
                        <th className="p-3">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mappedResult.rejected_rows.map((item, idx) => (
                        <tr key={idx} className="border-b border-white/5 last:border-0">
                          <td className="p-3 font-medium">{item.row}</td>
                          <td className="p-3 text-red-200">{item.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {directResult && (
            <section className="card p-6">
              <h2 className="text-base font-semibold">Direct import results ({directResult.source_file})</h2>
              <div className="result-chips mt-4">
                <span>imported {directResult.imported}</span>
                <span>duplicates {directResult.duplicates}</span>
                <span>rejected {directResult.rejected}</span>
              </div>
              {directResult.errors.length > 0 && (
                <pre className="mt-4 overflow-auto rounded-xl p-4 text-xs">
                  {JSON.stringify(directResult.errors, null, 2)}
                </pre>
              )}
            </section>
          )}
        </div>
      )}

      {mode === "document" && (
        <div className="space-y-6">
          <section className="card p-6">
            <h2 className="text-base font-semibold">Upload PDF or plain-text documents</h2>
            <p className="mt-1 text-xs text-white/45">
              Deterministic rules extract fields with page &amp; snippet provenance. Missing required fields go to Needs Review and are never guessed.
            </p>
            <div className="mt-4">
              <input
                className="field w-full"
                type="file"
                accept=".pdf,.txt"
                multiple
                disabled={!canImport || loading}
                onChange={(e) => {
                  setDocFiles(Array.from(e.target.files || []));
                  setDocResult(null);
                  setError("");
                }}
              />
            </div>
            {docFiles.length > 0 && (
              <p className="mt-2 text-xs text-white/50">
                Selected: {docFiles.map((f) => f.name).join(", ")}
              </p>
            )}
            {canImport && (
              <div className="mt-4">
                <button
                  className="button-primary"
                  disabled={!docFiles.length || loading}
                  onClick={handleDocumentImport}
                >
                  Extract &amp; import documents
                </button>
              </div>
            )}
          </section>

          {docResult && (
            <div className="space-y-6">
              <section className="card p-6">
                <h2 className="text-base font-semibold">Extraction summary</h2>
                <div className="result-chips mt-4">
                  <span>imported {docResult.imported.length}</span>
                  <span>duplicates {docResult.duplicates.length}</span>
                  <span>needs review {docResult.needs_review.length}</span>
                  <span>unsupported {docResult.unsupported.length}</span>
                </div>
              </section>

              {docResult.imported.length > 0 && (
                <section className="card p-6">
                  <h3 className="text-sm font-semibold">Imported documents</h3>
                  <div className="mt-3 overflow-auto">
                    <table className="w-full text-left text-sm">
                      <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                        <tr>
                          <th className="p-3">File</th>
                          <th className="p-3">Type</th>
                          <th className="p-3">Record ID</th>
                          <th className="p-3">Amount</th>
                          <th className="p-3">Vendor</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docResult.imported.map((item) => (
                          <tr key={item.record_id} className="border-b border-white/5 last:border-0">
                            <td className="p-3 font-medium">{item.filename}</td>
                            <td className="p-3">{item.record_type}</td>
                            <td className="p-3 font-mono text-xs">{item.record_id}</td>
                            <td className="p-3">
                              {item.fields_found.currency} {item.fields_found.total_amount}
                            </td>
                            <td className="p-3">{item.fields_found.vendor}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {docResult.duplicates.length > 0 && (
                <section className="card p-6">
                  <h3 className="text-sm font-semibold">Duplicate documents (skipped)</h3>
                  <div className="mt-3 space-y-2 text-sm">
                    {docResult.duplicates.map((item, idx) => (
                      <div key={idx} className="rounded-lg border border-white/10 p-3">
                        <strong>{item.filename}</strong> · {item.document_type} —{" "}
                        <span className="text-white/60">{item.detail}</span>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {docResult.needs_review.length > 0 && (
                <section className="card p-6">
                  <h3 className="text-sm font-semibold">Needs review (not imported)</h3>
                  <div className="mt-3 overflow-auto">
                    <table className="w-full min-w-[720px] text-left text-sm">
                      <thead className="border-b border-white/10 text-xs uppercase text-white/40">
                        <tr>
                          <th className="p-3">File</th>
                          <th className="p-3">Fields found</th>
                          <th className="p-3">Fields missing</th>
                          <th className="p-3">Provenance (page &amp; snippet)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docResult.needs_review.map((item, idx) => (
                          <tr key={idx} className="border-b border-white/5 align-top last:border-0">
                            <td className="p-3 font-medium">
                              <div>{item.filename}</div>
                              <span className="text-xs text-white/45">
                                {item.document_type || "unclassified"}
                              </span>
                            </td>
                            <td className="p-3 text-xs">
                              {Object.entries(item.fields_found).length ? (
                                Object.entries(item.fields_found).map(([k, v]) => (
                                  <div key={k}>
                                    <span className="text-white/50">{k}:</span> {v}
                                  </div>
                                ))
                              ) : (
                                <span className="text-white/40">None</span>
                              )}
                            </td>
                            <td className="p-3">
                              <div className="flex flex-wrap gap-1.5">
                                {item.fields_missing.map((field) => (
                                  <span key={field} className="status-badge" data-status="rejected">
                                    {field}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="p-3 text-xs text-white/70">
                              {Object.entries(item.provenance).map(([field, prov]) => (
                                <div key={field} className="mb-1.5">
                                  <strong>{field}</strong> (p.{prov.page}, conf {prov.confidence}):{" "}
                                  <span className="text-white/55">&ldquo;{prov.snippet}&rdquo;</span>
                                </div>
                              ))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {docResult.unsupported.length > 0 && (
                <section className="card p-6">
                  <h3 className="text-sm font-semibold">Unsupported / OCR required</h3>
                  <div className="mt-3 space-y-2 text-sm">
                    {docResult.unsupported.map((item, idx) => (
                      <div key={idx} className="rounded-lg border border-red-400/20 p-3 text-red-200">
                        <strong>{item.filename}</strong>: {item.message}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}
