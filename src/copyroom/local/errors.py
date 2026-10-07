"""Errors for the local workflow."""


class LocalError(Exception):
    """A local input, state, or jj action failed."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code
