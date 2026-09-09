import { useEffect } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import HearingList from "./pages/HearingList.jsx";
import HearingDetail from "./pages/HearingDetail.jsx";
import Subscribe from "./pages/Subscribe.jsx";
import About from "./pages/About.jsx";
import Welcome from "./pages/Welcome.jsx";
import Recommendations from "./pages/Recommendations.jsx";
import AdminLogin from "./pages/admin/AdminLogin.jsx";
import AdminDashboard from "./pages/admin/AdminDashboard.jsx";
import { clearAdmin, getStoredAdmin } from "./api.js";

const FIRST_VISIT_KEY = "cusg_visited";

// Sends a first-time visitor to /welcome once, automatically -- but only
// when they land on the plain homepage. A shared link straight to a
// specific hearing or the recommendations board is left alone rather than
// hijacked to the tour.
function FirstVisitRedirect() {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (location.pathname !== "/") return;
    try {
      if (!localStorage.getItem(FIRST_VISIT_KEY)) {
        localStorage.setItem(FIRST_VISIT_KEY, "true");
        navigate("/welcome", { replace: true });
      }
    } catch {
      /* localStorage unavailable (e.g. private browsing) -- just skip the tour */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}

function AccountNav() {
  const admin = getStoredAdmin();
  const navigate = useNavigate();

  if (!admin) return <NavLink to="/admin/login">Team Login</NavLink>;

  const label = admin.displayName || admin.email;
  return (
    <span>
      {admin.role ? <NavLink to="/admin">{label}</NavLink> : <span>{label}</span>}{" "}
      <button
        className="btn-nav-signout"
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
      <FirstVisitRedirect />
      <header className="site-header">
        <div className="inner">
          <NavLink to="/" className="wordmark">
            CUSG Boulder Court Tracker
            <small>Court-watching for the CUSG Supreme Court &amp; pre-law students</small>
          </NavLink>
          <nav className="site-nav">
            <NavLink to="/welcome">Welcome</NavLink>
            <NavLink to="/" end>
              Hearings
            </NavLink>
            <NavLink to="/recommendations">Court Recommendations</NavLink>
            <NavLink to="/subscribe">Subscribe</NavLink>
            <NavLink to="/about">Visiting a Courtroom</NavLink>
            <AccountNav />
          </nav>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<HearingList />} />
          <Route path="/welcome" element={<Welcome />} />
          <Route path="/hearings/:id" element={<HearingDetail />} />
          <Route path="/recommendations" element={<Recommendations />} />
          <Route path="/subscribe" element={<Subscribe />} />
          <Route path="/about" element={<About />} />
          <Route path="/admin/login" element={<AdminLogin />} />
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
      </footer>
    </>
  );
}
