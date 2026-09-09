export default function About() {
  return (
    <article>
      <h1>Visiting a Courtroom</h1>
      <p className="disclaimer">
        Colorado courtrooms are open to the public by default -- you don't need permission or an
        appointment to sit in the gallery of most hearings. A few basics make a first visit smoother.
      </p>

      <div className="card">
        <h3>Before you go</h3>
        <ul>
          <li>Confirm the hearing is still on -- check the hearing's detail page or the official docket search the morning of. Hearings move or get cancelled often.</li>
          <li>Arrive 15-20 minutes early. You'll go through security, and courtrooms can be hard to find on your first visit.</li>
          <li>Bring government ID. You may need to show it to security or the courtroom deputy.</li>
        </ul>
      </div>

      <div className="card">
        <h3>Security and courtroom etiquette</h3>
        <ul>
          <li>Expect an airport-style security screening at the courthouse entrance (metal detector, bag check).</li>
          <li><strong>Phones are usually not allowed to be used inside courtrooms</strong> -- silence it before entering, and don't take photos, video, or audio recordings unless a judge has explicitly permitted it.</li>
          <li>Dress reasonably -- business casual is a safe default. Some judges will not admit visitors in shorts, tank tops, or hats.</li>
          <li>Enter and exit quietly, ideally between witnesses or during a recess rather than mid-testimony.</li>
          <li>Stand when the judge enters or leaves ("all rise"), and remain quiet and seated otherwise.</li>
          <li>Check in with the courtroom deputy/bailiff if unsure where to sit.</li>
        </ul>
      </div>

      <div className="card">
        <h3>Courthouse locations</h3>
        <dl className="fact-grid">
          <div>
            <dt>Boulder County Justice Center</dt>
            <dd>1777 6th St, Boulder, CO 80302</dd>
          </div>
          <div>
            <dt>Boulder County Combined Court -- Longmont</dt>
            <dd>1035 Kimbark St, Longmont, CO 80501</dd>
          </div>
        </dl>
      </div>

      <p>
        For the authoritative, court-maintained version of visitor policy (which can vary by judge or
        change without notice on this page), see the{" "}
        <a href="https://www.coloradojudicial.gov/" target="_blank" rel="noreferrer">
          Colorado Judicial Branch website
        </a>
        .
      </p>
    </article>
  );
}
