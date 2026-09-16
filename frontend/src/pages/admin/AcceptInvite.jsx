import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, storeAdmin } from "../../api.js";

// Phase-3 doc, Section 1: what a one-time invite link opens onto. Shows
// who's being invited (from the invite itself, not user input) and asks
// only for a password -- name/title/email were already set by the
// Editor who created the invite.
export default function AcceptInvite() {
  const { token } = useParams();
  const [invite, setInvite] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api.getInvite(token).then(setInvite).catch((e) => setLoadError(e.message));
  }, [token]);

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.acceptInvite(token, password);
      storeAdmin({
        token: res.access_token, id: res.id, role: res.role, email: invite.email,
        is_justice: res.is_justice, display_name: res.display_name, title: res.title,
      });
      navigate("/justices/me/edit");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <article>
        <h1>Invite link not valid</h1>
        <p className="message-error">{loadError}</p>
        <p>Ask whoever invited you to send a new one.</p>
      </article>
    );
  }
  if (!invite) return <p>Loading&hellip;</p>;

  return (
    <article>
      <h1>Set up your CUSG Justice account</h1>
      <p className="disclaimer">
        You've been invited as <strong>{invite.title ? `${invite.title} ${invite.display_name}` : invite.display_name}</strong>{" "}
        ({invite.email}). Choose a password to finish setting up your account.
      </p>
      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="password">Password (at least 10 characters, not just letters or just numbers)</label>
          <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div>
          <label htmlFor="confirm">Confirm password</label>
          <input id="confirm" type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Setting up…" : "Set password & sign in"}
        </button>
        {error && <p className="message-error">{error}</p>}
      </form>
    </article>
  );
}
