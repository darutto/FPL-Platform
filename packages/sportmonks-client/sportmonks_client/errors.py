"""Secret-safe Sportmonks client errors."""
from __future__ import annotations


class SportmonksError(Exception):
    def __init__(self, message: str, *, endpoint: str | None = None, status_code: int | None = None) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        context = f" endpoint={endpoint}" if endpoint else ""
        context += f" status={status_code}" if status_code is not None else ""
        super().__init__(message + context)


class SportmonksConfigurationError(SportmonksError): pass
class SportmonksAuthenticationError(SportmonksError): pass
class SportmonksRateLimitError(SportmonksError): pass
class SportmonksRequestError(SportmonksError):
    def __init__(self, message: str, *, retryable: bool = False, endpoint: str | None = None, status_code: int | None = None) -> None:
        self.retryable = retryable
        super().__init__(message, endpoint=endpoint, status_code=status_code)
class SportmonksResponseError(SportmonksError): pass
class SportmonksPaginationError(SportmonksError): pass
class SportmonksSchemaError(SportmonksError): pass
