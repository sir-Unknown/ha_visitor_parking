"""The Hague parking provider implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, TypeVar

from aiohttp import ClientSession

from pythehagueparking import (
    Auth,
    AuthError,
    Favorite,
    ParkingConnectionError,
    ParkerenDenHaagAPI,
    ParseError,
    PyTheHagueParkingError,
    RateLimitError,
    Reservation,
)

from ..const import PROVIDER_THE_HAGUE
from ..data_normalization import (
    normalize_account_data,
    normalize_favorites,
    normalize_reservations,
)
from ..errors import (
    VisitorParkingAuthError,
    VisitorParkingConnectionError,
    VisitorParkingError,
    VisitorParkingRateLimitError,
)

T = TypeVar("T")


class TheHagueParkingProvider:
    """Provider implementation backed by Parkeren Den Haag."""

    provider = PROVIDER_THE_HAGUE
    requires_end_time = True
    supports_favorite_deletion = True
    supports_reservation_adjust = True

    def __init__(
        self,
        *,
        session: ClientSession,
        username: str | None,
        password: str | None,
        api_host: str | None = None,
    ) -> None:
        if not username or not password:
            raise ValueError("username and password are required")
        self._session = session
        self._username = username
        self._password = password
        self._client: ParkerenDenHaagAPI | None = None
        self._client_lock = asyncio.Lock()
        self._api_host = api_host

    def _build_client(self) -> ParkerenDenHaagAPI:
        """Build the API client."""
        auth = Auth(self._session, self._username, self._password)
        return ParkerenDenHaagAPI(auth)

    async def _ensure_client(self) -> ParkerenDenHaagAPI:
        """Ensure the API client is initialized off the event loop."""
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(self._build_client)
        return self._client

    async def async_login(self) -> None:
        """Validate credentials by performing a lightweight request."""
        client = await self._ensure_client()
        await self._wrap(client.async_get_account)

    async def async_fetch_all(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch account, reservations, and favorites."""
        client = await self._ensure_client()
        try:
            account, reservations, favorites = await asyncio.gather(
                client.async_get_account(),
                client.async_list_reservations(),
                client.async_list_favorites(),
            )
            return (
                normalize_account_data(
                    _account_data(account, self._api_host), PROVIDER_THE_HAGUE
                ),
                normalize_reservations(
                    [_reservation_dict(item) for item in reservations],
                    PROVIDER_THE_HAGUE,
                ),
                normalize_favorites(
                    [_favorite_dict(item) for item in favorites],
                    PROVIDER_THE_HAGUE,
                ),
            )
        except AuthError as err:
            raise VisitorParkingAuthError from err
        except ParkingConnectionError as err:
            raise VisitorParkingConnectionError from err
        except RateLimitError as err:
            raise VisitorParkingRateLimitError(err.retry_after) from err
        except (ParseError, PyTheHagueParkingError) as err:
            raise VisitorParkingError(str(err)) from err

    async def async_fetch_account(self) -> dict[str, Any]:
        """Fetch account data."""
        client = await self._ensure_client()
        account = await self._wrap(client.async_get_account)
        return normalize_account_data(
            _account_data(account, self._api_host), PROVIDER_THE_HAGUE
        )

    async def async_fetch_reservations(self) -> list[dict[str, Any]]:
        """Fetch reservations."""
        client = await self._ensure_client()
        reservations = await self._wrap(client.async_list_reservations)
        return normalize_reservations(
            [_reservation_dict(item) for item in reservations],
            PROVIDER_THE_HAGUE,
        )

    async def async_fetch_favorites(self) -> list[dict[str, Any]]:
        """Fetch favorites."""
        client = await self._ensure_client()
        favorites = await self._wrap(client.async_list_favorites)
        return normalize_favorites(
            [_favorite_dict(item) for item in favorites],
            PROVIDER_THE_HAGUE,
        )

    async def async_fetch_zone_end_time(
        self, epoch_seconds: int
    ) -> dict[str, Any] | None:
        """Fetch a zone end time when supported."""
        _ = epoch_seconds
        account = await self.async_fetch_account()
        zone = account.get("zone")
        if isinstance(zone, dict) and zone.get("end_time"):
            return {"end_time": zone.get("end_time")}
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
        client = await self._ensure_client()
        reservation = await self._wrap(
            client.async_create_reservation,
            name=name,
            license_plate=license_plate,
            start_time=start_time.isoformat().replace("+00:00", "Z"),
            end_time=end_time.isoformat().replace("+00:00", "Z") if end_time else None,
        )
        return _reservation_id_from_value(reservation.id)

    async def async_delete_reservation(self, reservation_id: str) -> None:
        """Delete or end a reservation."""
        reservation = await self._find_reservation(reservation_id)
        if reservation is None:
            raise VisitorParkingError("Reservation not found")
        await self._wrap(reservation.async_delete)

    async def async_adjust_reservation_end_time(
        self, *, reservation_id: str, end_time: datetime
    ) -> None:
        """Adjust the reservation end time when supported."""
        reservation = await self._find_reservation(reservation_id)
        if reservation is None:
            raise VisitorParkingError("Reservation not found")
        await self._wrap(
            reservation.async_update,
            end_time=end_time.isoformat().replace("+00:00", "Z"),
        )

    async def async_create_favorite(self, *, name: str, license_plate: str) -> None:
        """Create a favorite."""
        client = await self._ensure_client()
        await self._wrap(
            client.async_create_favorite,
            name=name,
            license_plate=license_plate,
        )

    async def async_update_favorite(
        self, *, favorite_id: str, name: str, license_plate: str
    ) -> None:
        """Update a favorite."""
        favorite = await self._find_favorite(favorite_id)
        if favorite is None:
            raise VisitorParkingError("Favorite not found")
        await self._wrap(
            favorite.async_update,
            name=name,
            license_plate=license_plate,
        )

    async def async_delete_favorite(self, favorite_id: str) -> None:
        """Delete a favorite when supported."""
        favorite = await self._find_favorite(favorite_id)
        if favorite is None:
            raise VisitorParkingError("Favorite not found")
        await self._wrap(favorite.async_delete)

    async def _wrap(
        self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        try:
            return await func(*args, **kwargs)
        except AuthError as err:
            raise VisitorParkingAuthError from err
        except ParkingConnectionError as err:
            raise VisitorParkingConnectionError from err
        except RateLimitError as err:
            raise VisitorParkingRateLimitError(err.retry_after) from err
        except (ParseError, PyTheHagueParkingError) as err:
            raise VisitorParkingError(str(err)) from err

    async def _find_reservation(self, reservation_id: str) -> Reservation | None:
        client = await self._ensure_client()
        reservations = await self._wrap(client.async_list_reservations)
        for reservation in reservations:
            if _match_id(reservation.id, reservation_id):
                return reservation
        return None

    async def _find_favorite(self, favorite_id: str) -> Favorite | None:
        client = await self._ensure_client()
        favorites = await self._wrap(client.async_list_favorites)
        for favorite in favorites:
            if _match_id(favorite.id, favorite_id):
                return favorite
        return None


def _account_data(account: Any, api_host: str | None) -> dict[str, Any]:
    data = dict(account.raw_data)
    zone = account.zone
    if zone is not None:
        data["zone"] = dict(zone.raw_data)
    if api_host:
        data["api_host"] = api_host
    data["provider"] = PROVIDER_THE_HAGUE
    return data


def _reservation_dict(reservation: Reservation) -> dict[str, Any]:
    return dict(reservation.raw_data)


def _favorite_dict(favorite: Favorite) -> dict[str, Any]:
    return dict(favorite.raw_data)


def _match_id(value: Any, target: str) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return str(value) == target
    if isinstance(value, str):
        return value.strip() == target
    return False


def _reservation_id_from_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None
