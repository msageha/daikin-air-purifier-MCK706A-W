class DaikinError(Exception):
    """Generic error talking to the Daikin unit."""

    def __init__(self, message: str, *, rsc: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        # ``rsc`` is the per-request "response status code" dsiot returns
        # (2000 == OK). Surfaced for debugging non-OK responses.
        self.rsc = rsc


class DaikinConnectionError(DaikinError):
    """Network level failure reaching the unit."""
