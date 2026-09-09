"""
Job-failure alerting (Section 8: "notify an Editor if a scheduled pull fails
or returns unexpectedly empty data").

No paging/notification account (Slack webhook, email, PagerDuty, etc.)
exists for this build, so ALERT_BACKEND="console" logs loudly at ERROR
level and that's it. Swap in a real integration behind alert_job_failure()
once the CUSG team has a channel they want alerts sent to -- everything
that calls this function doesn't need to change.
"""
import logging

from app.config import ALERT_BACKEND

logger = logging.getLogger("alerts")


def alert_job_failure(job_name: str, message: str) -> None:
    if ALERT_BACKEND == "console":
        logger.error("JOB FAILURE ALERT [%s]: %s", job_name, message)
        return
    raise NotImplementedError(f"Unknown ALERT_BACKEND {ALERT_BACKEND!r}")
