import { useState } from "react";
import { api } from "../api.js";

// Phase-4 doc, Section 2.5: a lightweight "Report" flag on every public
// Archive entry and recommendation, since both publish with no
// pre-review. Doesn't remove anything itself -- just notifies every
// Justice and lands in the dashboard's Reports queue.
export default function ReportLink({ targetType, targetId }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createReport({ target_type: targetType, target_id: targetId, reason: reason || undefined });
      setStatus({ ok: true, message: "Thanks -- every Justice has been notified." });
      setReason("");
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  if (status?.ok) {
    return <p style={{ fontSize: "0.78rem", color: "var(--ink-soft)" }}>{status.message}</p>;
  }

  if (!open) {
    return (
      <button
        type="button"
        className="report-link"
        onClick={() => setOpen(true)}
        aria-label="Report this content"
      >
        Report
      </button>
    );
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: "0.4rem", alignItems: "flex-start", flexWrap: "wrap", marginTop: "0.3rem" }}>
      <input
        placeholder="What's wrong with this? (optional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        style={{ fontSize: "0.8rem", flex: 1, minWidth: "10rem" }}
      />
      <button type="submit" className="btn btn-danger" style={{ fontSize: "0.78rem", padding: "0.2rem 0.6rem" }} disabled={busy}>
        {busy ? "Sending…" : "Submit report"}
      </button>
      <button type="button" className="btn btn-secondary" style={{ fontSize: "0.78rem", padding: "0.2rem 0.6rem" }} onClick={() => setOpen(false)}>
        Cancel
      </button>
      {status && !status.ok && <p className="message-error" style={{ width: "100%" }}>{status.message}</p>}
    </form>
  );
}
