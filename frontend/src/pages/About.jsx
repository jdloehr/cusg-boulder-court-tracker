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
        {/* Oct 2026 review, Phase 4 item 8: a real map link per
            address (Google's own documented URL scheme -- no API key
            needed for a plain search link) instead of this app trying
            to describe a specific route or bus line, which it has no
            way to keep accurate over time. One generic line each on
            getting there/parking, deliberately not naming a specific
            route, garage, or price this app can't verify or keep
            current. */}
        <dl className="fact-grid">
          <div>
            <dt>Boulder County Justice Center</dt>
            <dd>
              1777 6th St, Boulder, CO 80302
              {" · "}
              <a
                href="https://www.google.com/maps/search/?api=1&query=1777+6th+St%2C+Boulder%2C+CO+80302"
                target="_blank"
                rel="noreferrer"
              >
                Map
              </a>
              <br />
              <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
                Reachable by RTD bus or bike from campus; a free visitor lot and nearby street parking
                are both available -- check posted signage for time limits.
              </span>
            </dd>
          </div>
          <div>
            <dt>Boulder County Combined Court -- Longmont</dt>
            <dd>
              1035 Kimbark St, Longmont, CO 80501
              {" · "}
              <a
                href="https://www.google.com/maps/search/?api=1&query=1035+Kimbark+St%2C+Longmont%2C+CO+80501"
                target="_blank"
                rel="noreferrer"
              >
                Map
              </a>
              <br />
              <span style={{ fontSize: "0.85rem", color: "var(--ink-soft)" }}>
                Further out, best reached by car or RTD bus; a public lot and metered street parking
                are both available nearby -- check posted signage for time limits.
              </span>
            </dd>
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
