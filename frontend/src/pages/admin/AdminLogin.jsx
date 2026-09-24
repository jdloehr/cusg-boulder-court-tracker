import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, storeAdmin } from "../../api.js";

export default function AdminLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  // Set once the server confirms email+password are correct but a 2FA
  // code is also required (Phase-4 doc, Section 2.3) -- a 428 response,
  // not a failed login, so it doesn't count against account lockout.
  const [needsTotp, setNeedsTotp] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.adminLogin(email, password, needsTotp ? totpCode : undefined);
      storeAdmin({
        token: res.access_token, id: res.id, role: res.role, email,
        is_justice: res.is_justice, display_name: res.display_name, title: res.title,
      });
      // Curation-role accounts go to the review-queue dashboard; a
      // justice-only account (no curation role) just returns to the
      // hearings list, where attendance/recommendation controls now show
      // up inline on hearing detail pages.
      navigate(res.role ? "/admin" : "/hearings");
    } catch (err) {
      if (err.status === 428) {
        setNeedsTotp(true);
        setError(null);
      } else if (err.status === 423 || err.status === 429) {
        setError(err.message); // account-lockout / rate-limit messages are already user-safe
      } else if (needsTotp) {
        setError("That code didn't match. Check your authenticator app (or use a backup code) and try again.");
      } else {
        setError("Invalid credentials.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>CUSG Team Login</h1>
      <p className="disclaimer">
        For CUSG Court Justices and the curation team (Editors and Contributors) only.
        Browsing the tracker doesn't require an account.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="email">Email</label>
          <input id="email" type="email" required disabled={needsTotp} value={email}
                 onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input id="password" type="password" required disabled={needsTotp} value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </div>
        {needsTotp && (
          <div>
            <label htmlFor="totpCode">Authenticator code (or a backup code)</label>
            <input id="totpCode" required autoFocus value={totpCode}
                   onChange={(e) => setTotpCode(e.target.value)} />
          </div>
        )}
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Signing in…" : needsTotp ? "Verify" : "Sign in"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>
      <p style={{ marginTop: "1rem", fontSize: "0.85rem" }}>
        <Link to="/forgot-password">Forgot your password?</Link>
      </p>
      <p style={{ marginTop: "0.4rem", fontSize: "0.85rem" }}>
        New CUSG Justice, no account yet? <Link to="/request-invite">Request your signup link</Link>.
      </p>
    </article>
  );
}
