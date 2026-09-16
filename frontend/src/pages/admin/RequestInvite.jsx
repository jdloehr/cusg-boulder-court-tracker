import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api.js";

// Self-service provisioning, added on request: a known CUSG Justice can
// get their own signup link without needing an existing Editor/Justice
// to invite them first. Still gated -- an Editor has to have already
// added this email to the allow-list (Justice Accounts tab in the
// dashboard) for anything to actually get sent -- but this page doesn't
// reveal which emails qualify, same reasoning as forgot-password.
export default function RequestInvite() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.requestInvite(email);
      setMessage(res.message);
    } catch {
      setMessage("If that email is on the CUSG Justice list, a signup link has been sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>Request your CUSG Justice account</h1>
      <p className="disclaimer">
        For the 7-8 current CUSG Supreme Court Justices. Enter the email an Editor already has on
        file for you, and a one-time signup link will be sent there.
      </p>
      {message ? (
        <p className="message-success">{message}</p>
      ) : (
        <form className="form-grid" onSubmit={onSubmit}>
          <div>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            {busy ? "Sending…" : "Send my signup link"}
          </button>
        </form>
      )}
      <p style={{ marginTop: "1rem" }}>
        Not on the list yet, or already have an account? <Link to="/admin/login">Sign in</Link> or ask
        an existing Justice/Editor to add you.
      </p>
    </article>
  );
}
