"""DVSPortal provider implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from aiohttp import ClientSession

from dvsportal import (
    DVSPortal,
    DVSPortalAuthError,
    DVSPortalConnectionError,
    DVSPortalError,
)

from ..const import PROVIDER_DVSPORTAL
from ..data_normalization import (
    normalize_account_data,
    normalize_favorites,
    normalize_reservations,
)
from ..errors import (
    VisitorParkingAuthError,
    VisitorParkingConnectionError,
    VisitorParkingError,
    VisitorParkingUnsupportedError,
)

T = TypeVar("T")


class DVSPortalProvider:
    """Provider implementation backed by the DVSPortal API."""

    provider = PROVIDER_DVSPORTAL
    requires_end_time = False
    supports_favorite_deletion = False
    supports_reservation_adjust = False

    def __init__(
        self,
        *,
        session: ClientSession,
        api_host: str | None,
        identifier: str | None,
        password: str | None,
    ) -> None:
        if not api_host or not identifier or not password:
            raise ValueError("api_host, identifier, and password are required")
        self._client = DVSPortal(
            api_host=api_host,
            identifier=identifier,
            password=password,
            session=session,
        )
        self._api_host = api_host
        self._identifier = identifier

    async def async_login(self) -> None:
        """Validate credentials by performing a lightweight request."""
        await self._wrap(self._client.token)

    async def async_fetch_all(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch account, reservations, and favorites."""
        await self._wrap(self._client.update)
        account = normalize_account_data(
            _account_data(self._client, self._api_host, self._identifier),
            PROVIDER_DVSPORTAL,
        )
        reservations = normalize_reservations(
            _reservations_data(self._client), PROVIDER_DVSPORTAL
        )
        favorites = normalize_favorites(
            _favorites_data(self._client), PROVIDER_DVSPORTAL
        )
        return (account, reservations, favorites)

    async def async_fetch_account(self) -> dict[str, Any]:
        """Fetch account data."""
        await self._wrap(self._client.update)
        return normalize_account_data(
            _account_data(self._client, self._api_host, self._identifier),
            PROVIDER_DVSPORTAL,
        )

    async def async_fetch_reservations(self) -> list[dict[str, Any]]:
        """Fetch reservations."""
        await self._wrap(self._client.update)
        return normalize_reservations(
            _reservations_data(self._client), PROVIDER_DVSPORTAL
        )

    async def async_fetch_favorites(self) -> list[dict[str, Any]]:
        """Fetch favorites."""
        await self._wrap(self._client.update)
        return normalize_favorites(_favorites_data(self._client), PROVIDER_DVSPORTAL)

    async def async_fetch_zone_end_time(
        self, epoch_seconds: int
    ) -> dict[str, Any] | None:
        """Fetch a zone end time when supported."""
        _ = epoch_seconds
        return None

    async def async_create_reservation(
        self,
        *,
        license_plate: str,
        name: str | None,
        start_time: datetime,
        end_time: datetime | None,
    ) -> str | None:
        """Create a reservation and return its id if available."""
        await self._async_prepare()
        response = await self._wrap(
            self._client.create_reservation,
            license_plate_value=license_plate,
            license_plate_name=name,
            date_from=start_time,
            date_until=end_time,
        )
        return _reservation_id_from_response(response)

    async def async_delete_reservation(self, reservation_id: str) -> None:
        """Delete or end a reservation."""
        await self._async_prepare()
        await self._wrap(self._client.end_reservation, reservation_id=reservation_id)

    async def async_adjust_reservation_end_time(
        self, *, reservation_id: str, end_time: datetime
    ) -> None:
        """Adjust the reservation end time when supported."""
        _ = reservation_id
        _ = end_time
        raise VisitorParkingUnsupportedError("Reservation adjustments not supported")

    async def async_create_favorite(self, *, name: str, license_plate: str) -> None:
        """Create a favorite."""
        await self._async_prepare()
        await self._wrap(
            self._client.store_license_plate,
            license_plate=license_plate,
            name=name,
        )

    async def async_update_favorite(
        self, *, favorite_id: str, name: str, license_plate: str
    ) -> None:
        """Update a favorite."""
        _ = favorite_id
        await self._async_prepare()
        await self._wrap(
            self._client.store_license_plate,
            license_plate=license_plate,
            name=name,
        )

    async def async_delete_favorite(self, favorite_id: str) -> None:
        """Delete a favorite when supported."""
        _ = favorite_id
        raise VisitorParkingUnsupportedError("Favorite deletion not supported")

    async def _async_prepare(self) -> None:
        if self._client.default_type_id is None or self._client.default_code is None:
            await self._wrap(self._client.update)

    async def _wrap(
        self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        try:
            return await func(*args, **kwargs)
        except DVSPortalAuthError as err:
            raise VisitorParkingAuthError from err
        except DVSPortalConnectionError as err:
            raise VisitorParkingConnectionError from err
        except DVSPortalError as err:
            raise VisitorParkingError(str(err)) from err


def _account_data(
    client: DVSPortal, api_host: str | None, identifier: str | None
) -> dict[str, Any]:
    return {
        "provider": PROVIDER_DVSPORTAL,
        "balance": client.balance,
        "api_host": api_host,
        "identifier": identifier,
    }


def _reservations_data(client: DVSPortal) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    known = client.known_license_plates
    for reservation in client.active_reservations.values():
        valid_from = reservation.get("valid_from")
        valid_until = reservation.get("valid_until")
        results.append(
            {
                "id": reservation.get("reservation_id"),
                "license_plate": reservation.get("license_plate"),
                "name": known.get(reservation.get("license_plate"), None),
                "start_time": _isoformat(valid_from),
                "end_time": _isoformat(valid_until),
                "units": reservation.get("units"),
                "cost": reservation.get("cost"),
            }
        )
    return results


def _favorites_data(client: DVSPortal) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for plate, name in sorted(client.known_license_plates.items()):
        results.append(
            {
                "id": plate,
                "license_plate": plate,
                "name": name or None,
            }
        )
    return results


def _isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _reservation_id_from_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _reservation_id_from_response(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in ("ReservationID", "ReservationId", "reservation_id", "reservationId"):
        if key in response:
            return _reservation_id_from_value(response.get(key))
    return None
