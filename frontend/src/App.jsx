import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import Home from "./pages/Home.jsx";
import HearingList from "./pages/HearingList.jsx";
import HearingDetail from "./pages/HearingDetail.jsx";
import Subscribe from "./pages/Subscribe.jsx";
import ConfirmSubscription from "./pages/ConfirmSubscription.jsx";
import Unsubscribe from "./pages/Unsubscribe.jsx";
import About from "./pages/About.jsx";
import Welcome from "./pages/Welcome.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import Archive from "./pages/Archive.jsx";
import Learn from "./pages/Learn.jsx";
import LearnTopicDetail from "./pages/LearnTopicDetail.jsx";
import Justices from "./pages/Justices.jsx";
import EditJusticeProfile from "./pages/EditJusticeProfile.jsx";
import TeamAvailability from "./pages/TeamAvailability.jsx";
import AdminLogin from "./pages/admin/AdminLogin.jsx";
import AdminDashboard from "./pages/admin/AdminDashboard.jsx";
import AcceptInvite from "./pages/admin/AcceptInvite.jsx";
import ForgotPassword from "./pages/admin/ForgotPassword.jsx";
import ResetPassword from "./pages/admin/ResetPassword.jsx";
import RequestInvite from "./pages/admin/RequestInvite.jsx";
import AboutProject from "./pages/AboutProject.jsx";
import Privacy from "./pages/Privacy.jsx";
import { clearAdmin, getStoredAdmin } from "./api.js";

// Phase-6.2 doc, Section 1: individual Justice profile pages are gone --
// every profile now lives inline on /justices. This keeps any old
// bookmarked/shared /justices/:id link working by sending it to that
// Justice's anchor on the shared page instead of a 404.
function JusticeIdRedirect() {
  const { id } = useParams();
  return <Navigate to={`/justices#justice-${id}`} replace />;
}

// Oct 2026 review, Phase 2 item 4: an unmatched route used to render a
// blank <main> with no explanation at all -- a dead end for a stale
// bookmark, a typo'd URL, or a broken external link, with no way back
// in without using the browser's own back button or the header nav.
function NotFound() {
  return (
    <article>
      <h1>Page not found</h1>
      <p>That page doesn't exist, or the link might be out of date.</p>
      <p>
        <Link to="/hearings">Go to the Calendar</Link>
        {" · "}
        <Link to="/about">Visiting a Courtroom</Link>
      </p>
    </article>
  );
}

// Phase-6.2 doc, Section 3: lives at the header's far right.
// Oct 2026 review, Phase 4 item 1: back to a plain small text link
// (not the bordered pill this became in the page-redesign doc) --
// de-emphasized relative to the 5 main links, which matter to every
// visitor; this one only matters to the 7 Justices.
function AccountNavLink() {
  const admin = getStoredAdmin();
  const navigate = useNavigate();

  if (!admin) return <NavLink to="/admin/login" className="nav-signin-link">Justice Sign In</NavLink>;

  const label = admin.displayName || admin.email;
  return (
    <span className="nav-account-link">
      {admin.isJustice && <NavLink to="/justices/team/availability">Team Availability</NavLink>}{" "}
      {admin.role ? <NavLink to="/admin">{label}</NavLink> : <span>{label}</span>}{" "}
      <button
        className="btn-footer-signout"
        onClick={() => {
          clearAdmin();
          navigate("/");
        }}
      >
        Sign out
      </button>
    </span>
  );
}

// Oct 2026 review, Phase 3 item 1: below ~720px, .site-nav stayed a
// single flex row with no way to collapse it -- "Meet the Justices"
// got cut off and "Justice Sign In" ended up off-screen (~115px past
// the edge of a 390px-wide phone), unreachable by tap or by tab. This
// button + the .site-nav[data-open] CSS below (see styles.css) turns
// it into a real disclosure widget: hidden above 720px (the row fits
// fine there), toggles a stacked panel below it.
function MobileMenuButton({ open, onToggle, buttonRef }) {
  return (
    <button
      type="button"
      className="nav-menu-toggle"
      aria-expanded={open}
      aria-controls="site-nav"
      aria-label={open ? "Close menu" : "Open menu"}
      ref={buttonRef}
      onClick={onToggle}
    >
      <span aria-hidden="true">{open ? "✕" : "☰"}</span>
    </button>
  );
}

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef(null);

  // Closes on Escape with focus returned to the toggle button --
  // standard behavior for a disclosure widget (WAI-ARIA Authoring
  // Practices), and exactly the kind of gap an axe/keyboard-only pass
  // flags: without this, a keyboard user who opens the menu has no way
  // to close it except tabbing all the way through every link in it.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(e) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <>
      <header className="site-header">
        <div className="inner">
          {/* Oct 2026 review, Phase 4 item 2: "CUSG Court" kept, with
              "Boulder Court Tracker" as a subtitle -- .wordmark small
              already had styling for exactly this, just never
              actually rendered. */}
          <NavLink to="/" className="wordmark">
            CUSG Court
            <small>Boulder Court Tracker</small>
          </NavLink>
          <MobileMenuButton open={menuOpen} onToggle={() => setMenuOpen((v) => !v)} buttonRef={menuButtonRef} />
          {/* Closes on navigation: any click on a link inside bubbles
              up here -- simpler and more direct than reacting to a
              route-change effect for the same thing.
              Oct 2026 review, Phase 4 item 1: reorganized to the 5
              things a first-time visitor actually needs quick access
              to; Archive, Meet the Justices, and Welcome moved to the
              footer (below) -- still one click away, just not
              competing for header space with the main 5.
              AccountNavLink lives outside this nav (below) so it
              stays reachable even while this is collapsed on mobile. */}
          <nav className="site-nav" id="site-nav" data-open={menuOpen} onClick={() => setMenuOpen(false)}>
            <NavLink to="/hearings">Calendar</NavLink>
            <NavLink to="/about">First visit?</NavLink>
            <NavLink to="/learn">Learn</NavLink>
            <NavLink to="/recommendations">Picks</NavLink>
            <NavLink to="/justices">Meet the Justices</NavLink>
            <NavLink to="/subscribe">Subscribe</NavLink>
          </nav>
          <AccountNavLink />
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/hearings" element={<HearingList />} />
          <Route path="/hearings/:id" element={<HearingDetail />} />
          <Route path="/welcome" element={<Welcome />} />
          <Route path="/recommendations" element={<Recommendations />} />
          <Route path="/archive" element={<Archive />} />
          <Route path="/learn" element={<Learn />} />
          <Route path="/learn/:id" element={<LearnTopicDetail />} />
          <Route path="/justices" element={<Justices />} />
          <Route path="/justices/me/edit" element={<EditJusticeProfile />} />
          <Route path="/justices/team/availability" element={<TeamAvailability />} />
          <Route path="/justices/:id" element={<JusticeIdRedirect />} />
          <Route path="/subscribe" element={<Subscribe />} />
          <Route path="/subscriptions/confirm/:token" element={<ConfirmSubscription />} />
          <Route path="/unsubscribe/:token" element={<Unsubscribe />} />
          <Route path="/about" element={<About />} />
          <Route path="/about-project" element={<AboutProject />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/accept-invite/:token" element={<AcceptInvite />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password/:token" element={<ResetPassword />} />
          <Route path="/request-invite" element={<RequestInvite />} />
          <Route path="/admin/*" element={<AdminDashboard />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="site-footer">
        <p>
          CUSG Boulder Court Tracker is a planning aid, not an authoritative record. Hearing dates,
          times, and courtrooms can change or be cancelled with little notice -- always confirm on the{" "}
          <a href="https://www.coloradojudicial.gov/dockets" target="_blank" rel="noreferrer">
            official Colorado Judicial Branch docket search
          </a>{" "}
          before attending.
        </p>
        {/* Oct 2026 review, Phase 4 item 1: Archive and Meet the
            Justices moved here from the main nav above (Welcome was
            already here) -- still one click away, just not competing
            for header space with the main 5 links. */}
        <p className="site-footer-links">
          <NavLink to="/welcome">Welcome</NavLink> &middot; <NavLink to="/archive">Archive</NavLink>{" "}
          &middot; <NavLink to="/justices">Meet the Justices</NavLink> &middot;{" "}
          <NavLink to="/subscribe">Subscribe</NavLink> &middot;{" "}
          <NavLink to="/about">Visiting a Courtroom</NavLink> &middot;{" "}
          <NavLink to="/about-project">About</NavLink> &middot; <NavLink to="/privacy">Privacy</NavLink>
        </p>
        <p className="site-footer-affiliation">
          A project of the{" "}
          <a href="https://www.colorado.edu/cusg/about-us/judicial-branch" target="_blank" rel="noreferrer">
            CUSG Judicial Branch
          </a>
          .
        </p>
      </footer>
    </>
  );
}
