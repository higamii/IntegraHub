"""Domain and upstream exceptions."""


class IntegraHubError(Exception):
    """Base class for errors that are translated into HTTP responses."""

    status_code = 500
    code = "internal_error"


class NotFoundError(IntegraHubError):
    status_code = 404
    code = "not_found"


class IntegrationNotFoundError(NotFoundError):
    code = "integration_not_found"

    def __init__(self, name: str) -> None:
        super().__init__(f"Integration '{name}' does not exist")


class SyncRunNotFoundError(NotFoundError):
    code = "sync_run_not_found"

    def __init__(self, run_id: int) -> None:
        super().__init__(f"Sync run {run_id} does not exist")


class RecordNotFoundError(NotFoundError):
    code = "record_not_found"

    def __init__(self, record_id: int) -> None:
        super().__init__(f"Record {record_id} does not exist")


class ConflictError(IntegraHubError):
    status_code = 409
    code = "conflict"


class IntegrationDisabledError(ConflictError):
    code = "integration_disabled"

    def __init__(self, name: str) -> None:
        super().__init__(f"Integration '{name}' is disabled")


class SyncInProgressError(ConflictError):
    code = "sync_in_progress"

    def __init__(self, name: str) -> None:
        super().__init__(f"A synchronization for '{name}' is already in progress")


class UpstreamError(Exception):
    """A failure while talking to an external API.

    These are never returned to API clients directly: the synchronization service
    records them in the sync history and updates the integration status instead.
    """

    retryable = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        #: Number of HTTP attempts made before giving up (set by the HTTP client).
        self.attempts = 0


class UpstreamTimeoutError(UpstreamError):
    retryable = True


class UpstreamConnectionError(UpstreamError):
    retryable = True


class UpstreamHTTPError(UpstreamError):
    """The upstream answered with an HTTP error status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, retry_after=retry_after)
        self.status_code = status_code
        self.retryable = retryable


class UpstreamInvalidResponseError(UpstreamError):
    """The upstream answered 2xx but the body was not valid or had an unexpected shape."""
