import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { requestAccess } from "../api";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

export default function RequestAccessPage() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (password.length < 12) {
      setError("Password must be at least 12 characters long.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await requestAccess({
        username: username.trim(),
        email: email.trim(),
        password,
        note: note.trim() || undefined,
      });
      setSuccess(res.message);
      setUsername("");
      setEmail("");
      setPassword("");
      setNote("");
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
        <h1>Request access</h1>
        <p className="auth-sub">
          Submit an access request. An administrator will review your request and assign a role.
        </p>
        {error && <div className="auth-alert">{error}</div>}
        {success && <div className="auth-success">{success}</div>}
        <form onSubmit={handleSubmit} className="auth-form">
          <label className="auth-label">
            <span>Username</span>
            <input
              className="field w-full"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="jane.doe"
              required
            />
          </label>
          <label className="auth-label">
            <span>Email</span>
            <input
              className="field w-full"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="jane@company.com"
              required
            />
          </label>
          <label className="auth-label">
            <span>Password (min 12 characters)</span>
            <input
              className="field w-full"
              type="password"
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 12 characters"
              required
            />
          </label>
          <label className="auth-label">
            <span>Note (optional)</span>
            <input
              className="field w-full"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Team or reason for access"
            />
          </label>
          <button className="button-primary w-full" type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit request"}
          </button>
        </form>
        <div className="auth-footer-links">
          <Link to="/login">← Back to sign in</Link>
          <Link to="/">Landing</Link>
        </div>
      </div>
    </div>
  );
}
