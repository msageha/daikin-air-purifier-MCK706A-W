class DaikinError(Exception):
    def __init__(self, message: str, *, rsc: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.rsc = rsc


class DaikinConnectionError(DaikinError):
    pass
