"""
Job-failure alerting (Section 8: "notify an Editor if a scheduled pull fails
or returns unexpectedly empty data").

Phase 8 doc (news tracking rebuild): upgraded from console-only to real
email, reusing the already-working app/jobs/digest.py::send_email()
(SendGrid) rather than inventing a second email-sending path. This was
added specifically because the news-search job's quota-approaching alert
is only useful if someone actually sees it -- a log line in Render/GitHub
Actions logs that nobody proactively reads doesn't satisfy "alert me."
ALERT_BACKEND="console" (the default, safe with no email configured)
still just logs; set ALERT_BACKEND=email + ALERT_EMAIL_ADDRESS in
production for real delivery.

`severity` distinguishes a genuine failure ("high", the default -- what
every pre-Phase-8 caller already meant) from a low-urgency notice like a
quota warning ("low") -- Section 4 of the Phase 8 doc is explicit that
this pipeline is an enrichment layer, not the site's backbone, and its
failures shouldn't read as page-the-team emergencies.
"""
import logging

from app.config import ALERT_BACKEND, ALERT_EMAIL_ADDRESS

logger = logging.getLogger("alerts")


def alert_job_failure(job_name: str, message: str, severity: str = "high") -> None:
    if ALERT_BACKEND == "console":
        level = logging.ERROR if severity == "high" else logging.WARNING
        logger.log(level, "JOB ALERT [%s] severity=%s: %s", job_name, severity, message)
        return
    if ALERT_BACKEND == "email":
        _send_alert_email(job_name, message, severity)
        return
    raise NotImplementedError(f"Unknown ALERT_BACKEND {ALERT_BACKEND!r}")


def alert_quota_warning(api_name: str, count: int, limit: int) -> None:
    """Phase 8 doc: fired by app/external_api_usage.py::record_usage()
    the first time a metered API's daily call count crosses its alert
    threshold. Always low-urgency -- approaching a free-tier quota is
    worth knowing about, not an emergency."""
    alert_job_failure(
        "news_search_quota",
        f"{api_name} has made {count}/{limit} queries today -- approaching the daily quota.",
        severity="low",
    )


def _send_alert_email(job_name: str, message: str, severity: str) -> None:
    if not ALERT_EMAIL_ADDRESS:
        logger.error(
            "ALERT_BACKEND=email but ALERT_EMAIL_ADDRESS isn't set -- "
            "alert for job=%s severity=%s was NOT sent: %s", job_name, severity, message,
        )
        return
    # Local import: app.jobs.digest imports from app.models, and importing
    # it at module level here would risk a circular import depending on
    # what else app.jobs.digest ends up importing later -- deferred to
    # call time instead, same pattern already used elsewhere in this
    # codebase for a similar reason (e.g. news_search.py's own imports).
    from app.jobs.digest import send_email
    send_email(ALERT_EMAIL_ADDRESS, f"[{severity}] {job_name} alert", message)
