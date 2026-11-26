import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AdminUserRecord,
  approveAdminUser,
  changeAdminUserRole,
  createAdminUser,
  deactivateAdminUser,
  getAdminUsers,
  getAuthUser,
  rejectAdminUser,
  UserRole,
} from "../api";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

const ASSIGNABLE_ROLES: UserRole[] = ["analyst", "approver", "auditor", "admin"];

export default function UsersPage() {
  const currentUser = getAuthUser();
  const isAdmin = currentUser?.role === "admin";
  const [users, setUsers] = useState<AdminUserRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [roleSelections, setRoleSelections] = useState<Record<string, UserRole>>({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Create user form
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("analyst");
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    if (!isAdmin) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    getAdminUsers(statusFilter)
      .then((data) => {
        setUsers(data);
        setRoleSelections((prev) => {
          const next = { ...prev };
          data.forEach((u) => {
            if (!next[u.id]) next[u.id] = u.role || "analyst";
          });
          return next;
        });
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false));
  }, [isAdmin, statusFilter]);

  useEffect(load, [load]);

  if (!isAdmin) {
    return (
      <>
        <header className="app-page-title mb-8">
          <h1 className="text-2xl font-semibold">Users</h1>
          <p className="mt-1 text-sm text-white/45">Administrator access required.</p>
        </header>
        <div className="card border-red-400/20 p-5 text-sm text-red-200">
          You do not have permission for this action.
        </div>
      </>
    );
  }

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setCreating(true);
    try {
      const created = await createAdminUser({
        username: newUsername.trim(),
        email: newEmail.trim() || undefined,
        password: newPassword,
        role: newRole,
      });
      setUsers((prev) => [created, ...prev]);
      setNotice(`Created user ${created.username} (${created.role}).`);
      setNewUsername("");
      setNewEmail("");
      setNewPassword("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setCreating(false);
    }
  };

  const runAction = async (userId: string, fn: () => Promise<AdminUserRecord>, msg: string) => {
    setSavingId(userId);
    setError("");
    setNotice("");
    try {
      const updated = await fn();
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
      setNotice(msg);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSavingId("");
    }
  };

  return (
    <>
      <header className="app-page-title mb-8">
        <h1 className="text-2xl font-semibold">Users</h1>
        <p className="mt-1 text-sm text-white/45">
          Review pending access requests, create accounts, and manage roles.
        </p>
      </header>

      {error && <div className="card mb-5 border-red-400/20 p-5 text-sm text-red-200">{error}</div>}
      {notice && <div className="auth-success mb-5">{notice}</div>}

      <section className="card mb-6 p-6">
        <h2 className="text-base font-semibold">Create user</h2>
        <form onSubmit={handleCreate} className="mt-4 grid gap-3 md:grid-cols-5">
          <input
            className="field"
            placeholder="Username"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            required
          />
          <input
            className="field"
            type="email"
            placeholder="Email (optional)"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <input
            className="field"
            type="password"
            minLength={12}
            placeholder="Password (12+ chars)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
          <select
            className="field"
            value={newRole}
            onChange={(e) => setNewRole(e.target.value as UserRole)}
          >
            {ASSIGNABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button className="button-primary" type="submit" disabled={creating}>
            {creating ? "Creating..." : "Create user"}
          </button>
        </form>
      </section>

      <div className="mb-4 flex flex-wrap gap-2">
        {["", "pending", "active", "rejected", "deactivated"].map((st) => (
          <button
            key={st || "all"}
            className={statusFilter === st ? "button-primary" : "button-secondary"}
            onClick={() => setStatusFilter(st)}
          >
            {st ? st : "All users"}
          </button>
        ))}
      </div>

      {loading && <div className="card p-8 text-sm text-white/50">Loading users...</div>}
      {!loading && !users.length && (
        <div className="card p-8 text-sm text-white/50">No users match this filter.</div>
      )}

      {!loading && !!users.length && (
        <div className="card overflow-auto">
          <table className="w-full min-w-[780px] text-left text-sm">
            <thead className="border-b border-white/10 text-xs uppercase text-white/40">
              <tr>
                <th className="p-4">User</th>
                <th>Status</th>
                <th>Role</th>
                <th>Source / Note</th>
                <th className="p-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const chosenRole = roleSelections[u.id] || u.role || "analyst";
                const busy = savingId === u.id;
                return (
                  <tr key={u.id} className="border-b border-white/5 last:border-0">
                    <td className="p-4">
                      <div className="font-medium">{u.username}</div>
                      {u.email && <div className="text-xs text-white/45">{u.email}</div>}
                    </td>
                    <td>
                      <span className="status-badge" data-status={u.status}>
                        {u.status}
                      </span>
                    </td>
                    <td>{u.role || "—"}</td>
                    <td className="max-w-xs text-xs text-white/55">
                      <div>via {u.created_via}</div>
                      {u.request_note && <div className="mt-0.5 text-white/75">{u.request_note}</div>}
                    </td>
                    <td className="p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <select
                          className="field py-1 text-xs"
                          value={chosenRole}
                          disabled={busy}
                          onChange={(e) =>
                            setRoleSelections({ ...roleSelections, [u.id]: e.target.value as UserRole })
                          }
                        >
                          {ASSIGNABLE_ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                        {u.status === "pending" && (
                          <>
                            <button
                              className="button-primary px-3 py-1 text-xs"
                              disabled={busy}
                              onClick={() =>
                                runAction(
                                  u.id,
                                  () => approveAdminUser(u.id, chosenRole),
                                  `Approved ${u.username} as ${chosenRole}.`,
                                )
                              }
                            >
                              Approve
                            </button>
                            <button
                              className="button-secondary px-3 py-1 text-xs"
                              disabled={busy}
                              onClick={() =>
                                runAction(
                                  u.id,
                                  () => rejectAdminUser(u.id),
                                  `Rejected ${u.username}.`,
                                )
                              }
                            >
                              Reject
                            </button>
                          </>
                        )}
                        {u.status === "active" && (
                          <>
                            <button
                              className="button-secondary px-3 py-1 text-xs"
                              disabled={busy || chosenRole === u.role}
                              onClick={() =>
                                runAction(
                                  u.id,
                                  () => changeAdminUserRole(u.id, chosenRole),
                                  `Updated ${u.username} role to ${chosenRole}.`,
                                )
                              }
                            >
                              Change role
                            </button>
                            <button
                              className="button-secondary px-3 py-1 text-xs"
                              disabled={busy}
                              onClick={() =>
                                runAction(
                                  u.id,
                                  () => deactivateAdminUser(u.id),
                                  `Deactivated ${u.username}.`,
                                )
                              }
                            >
                              Deactivate
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
