"""Errors for the Visitor Parking integration."""

from __future__ import annotations


class VisitorParkingError(Exception):
    """Base exception for Visitor Parking."""


class VisitorParkingAuthError(VisitorParkingError):
    """Raised when authentication fails."""


class VisitorParkingConnectionError(VisitorParkingError):
    """Raised when the API cannot be reached."""


class VisitorParkingRateLimitError(VisitorParkingError):
    """Raised when the API rate limit is exceeded."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("Rate limit exceeded")
        self.retry_after = retry_after


class VisitorParkingUnsupportedError(VisitorParkingError):
    """Raised when a provider does not support an action."""
