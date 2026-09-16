import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.forgotPassword(email);
      setMessage(res.message);
    } catch {
      // Same generic message either way -- see routers/account.py's
      // forgot_password, which never reveals whether the email matched.
      setMessage("If that email has an account, a reset link has been sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>Reset your password</h1>
      <p className="disclaimer">For CUSG Justices and curation-team accounts.</p>
      {message ? (
        <p className="message-success">{message}</p>
      ) : (
        <form className="form-grid" onSubmit={onSubmit}>
          <div>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
      <p style={{ marginTop: "1rem" }}>
        <Link to="/admin/login">&larr; Back to sign in</Link>
      </p>
    </article>
  );
}
