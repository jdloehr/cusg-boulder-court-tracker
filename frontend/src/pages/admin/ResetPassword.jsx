import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api.js";

export default function ResetPassword() {
  const { token } = useParams();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <article>
        <h1>Password reset</h1>
        <p className="message-success">Your password's been changed -- sign in with it now.</p>
        <button className="btn" onClick={() => navigate("/admin/login")}>Go to sign in</button>
      </article>
    );
  }

  return (
    <article>
      <h1>Choose a new password</h1>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="password">New password (at least 10 characters, not just letters or just numbers)</label>
          <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div>
          <label htmlFor="confirm">Confirm new password</label>
          <input id="confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Set new password"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>
      <p style={{ marginTop: "1rem" }}>
        <Link to="/admin/login">&larr; Back to sign in</Link>
      </p>
    </article>
  );
}
