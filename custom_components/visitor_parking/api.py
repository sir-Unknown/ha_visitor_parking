"""API helpers for the Visitor Parking integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiohttp import ClientSession

from .providers import VisitorParkingProvider, build_provider


class VisitorParkingClient:
    """Client wrapper for visitor parking providers."""

    def __init__(
        self,
        *,
        provider: str,
        session: ClientSession,
        username: str | None = None,
        password: str | None = None,
        api_host: str | None = None,
        identifier: str | None = None,
    ) -> None:
        """Initialize the client."""
        self._provider: VisitorParkingProvider = build_provider(
            provider=provider,
            session=session,
            username=username,
            password=password,
            api_host=api_host,
            identifier=identifier,
        )

    @property
    def provider(self) -> str:
        """Return the provider identifier."""
        return self._provider.provider

    @property
    def requires_end_time(self) -> bool:
        """Return True when reservations must include an end time."""
        return self._provider.requires_end_time

    @property
    def supports_favorite_deletion(self) -> bool:
        """Return True when favorites can be deleted."""
        return self._provider.supports_favorite_deletion

    @property
    def supports_reservation_adjust(self) -> bool:
        """Return True when reservation end times can be adjusted."""
        return self._provider.supports_reservation_adjust

    async def async_login(self) -> None:
        """Validate credentials by performing a lightweight request."""
        await self._provider.async_login()

    async def async_fetch_all(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch account, reservations, and favorites."""
        return await self._provider.async_fetch_all()

    async def async_fetch_account(self) -> dict[str, Any]:
        """Fetch account data."""
        return await self._provider.async_fetch_account()

    async def async_fetch_reservations(self) -> list[dict[str, Any]]:
        """Fetch reservations."""
        return await self._provider.async_fetch_reservations()

    async def async_fetch_favorites(self) -> list[dict[str, Any]]:
        """Fetch favorites."""
        return await self._provider.async_fetch_favorites()

    async def async_fetch_zone_end_time(
        self, epoch_seconds: int
    ) -> dict[str, Any] | None:
        """Fetch a zone end time when supported."""
        return await self._provider.async_fetch_zone_end_time(epoch_seconds)

    async def async_create_reservation(
        self,
        *,
        license_plate: str,
        name: str | None,
        start_time: datetime,
        end_time: datetime | None,
    ) -> str | None:
        """Create a reservation and return its id if available."""
        return await self._provider.async_create_reservation(
            license_plate=license_plate,
            name=name,
            start_time=start_time,
            end_time=end_time,
        )

    async def async_delete_reservation(self, reservation_id: str) -> None:
        """Delete or end a reservation."""
        await self._provider.async_delete_reservation(reservation_id)

    async def async_adjust_reservation_end_time(
        self, *, reservation_id: str, end_time: datetime
    ) -> None:
        """Adjust the reservation end time when supported."""
        await self._provider.async_adjust_reservation_end_time(
            reservation_id=reservation_id,
            end_time=end_time,
        )

    async def async_create_favorite(self, *, name: str, license_plate: str) -> None:
        """Create a favorite."""
        await self._provider.async_create_favorite(
            name=name,
            license_plate=license_plate,
        )

    async def async_update_favorite(
        self, *, favorite_id: str, name: str, license_plate: str
    ) -> None:
        """Update a favorite."""
        await self._provider.async_update_favorite(
            favorite_id=favorite_id,
            name=name,
            license_plate=license_plate,
        )

    async def async_delete_favorite(self, favorite_id: str) -> None:
        """Delete a favorite when supported."""
        await self._provider.async_delete_favorite(favorite_id)


def normalize_identifier(value: object) -> str | None:
    """Normalize identifiers to a trimmed string."""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None
