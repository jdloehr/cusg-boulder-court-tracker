import { Link } from "react-router-dom";

export default function Welcome() {
  return (
    <article>
      <h1>Welcome to the CUSG Boulder Court Tracker</h1>
      <p className="disclaimer">
        A quick tour -- this page is always here (bottom of the "Hearings" page, or just bookmark it)
        if you want to come back to it.
      </p>

      <div className="card">
        <h3>What this is</h3>
        <p>
          A planning tool for finding real, upcoming, in-person Boulder-area court proceedings worth
          sitting in on -- built for the CUSG Supreme Court, and open to any pre-law student. Every
          hearing listed comes from the actual Colorado court docket (or, for federal and Colorado
          appellate cases, a real, currently-scheduled case), pulled and checked automatically most
          days.
        </p>
      </div>

      <div className="card">
        <h3>Finding a hearing</h3>
        <p>
          The <Link to="/">Hearings</Link> page defaults to <strong>jury trials and oral arguments /
          motions hearings</strong> -- the two hearing types most worth watching as an observer,
          since they involve actual argument or testimony rather than a two-minute scheduling
          check-in. Use "Show all types" in the Hearing type filter to see everything on the docket,
          including more procedural hearings.
        </p>
        <ul>
          <li><strong>Planning window</strong> -- defaults to the next 2 weeks; widen it to a month or the whole semester.</li>
          <li><strong>Case category</strong> -- criminal, civil, family, probate, etc.</li>
          <li><strong>Court</strong> -- Boulder County, Longmont, or the federal/state-appellate cases (see below).</li>
          <li><strong>"In the news only"</strong> -- shows just the hearings tied to real local news coverage.</li>
        </ul>
        <p>
          Each hearing shows its date, time, estimated duration, a plain-language explanation of what
          that hearing type actually involves, and (when the team has added one) a short note on why
          it's worth watching. Click into a hearing for the full detail, courthouse address and
          visitor info, an "Add to calendar" button, and a link to double-check it on the official
          docket -- <strong>hearings move or get cancelled</strong>, so always confirm before you go,
          especially for anything more than a few days out.
        </p>
      </div>

      <div className="card">
        <h3>Reading the tags</h3>
        <p>
          Most hearings are Boulder County Court and don't carry a court tag. A visible tag (e.g.
          "Longmont", "CO Supreme Ct.", "U.S. Supreme Ct.") means the hearing is somewhere else --
          Colorado's own Supreme Court and Court of Appeals sit in Denver, not Boulder. A separate{" "}
          <span className="badge badge-news" style={{ verticalAlign: "middle" }}>In the news</span>{" "}
          tag means the case has real local news coverage attached -- check the hearing's detail page
          for the article.
        </p>
      </div>

      <div className="card">
        <h3>For CUSG Justices</h3>
        <p>
          Every hearing has a <strong>Court attendance</strong> section where any of the 7 Justices'
          status (attending / maybe / not attending, with an optional note) can be set directly --
          no login needed, just pick your own name's row. Justices can also{" "}
          <strong>recommend</strong> a hearing to the rest of the court with a note on why, which
          lands on the public <Link to="/recommendations">Court Recommendations</Link> board.
        </p>
      </div>

      <div className="card">
        <h3>Staying in the loop</h3>
        <p>
          <Link to="/subscribe">Subscribe</Link> with just an email address (no account) for a weekly
          digest by hearing type, real-time alerts on one specific case number, or an alert the
          moment the court adds a new recommendation. Digests are shortened during CU Boulder breaks
          and finals week, since court doesn't pause for the academic calendar but most students
          aren't watching then.
        </p>
      </div>

      <div className="card">
        <h3>First time in a courtroom?</h3>
        <p>
          See <Link to="/about">Visiting a Courtroom</Link> for what to expect -- ID, security
          screening, dress, phone policy, and the two courthouse addresses.
        </p>
      </div>

      <p className="disclaimer" style={{ marginTop: "2rem" }}>
        This is a planning aid, not an authoritative record. Always confirm a hearing's date, time,
        and courtroom on the official docket before attending.
      </p>
    </article>
  );
}
