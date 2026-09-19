// Phase-4 doc, Section 2.6: a short, plain-language privacy notice --
// not framed as a hard legal requirement at this scale, but appropriate
// given the site represents an official student-government branch.
export default function Privacy() {
  return (
    <article>
      <h1>Privacy notice</h1>
      <p className="disclaimer">Plain-language, not a legal document -- what's collected, why, and how it's kept.</p>

      <div className="card">
        <h3>What's collected</h3>
        <ul>
          <li>
            <strong>Email addresses</strong> -- if you subscribe to a digest or an alert, or as part of
            a Justice account (invite/password-reset emails).
          </li>
          <li>
            <strong>Names</strong> -- if you submit case details, write an Archive reflection, or
            (for Justices) fill out a public profile. A display name for a public submission is
            whatever you type in; it doesn't have to be your real name.
          </li>
          <li>
            <strong>IP address</strong> -- logged internally (never shown publicly) on unmoderated
            public submissions (Archive entries, reported content) and rate-limited actions, purely
            to trace abuse after the fact. Not used for anything else, and not shared.
          </li>
          <li>
            <strong>A Justice's profile photo</strong>, if uploaded -- re-encoded and stripped of
            metadata (including any embedded location data) before storage.
          </li>
        </ul>
      </div>

      <div className="card">
        <h3>Why</h3>
        <p>
          Strictly to run the features you're using: sending the digest/alert you asked for, showing
          your submission under the name you gave it, and (for the internal-only data) tracing abuse
          of an unmoderated public form if it happens. Nothing here is sold, shared with advertisers,
          or used for anything beyond operating the site.
        </p>
      </div>

      <div className="card">
        <h3>How it's stored, and how to remove it</h3>
        <p>
          Data lives in this project's own database (not a third-party analytics or ad platform). An
          email subscription can be removed anytime via the unsubscribe link in any digest email. A
          Justice can edit or delete their own profile fields and photo at will. To request removal of
          anything else you've submitted (an Archive entry, a case-detail submission), contact the
          CUSG Judicial Branch through its{" "}
          <a href="https://www.colorado.edu/cusg/about-us/judicial-branch" target="_blank" rel="noreferrer">
            official page
          </a>
          .
        </p>
      </div>

      <div className="card">
        <h3>Email delivery</h3>
        <p>
          Transactional and digest email (when configured) is sent through a third-party provider
          (SendGrid) whose only role is delivering the message -- it doesn't see or use the content
          for anything else.
        </p>
      </div>
    </article>
  );
}
