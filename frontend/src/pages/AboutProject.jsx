import { Link } from "react-router-dom";

// Phase-4 doc, Section 3: affiliation + project-purpose page. Distinct
// from /about ("Visiting a Courtroom," a visitor-logistics page) and
// /welcome (a feature tour) -- this one is specifically about what the
// project is and its connection to CUSG.
export default function AboutProject() {
  return (
    <article>
      <h1>About this project</h1>
      <p className="disclaimer">A project of the CUSG Judicial Branch.</p>

      <div className="card">
        <h3>What this is</h3>
        <p>
          The CUSG Boulder Court Tracker is a planning tool for finding real, upcoming, in-person
          Boulder-area court proceedings worth sitting in on -- built for the CUSG Court, and
          open to any pre-law student, or anyone else interested in the field of law. Every hearing
          listed comes from the actual Colorado court docket, or, for federal and Colorado appellate
          cases, a real, currently-scheduled case.
        </p>
      </div>

      <div className="card">
        <h3>Connection to CUSG</h3>
        <p>
          This tool was built by and for the CUSG Judicial Branch -- the seven-justice Appellate
          Court that interprets and enforces the CUSG Constitution -- to make it easier for the
          Court, and anyone else on campus curious about the law, to find and attend real hearings
          worth watching. It's an independent, free-standing project rather than an official
          University of Colorado Boulder site, and doesn't use CU Boulder's official branding.
        </p>
        <p>
          For the Judicial Branch's official business -- filing a petition, Bar Advocate services,
          case precedent, office hours -- see the{" "}
          <a href="https://www.colorado.edu/cusg/about-us/judicial-branch" target="_blank" rel="noreferrer">
            official CUSG Judicial Branch page
          </a>{" "}
          or the{" "}
          <a href="https://www.colorado.edu/cusg" target="_blank" rel="noreferrer">
            main CUSG site
          </a>
          .
        </p>
      </div>

      <div className="card">
        <h3>Questions or feedback</h3>
        <p>
          For anything about this tool itself -- a bug, a suggestion, or a question about a specific
          feature -- reach out through the{" "}
          <a href="https://www.colorado.edu/cusg/about-us/judicial-branch" target="_blank" rel="noreferrer">
            CUSG Judicial Branch's official contact info
          </a>
          .
        </p>
      </div>

      <p style={{ marginTop: "1.5rem" }}>
        See also: <Link to="/welcome">how to use this site</Link>,{" "}
        <Link to="/privacy">the privacy notice</Link>.
      </p>
    </article>
  );
}
