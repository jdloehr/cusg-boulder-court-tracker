import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, storeAdmin } from "../../api.js";

export default function AdminLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.adminLogin(email, password);
      storeAdmin({
        token: res.access_token, role: res.role, email,
        is_justice: res.is_justice, display_name: res.display_name, title: res.title,
      });
      // Curation-role accounts go to the review-queue dashboard; a
      // justice-only account (no curation role) just returns to the
      // hearings list, where attendance/recommendation controls now show
      // up inline on hearing detail pages.
      navigate(res.role ? "/admin" : "/");
    } catch (err) {
      setError("Invalid credentials.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>CUSG Team Login</h1>
      <p className="disclaimer">
        For CUSG Supreme Court Justices and the curation team (Editors and Contributors) only.
        Browsing the tracker doesn't require an account.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>
    </article>
  );
}
