import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, getStoredAdmin } from "../api.js";
import AvailabilityGrid from "../components/AvailabilityGrid.jsx";

// Phase-3 doc, Section 3: a Justice edits only their own profile --
// identity comes from the login (require_justice on the backend), never
// a ?justice_id= this page could be tricked into passing for someone
// else.
export default function EditJusticeProfile() {
  const admin = getStoredAdmin();
  const [justice, setJustice] = useState(null);
  const [bio, setBio] = useState("");
  const [yearOrMajor, setYearOrMajor] = useState("");
  const [whyCare, setWhyCare] = useState("");
  const [funFact, setFunFact] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoError, setPhotoError] = useState(null);
  const [availabilityCells, setAvailabilityCells] = useState([]);
  const [availabilityStatus, setAvailabilityStatus] = useState(null);
  const [availabilityBusy, setAvailabilityBusy] = useState(false);

  useEffect(() => {
    if (!admin?.id) return;
    api.getJustice(admin.id).then((j) => {
      setJustice(j);
      setBio(j.bio || "");
      setYearOrMajor(j.year_or_major || "");
      setWhyCare(j.why_care || "");
      setFunFact(j.fun_fact || "");
    });
    api.getMyAvailability().then((a) => setAvailabilityCells(a.cells || []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin?.id]);

  async function onSaveAvailability() {
    setAvailabilityBusy(true);
    setAvailabilityStatus(null);
    try {
      const updated = await api.updateMyAvailability(availabilityCells);
      setAvailabilityCells(updated.cells || []);
      setAvailabilityStatus({ ok: true, message: "Availability saved." });
    } catch (err) {
      setAvailabilityStatus({ ok: false, message: err.message });
    } finally {
      setAvailabilityBusy(false);
    }
  }

  if (!admin?.isJustice) return <Navigate to="/admin/login" replace />;
  if (!justice) return <p>Loading&hellip;</p>;

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      const updated = await api.updateMyProfile({
        bio: bio || null, year_or_major: yearOrMajor || null, why_care: whyCare || null, fun_fact: funFact || null,
      });
      setJustice(updated);
      setStatus({ ok: true, message: "Profile saved." });
    } catch (err) {
      setStatus({ ok: false, message: err.message });
    } finally {
      setBusy(false);
    }
  }

  async function onPhotoChange(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoBusy(true);
    setPhotoError(null);
    try {
      const updated = await api.uploadMyPhoto(file);
      setJustice(updated);
    } catch (err) {
      setPhotoError(err.message);
    } finally {
      setPhotoBusy(false);
      e.target.value = "";
    }
  }

  return (
    <article>
      <p>
        <Link to={`/justices#justice-${justice.id}`}>&larr; Back to my profile</Link>
      </p>
      <h1>Edit my profile</h1>
      <p className="disclaimer">
        This is public -- visible on "Meet the Justices" and linked from your name wherever it
        appears on the site (recommendations, attendance, the Archive).
      </p>

      <div className="card">
        <h3>Photo</h3>
        {justice.photo_url ? (
          <img className="justice-photo" src={api.justicePhotoUrl(justice.id)} alt="" style={{ marginBottom: "0.75rem" }} />
        ) : (
          <div className="justice-photo-placeholder" aria-hidden="true" style={{ marginBottom: "0.75rem" }}>
            {(justice.display_name || "?")[0]}
          </div>
        )}
        <input type="file" accept="image/jpeg,image/png,image/webp" onChange={onPhotoChange} disabled={photoBusy} />
        <p style={{ fontSize: "0.78rem", color: "var(--ink-soft)" }}>JPEG, PNG, or WEBP, up to 5MB.</p>
        {photoBusy && <p>Uploading&hellip;</p>}
        {photoError && <p className="message-error">{photoError}</p>}
      </div>

      <form className="form-grid" onSubmit={onSubmit}>
        <div>
          <label htmlFor="yearOrMajor">Year in school / major</label>
          <input id="yearOrMajor" value={yearOrMajor} onChange={(e) => setYearOrMajor(e.target.value)}
                 placeholder="Junior, Political Science" />
        </div>
        <div>
          <label htmlFor="bio">Short bio</label>
          <textarea id="bio" value={bio} onChange={(e) => setBio(e.target.value)} maxLength={2000} />
        </div>
        <div>
          <label htmlFor="whyCare">Why I care about court-watching</label>
          <textarea id="whyCare" value={whyCare} onChange={(e) => setWhyCare(e.target.value)} maxLength={2000} />
        </div>
        <div>
          <label htmlFor="funFact">Fun fact / interests</label>
          <input id="funFact" value={funFact} onChange={(e) => setFunFact(e.target.value)} maxLength={300} />
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save profile"}
        </button>
        {status && <p className={status.ok ? "message-success" : "message-error"}>{status.message}</p>}
      </form>

      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>My weekly availability</h3>
        <p className="disclaimer" style={{ margin: "0 0 1rem" }}>
          Justices only -- never shown publicly. Click and drag to paint your free time; used to
          compute the availability meter and{" "}
          <Link to="/justices/team/availability">Team Availability</Link> heatmap so the court can see
          when hearings work for everyone.
        </p>
        <AvailabilityGrid cells={availabilityCells} onChange={setAvailabilityCells} />
        <button className="btn" type="button" onClick={onSaveAvailability} disabled={availabilityBusy} style={{ marginTop: "1rem" }}>
          {availabilityBusy ? "Saving…" : "Save availability"}
        </button>
        {availabilityStatus && (
          <p className={availabilityStatus.ok ? "message-success" : "message-error"}>{availabilityStatus.message}</p>
        )}
      </div>
    </article>
  );
}
