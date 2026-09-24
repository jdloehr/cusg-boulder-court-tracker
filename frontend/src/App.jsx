import { NavLink, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import Home from "./pages/Home.jsx";
import HearingList from "./pages/HearingList.jsx";
import HearingDetail from "./pages/HearingDetail.jsx";
import Subscribe from "./pages/Subscribe.jsx";
import About from "./pages/About.jsx";
import Welcome from "./pages/Welcome.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import Archive from "./pages/Archive.jsx";
import Justices from "./pages/Justices.jsx";
import EditJusticeProfile from "./pages/EditJusticeProfile.jsx";
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

// Phase-6.2 doc, Section 3: moved out of the footer into the header's far
// right, per the approved design's "small, low-emphasis 'Justice Sign
// In' link" -- still unobtrusive (Phase-3 doc, Section 2's original
// reasoning), just relocated now that the header nav itself is shorter.
function AccountNavLink() {
  const admin = getStoredAdmin();
  const navigate = useNavigate();

  if (!admin) return <NavLink to="/admin/login" className="nav-account-link">Justice Sign In</NavLink>;

  const label = admin.displayName || admin.email;
  return (
    <span className="nav-account-link">
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

export default function App() {
  return (
    <>
      <header className="site-header">
        <div className="inner">
          <NavLink to="/" className="wordmark">
            CUSG Court
          </NavLink>
          <nav className="site-nav">
            <NavLink to="/hearings">Calendar</NavLink>
            <NavLink to="/recommendations">Recommendations</NavLink>
            <NavLink to="/archive">Archive</NavLink>
            <NavLink to="/justices">Meet the Justices</NavLink>
            <AccountNavLink />
          </nav>
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
          <Route path="/justices" element={<Justices />} />
          <Route path="/justices/me/edit" element={<EditJusticeProfile />} />
          <Route path="/justices/:id" element={<JusticeIdRedirect />} />
          <Route path="/subscribe" element={<Subscribe />} />
          <Route path="/about" element={<About />} />
          <Route path="/about-project" element={<AboutProject />} />
          <Route path="/privacy" element={<Privacy />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/accept-invite/:token" element={<AcceptInvite />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password/:token" element={<ResetPassword />} />
          <Route path="/request-invite" element={<RequestInvite />} />
          <Route path="/admin/*" element={<AdminDashboard />} />
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
        <p className="site-footer-links">
          <NavLink to="/welcome">Welcome</NavLink> &middot; <NavLink to="/subscribe">Subscribe</NavLink>{" "}
          &middot; <NavLink to="/about">Visiting a Courtroom</NavLink> &middot;{" "}
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
