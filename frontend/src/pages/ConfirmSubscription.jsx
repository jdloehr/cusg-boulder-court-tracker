import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";

const FREQUENCY_LABELS = {
  weekly_digest: "a weekly digest",
  realtime_for_followed_case: "real-time alerts",
};

// Oct 2026 review item 2: double opt-in for /subscribe. GET here first
// (api.getSubscriptionConfirmation) to show what's being confirmed --
// same "peek before you commit" pattern as /accept-invite/:token -- then
// POST (api.confirmSubscription) to actually flip it on. A 404 here just
// as plausibly means "already confirmed" as "invalid link" (the token is
// cleared once used -- see app/models.py's Subscription docstring), so
// the error message doesn't guess which.
export default function ConfirmSubscription() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSubscriptionConfirmation(token).then(setInfo).catch((e) => setLoadError(e.message));
  }, [token]);

  async function onConfirm() {
    setBusy(true);
    try {
      await api.confirmSubscription(token);
      setStatus({ ok: true });
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <article>
      <h1>Confirm your subscription</h1>

      {!info && !loadError && <p>Loading&hellip;</p>}

      {loadError && !status && (
        <p className="message-error">
          Couldn't load this confirmation link: {loadError}. It may already have been confirmed, or
          the link may be invalid.
        </p>
      )}

      {info && !status && (
        <>
          <p>
            Confirm <strong>{info.email}</strong> for {FREQUENCY_LABELS[info.frequency] || info.frequency}?
            No mail goes out until you do.
          </p>
          <button className="btn" type="button" onClick={onConfirm} disabled={busy}>
            {busy ? "Confirming…" : "Confirm subscription"}
          </button>
        </>
      )}

      {status?.ok && (
        <p className="message-success">
          Confirmed -- you're all set. Every email includes an unsubscribe link if you change your
          mind later.
        </p>
      )}
      {status && !status.ok && <p className="message-error">Couldn't confirm: {status.message}</p>}

      <p style={{ marginTop: "1rem" }}>
        <Link to="/">&larr; Back to the homepage</Link>
      </p>
    </article>
  );
}
