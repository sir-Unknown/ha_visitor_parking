"""Coordinator for the Visitor Parking integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VisitorParkingClient
from .const import DOMAIN
from .errors import (
    VisitorParkingAuthError,
    VisitorParkingConnectionError,
    VisitorParkingError,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisitorParkingData:
    """Data returned by the coordinator."""

    account: dict[str, Any]
    reservations: list[dict[str, Any]]
    favorites: list[dict[str, Any]]
    provider: str


class VisitorParkingCoordinator(DataUpdateCoordinator[VisitorParkingData]):
    """Coordinator to fetch data from visitor parking providers."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        client: VisitorParkingClient,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=1),
            config_entry=config_entry,
        )
        self.client = client
        self._unavailable_logged = False

    async def _async_update_data(self) -> VisitorParkingData:
        try:
            account, reservations, favorites = await self.client.async_fetch_all()
        except VisitorParkingAuthError as err:
            raise ConfigEntryAuthFailed("Authentication failed") from err
        except VisitorParkingConnectionError as err:
            if not self._unavailable_logged:
                _LOGGER.info("The service is unavailable: %s", err)
                self._unavailable_logged = True
            raise UpdateFailed("Cannot connect") from err
        except VisitorParkingError as err:
            raise UpdateFailed(str(err)) from err

        if self._unavailable_logged:
            _LOGGER.info("The service is back online")
            self._unavailable_logged = False

        return VisitorParkingData(
            account=account,
            reservations=reservations,
            favorites=favorites,
            provider=self.client.provider,
        )
