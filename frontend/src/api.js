const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    const err = new Error(detail || `Request failed (${res.status})`);
    // Attached, not a change to the error contract every existing
    // `catch (err) { ... err.message ... }` caller relies on -- lets a
    // caller that needs to distinguish status codes do so (e.g. 428
    // "2FA code required" during login, Phase-4 doc Section 2.3) without
    // parsing the message string.
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function authHeaders() {
  const token = localStorage.getItem("cusg_admin_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export const api = {
  listHearings: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    ).toString();
    return request(`/api/hearings${qs ? `?${qs}` : ""}`);
  },
  getHearing: (id) => request(`/api/hearings/${id}`),
  submitDetails: (hearingId, payload) =>
    request(`/api/hearings/${hearingId}/submissions`, { method: "POST", body: JSON.stringify(payload) }),
  icsUrl: (id) => `${API_BASE}/api/hearings/${id}/ics`,
  academicCalendarCurrent: () => request("/api/academic-calendar/current"),
  dataStatus: () => request("/api/data-status"),
  triggerRefresh: () => request("/api/refresh", { method: "POST" }),
  createSubscription: (payload) =>
    request("/api/subscriptions", { method: "POST", body: JSON.stringify(payload) }),
  unsubscribe: (token) => request(`/api/subscriptions/${token}`, { method: "DELETE" }),

  // --- admin ---
  adminLogin: (email, password, totpCode) =>
    request("/api/admin/login", {
      method: "POST", body: JSON.stringify({ email, password, totp_code: totpCode || undefined }),
    }),
  reviewQueueHearings: () => request("/api/admin/review-queue/hearings", { headers: authHeaders() }),
  reviewQueueNewsMentions: () => request("/api/admin/review-queue/news-mentions", { headers: authHeaders() }),
  reviewQueueNewsMentionsCount: () =>
    request("/api/admin/review-queue/news-mentions/count", { headers: authHeaders() }),
  reviewQueueCommunitySubmissions: () =>
    request("/api/admin/review-queue/community-submissions", { headers: authHeaders() }),
  approveCommunitySubmission: (id) =>
    request(`/api/admin/community-submissions/${id}/approve`, { method: "POST", headers: authHeaders() }),
  rejectCommunitySubmission: (id) =>
    request(`/api/admin/community-submissions/${id}/reject`, { method: "POST", headers: authHeaders() }),
  // Phase-6 doc, Section 4: link by case number OR hearing_id -- pass
  // exactly one of the two fields in `payload` ({case_number} or {hearing_id}).
  linkNewsMention: (mentionId, payload) =>
    request(`/api/admin/news-mentions/${mentionId}/link`, {
      method: "POST", headers: authHeaders(), body: JSON.stringify(payload),
    }),
  confirmSuggestedNewsMention: (mentionId) =>
    request(`/api/admin/news-mentions/${mentionId}/confirm`, { method: "POST", headers: authHeaders() }),
  rejectSuggestedNewsMention: (mentionId) =>
    request(`/api/admin/news-mentions/${mentionId}/reject`, { method: "POST", headers: authHeaders() }),
  discardNewsMention: (mentionId) =>
    request(`/api/admin/news-mentions/${mentionId}`, { method: "DELETE", headers: authHeaders() }),
  backfillRematchNewsMentions: () =>
    request("/api/admin/news-mentions/backfill-rematch", { method: "POST", headers: authHeaders() }),
  draftBlurb: (hearingId, text) =>
    request(`/api/admin/hearings/${hearingId}/draft-blurb`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({ curated_blurb_draft: text }),
    }),
  publishBlurb: (hearingId) =>
    request(`/api/admin/hearings/${hearingId}/publish-blurb`, { method: "POST", headers: authHeaders() }),
  setExclusion: (hearingId, isExcluded, reason) =>
    request(`/api/admin/hearings/${hearingId}/exclusion`, {
      method: "PATCH",
      headers: authHeaders(),
      body: JSON.stringify({ is_excluded: isExcluded, exclusion_reason: reason || null }),
    }),
  appellateCourtPresets: () => request("/api/admin/appellate-candidates/courts", { headers: authHeaders() }),
  searchAppellateCandidates: (query, court, resultType = "o") =>
    request(`/api/admin/appellate-candidates/search?query=${encodeURIComponent(query)}` +
      `&court=${encodeURIComponent(court || "")}&result_type=${resultType}`, { headers: authHeaders() }),
  flagAppellateCandidate: (candidate) =>
    request("/api/admin/appellate-candidates/flag", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(candidate),
    }),
  listFlaggedAppellateCandidates: () =>
    request("/api/admin/appellate-candidates/flagged", { headers: authHeaders() }),
  publishAppellateCandidate: (payload) =>
    request("/api/admin/appellate-candidates/publish", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    }),
  listAcademicCalendar: () => request("/api/admin/academic-calendar", { headers: authHeaders() }),
  createAcademicCalendarPeriod: (payload) =>
    request("/api/admin/academic-calendar", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    }),
  activityLog: () => request("/api/admin/activity-log", { headers: authHeaders() }),

  // --- CUSG Justice features: setting/recommending requires a Justice login; reading is public ---
  listJustices: () => request("/api/justices"),
  setAttendance: (hearingId, payload) =>
    request(`/api/hearings/${hearingId}/attendance`, {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify(payload),
    }),
  listRecommendations: (hearingId) =>
    request(`/api/recommendations${hearingId ? `?hearing_id=${encodeURIComponent(hearingId)}` : ""}`),
  createRecommendation: (payload) =>
    request("/api/recommendations", { method: "POST", headers: authHeaders(), body: JSON.stringify(payload) }),
  deleteRecommendation: (id) =>
    request(`/api/recommendations/${id}`, { method: "DELETE", headers: authHeaders() }),

  // --- Archive & Reflections: reading and "Submit a Summary" are public; ---
  // --- editing/removing needs a Justice login (see backend/app/routers/archive.py) ---
  listArchive: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    ).toString();
    return request(`/api/archive${qs ? `?${qs}` : ""}`);
  },
  getArchiveEntry: (id) => request(`/api/archive/${id}`),
  createArchiveEntry: (payload) =>
    request("/api/archive", { method: "POST", headers: authHeaders(), body: JSON.stringify(payload) }),
  updateArchiveEntry: (id, payload) =>
    request(`/api/archive/${id}`, { method: "PATCH", headers: authHeaders(), body: JSON.stringify(payload) }),
  deleteArchiveEntry: (id) => request(`/api/archive/${id}`, { method: "DELETE", headers: authHeaders() }),

  // --- Phase-3: invite-link provisioning, password reset, public profiles ---
  createInvite: (payload) =>
    request("/api/admin/invites", { method: "POST", headers: authHeaders(), body: JSON.stringify(payload) }),
  getInvite: (token) => request(`/api/invites/${token}`),
  acceptInvite: (token, password) =>
    request(`/api/invites/${token}/accept`, { method: "POST", body: JSON.stringify({ password }) }),
  forgotPassword: (email) =>
    request("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token, password) =>
    request(`/api/auth/reset-password/${token}`, { method: "POST", body: JSON.stringify({ password }) }),
  // Self-service invite requests, gated by the allow-list below.
  requestInvite: (email) =>
    request("/api/justices/request-invite", { method: "POST", body: JSON.stringify({ email }) }),
  listAllowlist: () => request("/api/admin/justice-allowlist", { headers: authHeaders() }),
  addToAllowlist: (payload) =>
    request("/api/admin/justice-allowlist", { method: "POST", headers: authHeaders(), body: JSON.stringify(payload) }),
  removeFromAllowlist: (id) =>
    request(`/api/admin/justice-allowlist/${id}`, { method: "DELETE", headers: authHeaders() }),
  getJustice: (id) => request(`/api/justices/${id}`),
  updateMyProfile: (payload) =>
    request("/api/justices/me/profile", { method: "PATCH", headers: authHeaders(), body: JSON.stringify(payload) }),
  // --- Phase-6.2/6.3 docs: Justice-only recurring availability ---
  getMyAvailability: () => request("/api/justices/me/availability", { headers: authHeaders() }),
  updateMyAvailability: (cells) =>
    request("/api/justices/me/availability", {
      method: "PATCH", headers: authHeaders(), body: JSON.stringify({ cells }),
    }),
  hearingsAvailabilitySummary: (hearingIds) =>
    request("/api/hearings/availability-summary", {
      method: "POST", headers: authHeaders(), body: JSON.stringify({ hearing_ids: hearingIds }),
    }),
  teamAvailability: () => request("/api/justices/team/availability", { headers: authHeaders() }),
  // Bypasses the shared request() helper: a photo upload is
  // multipart/form-data, and the browser needs to set that header itself
  // (with the multipart boundary) -- request() always forces
  // application/json, which would break this call.
  uploadMyPhoto: async (file) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE}/api/justices/me/photo`, {
      method: "PUT", headers: authHeaders(), body: form,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json();
  },
  justicePhotoUrl: (id) => `${API_BASE}/api/justices/${id}/photo`,

  // --- Phase-4: reporting, 2FA ---
  createReport: (payload) => request("/api/reports", { method: "POST", body: JSON.stringify(payload) }),
  listReports: (resolved = false) => request(`/api/admin/reports?resolved=${resolved}`, { headers: authHeaders() }),
  resolveReport: (id) => request(`/api/admin/reports/${id}/resolve`, { method: "POST", headers: authHeaders() }),
  setup2fa: () => request("/api/account/2fa/setup", { method: "POST", headers: authHeaders() }),
  confirm2fa: (code) =>
    request("/api/account/2fa/confirm", { method: "POST", headers: authHeaders(), body: JSON.stringify({ code }) }),
  disable2fa: (password) =>
    request("/api/account/2fa/disable", {
      method: "POST", headers: authHeaders(), body: JSON.stringify({ password }),
    }),
};

export function getStoredAdmin() {
  const token = localStorage.getItem("cusg_admin_token");
  if (!token) return null;
  return {
    token,
    id: localStorage.getItem("cusg_admin_id") || null,
    role: localStorage.getItem("cusg_admin_role") || null,
    email: localStorage.getItem("cusg_admin_email"),
    isJustice: localStorage.getItem("cusg_admin_is_justice") === "true",
    displayName: localStorage.getItem("cusg_admin_display_name") || null,
    title: localStorage.getItem("cusg_admin_title") || null,
  };
}

export function storeAdmin({ token, id, role, email, is_justice, display_name, title }) {
  localStorage.setItem("cusg_admin_token", token);
  if (id) localStorage.setItem("cusg_admin_id", id);
  if (role) localStorage.setItem("cusg_admin_role", role);
  localStorage.setItem("cusg_admin_email", email);
  localStorage.setItem("cusg_admin_is_justice", is_justice ? "true" : "false");
  if (display_name) localStorage.setItem("cusg_admin_display_name", display_name);
  if (title) localStorage.setItem("cusg_admin_title", title);
}

export function clearAdmin() {
  for (const key of ["token", "id", "role", "email", "is_justice", "display_name", "title"]) {
    localStorage.removeItem(`cusg_admin_${key}`);
  }
}
