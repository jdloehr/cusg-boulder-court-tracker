import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api.js";

// Oct 2026 review: app/jobs/digest.py's emailed "Unsubscribe: <link>"
// line always pointed here, but this route never existed -- clicking it
// landed on a 404 (or, before FRONTEND_URL was used to build the link,
// on a bare relative path that didn't even resolve to this site at
// all). DELETE /api/subscriptions/{token} (api.unsubscribe) already
// existed and already worked; this page is just the missing landing
// spot for it. No confirmation step -- the token in the URL already is
// the one-time credential, same trust model as /reset-password/:token.
export default function Unsubscribe() {
  const { token } = useParams();
  const [status, setStatus] = useState(null); // null while in flight

  useEffect(() => {
    let ignore = false;
    api
      .unsubscribe(token)
      .then(() => {
        if (!ignore) setStatus({ ok: true });
      })
      .catch((err) => {
        if (!ignore) setStatus({ ok: false, message: err.message });
      });
    return () => {
      ignore = true;
    };
  }, [token]);

  return (
    <article>
      <h1>Unsubscribe</h1>
      {status === null && <p>Unsubscribing&hellip;</p>}
      {status?.ok && (
        <p className="message-success">
          You're unsubscribed -- no more emails from this subscription. (If you have more than one, each
          needs its own link.)
        </p>
      )}
      {status && !status.ok && (
        <p className="message-error">
          Couldn't unsubscribe: {status.message}. If this keeps happening, reach out through the{" "}
          <a href="https://www.colorado.edu/cusg/about-us/judicial-branch" target="_blank" rel="noreferrer">
            CUSG Judicial Branch's official contact info
          </a>
          .
        </p>
      )}
      <p style={{ marginTop: "1rem" }}>
        <Link to="/">&larr; Back to the homepage</Link>
      </p>
    </article>
  );
}
