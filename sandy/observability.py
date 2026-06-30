"""Sentry error reporting for Sandy.

Two responsibilities live here:

* :func:`init_sentry` — initialize the Sentry SDK once at daemon startup,
  honoring the ``SENTRY_DSN`` / ``DEBUG`` conventions. Returns whether Sentry
  is active so the caller can log it.
* :func:`capture` — report a *handled* failure (one a plugin catches and turns
  into a friendly message instead of raising). It is a no-op when Sentry is not
  initialized, so plugins and the pipeline can call it unconditionally — in CLI
  mode, local dev, or DEBUG mode nothing is sent.

Without this, the only errors that ever reached Sentry were unhandled crashes;
Sandy's plugins are defensive and almost never raise, so Sentry stayed silent
even as commands visibly failed (issue #129).
"""

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

_TRACES_SAMPLE_RATE = 0.1

# Reporting is explicit (via capture()), never an implicit side effect of a log
# call. event_level=None keeps log records as breadcrumbs for context but stops
# the default LoggingIntegration from turning every logger.error into its own
# (untagged, possibly duplicated) Sentry event.
_LOGGING_INTEGRATION = LoggingIntegration(event_level=None)


def init_sentry(dsn: str, debug: bool, environment: str | None = None) -> bool:
    """Initialize Sentry error monitoring.

    Returns ``True`` when Sentry is initialized, ``False`` when skipped because
    the DSN is empty or ``debug`` is set (both safe in local dev).
    """
    if not dsn or debug:
        return False
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        environment=environment,
        integrations=[_LOGGING_INTEGRATION],
    )
    return True


def status_message(active: bool) -> str:
    """Human-readable Sentry status for the startup log."""
    if active:
        return "active"
    return "inactive (no SENTRY_DSN, or DEBUG mode)"


def capture(error, **context) -> None:
    """Report a handled error to Sentry. No-op when Sentry isn't initialized.

    ``error`` may be an exception instance (captured with its traceback) or a
    string message. Each keyword in ``context`` becomes a Sentry tag so failures
    can be filtered by plugin, source, etc.
    """
    if not sentry_sdk.is_initialized():
        return
    with sentry_sdk.new_scope() as scope:
        for key, value in context.items():
            scope.set_tag(key, value)
        if isinstance(error, BaseException):
            sentry_sdk.capture_exception(error)
        else:
            sentry_sdk.capture_message(str(error), level="error")
