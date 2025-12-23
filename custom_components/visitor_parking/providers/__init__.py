"""Provider factory for Visitor Parking."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from aiohttp import ClientSession

from ..const import PROVIDER_DVSPORTAL, PROVIDER_THE_HAGUE
from .dvsportal import DVSPortalProvider
from .thehague import TheHagueParkingProvider


class VisitorParkingProvider(Protocol):
    """Define the provider interface for visitor parking."""

    provider: str
    requires_end_time: bool
    supports_favorite_deletion: bool
    supports_reservation_adjust: bool

    async def async_login(self) -> None:
        """Validate credentials by performing a lightweight request."""
        ...

    async def async_fetch_all(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch account, reservations, and favorites."""
        ...

    async def async_fetch_account(self) -> dict[str, Any]:
        """Fetch account data."""
        ...

    async def async_fetch_reservations(self) -> list[dict[str, Any]]:
        """Fetch reservations."""
        ...

    async def async_fetch_favorites(self) -> list[dict[str, Any]]:
        """Fetch favorites."""
        ...

    async def async_fetch_zone_end_time(
        self, epoch_seconds: int
    ) -> dict[str, Any] | None:
        """Fetch a zone end time when supported."""
        ...

    async def async_create_reservation(
        self,
        *,
        license_plate: str,
        name: str | None,
        start_time: datetime,
        end_time: datetime | None,
    ) -> str | None:
        """Create a reservation and return its id if available."""
        ...

    async def async_delete_reservation(self, reservation_id: str) -> None:
        """Delete or end a reservation."""
        ...

    async def async_adjust_reservation_end_time(
        self, *, reservation_id: str, end_time: datetime
    ) -> None:
        """Adjust the reservation end time when supported."""
        ...

    async def async_create_favorite(self, *, name: str, license_plate: str) -> None:
        """Create a favorite."""
        ...

    async def async_update_favorite(
        self, *, favorite_id: str, name: str, license_plate: str
    ) -> None:
        """Update a favorite."""
        ...

    async def async_delete_favorite(self, favorite_id: str) -> None:
        """Delete a favorite when supported."""
        ...


def build_provider(
    *,
    provider: str,
    session: ClientSession,
    username: str | None = None,
    password: str | None = None,
    api_host: str | None = None,
    identifier: str | None = None,
) -> VisitorParkingProvider:
    """Build the provider client from config data."""
    if provider == PROVIDER_THE_HAGUE:
        return TheHagueParkingProvider(
            session=session,
            username=username,
            password=password,
            api_host=api_host,
        )
    if provider == PROVIDER_DVSPORTAL:
        return DVSPortalProvider(
            session=session,
            api_host=api_host,
            identifier=identifier,
            password=password,
        )
    raise ValueError(f"Unsupported provider: {provider}")


__all__ = ["VisitorParkingProvider", "build_provider"]
