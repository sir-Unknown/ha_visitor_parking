"""Service handlers for Visitor Parking."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from functools import partial
import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import VisitorParkingClient, normalize_identifier
from .const import (
    CONF_AUTO_END_ENABLED,
    DOMAIN,
    SERVICE_ADJUST_RESERVATION_END_TIME,
    SERVICE_CREATE_FAVORITE,
    SERVICE_CREATE_RESERVATION,
    SERVICE_DELETE_FAVORITE,
    SERVICE_DELETE_RESERVATION,
    SERVICE_UPDATE_FAVORITE,
)
from .errors import (
    VisitorParkingAuthError,
    VisitorParkingConnectionError,
    VisitorParkingError,
    VisitorParkingRateLimitError,
    VisitorParkingUnsupportedError,
)
from .schedule import scheduled_end_for_start

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("license_plate"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("start_time"): cv.string,
        vol.Optional("end_time"): cv.string,
        vol.Optional("start_time_entity_id"): cv.entity_id,
        vol.Optional("end_time_entity_id"): cv.entity_id,
    }
)

SERVICE_DELETE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("reservation_id"): vol.Any(cv.positive_int, cv.string),
    }
)

SERVICE_ADJUST_END_TIME_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("reservation_id"): vol.Any(cv.positive_int, cv.string),
        vol.Required("end_time"): cv.string,
    }
)

SERVICE_CREATE_FAVORITE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("license_plate"): cv.string,
        vol.Required("name"): cv.string,
    }
)

SERVICE_DELETE_FAVORITE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("favorite_id"): vol.Any(cv.positive_int, cv.string),
    }
)

SERVICE_UPDATE_FAVORITE_SCHEMA = vol.Schema(
    {
        vol.Optional("config_entry_id"): cv.string,
        vol.Required("favorite_id"): vol.Any(cv.positive_int, cv.string),
        vol.Required("license_plate"): cv.string,
        vol.Required("name"): cv.string,
    }
)


def _as_utc(value: datetime) -> datetime:
    """Return the datetime in UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(value)


def _parse_required_dt(value: str, field: str) -> datetime:
    """Parse a required datetime string."""
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_datetime_string",
            translation_placeholders={"field": field, "value": value},
        )
    return _as_utc(parsed)


def _parse_optional_dt(value: str | None, field: str) -> datetime | None:
    """Parse an optional datetime string."""
    if value is None or value.strip() == "":
        return None
    return _parse_required_dt(value, field)


def _parse_dt_from_entity_id(
    hass: HomeAssistant, entity_id: str, field: str
) -> datetime:
    """Parse a datetime value from an entity state."""
    if not (state := hass.states.get(entity_id)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="datetime_entity_not_found",
            translation_placeholders={"field": field, "entity_id": entity_id},
        )

    if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="datetime_entity_no_value",
            translation_placeholders={"field": field, "entity_id": entity_id},
        )

    return _parse_required_dt(state.state, field)


def _get_entry_id(hass: HomeAssistant, call: ServiceCall) -> str:
    """Resolve the config entry id for the service call."""
    entry_id = call.data.get("config_entry_id")
    if entry_id is not None:
        return entry_id

    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_config_entries_loaded",
        )
    if len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="set_config_entry_id_multiple_entries",
        )

    return next(iter(entries))


def _get_runtime_data(hass: HomeAssistant, call: ServiceCall) -> tuple[str, Any]:
    """Return the entry id and runtime data for the service call."""
    entry_id = _get_entry_id(hass, call)
    if not (runtime_data := hass.data.get(DOMAIN, {}).get(entry_id)):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="config_entry_not_loaded",
        )
    return entry_id, runtime_data


def _error_for_user(err: VisitorParkingError) -> str:
    """Return a user-friendly error summary."""
    if isinstance(err, VisitorParkingAuthError):
        return "Authentication failed"
    if isinstance(err, VisitorParkingConnectionError):
        return "Cannot connect"
    if isinstance(err, VisitorParkingRateLimitError):
        return "Rate limit exceeded"
    if isinstance(err, VisitorParkingUnsupportedError):
        return "Not supported"
    return str(err)


def _normalize_license_plate(value: str) -> str:
    """Normalize a license plate value."""
    return value.strip().upper()


def _required_license_plate(value: str) -> str:
    """Validate a required license plate value."""
    license_plate = _normalize_license_plate(value)
    if not license_plate:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_license_plate",
        )
    return license_plate


def _normalize_optional_name(value: Any) -> str | None:
    """Normalize a user-provided name value."""
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name or None


def _normalize_identifier(value: int | str, field: str) -> str:
    """Normalize an identifier or raise when invalid."""
    normalized = normalize_identifier(value)
    if not normalized:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_identifier",
            translation_placeholders={"field": field},
        )
    return normalized


def _hhmm(value: datetime) -> str:
    """Format a datetime as local HH:MM."""
    local = dt_util.as_local(value)
    return f"{local.hour:02d}:{local.minute:02d}"


def _find_reservation(
    reservations: list[dict[str, Any]], reservation_id: str
) -> dict[str, Any] | None:
    """Find a reservation by id."""
    for reservation in reservations:
        if str(reservation.get("id")).strip() == reservation_id:
            return reservation
    return None


def _parse_start_time(hass: HomeAssistant, call: ServiceCall) -> datetime:
    """Resolve the reservation start time from the service call."""
    start_time = _parse_optional_dt(call.data.get("start_time"), "start_time")
    if start_time is None and call.data.get("start_time_entity_id"):
        start_time = _parse_dt_from_entity_id(
            hass, call.data["start_time_entity_id"], "start_time"
        )
    return start_time or _as_utc(dt_util.now())


def _parse_end_time(hass: HomeAssistant, call: ServiceCall) -> datetime | None:
    """Resolve the reservation end time from the service call."""
    end_time = _parse_optional_dt(call.data.get("end_time"), "end_time")
    if end_time is None and call.data.get("end_time_entity_id"):
        end_time = _parse_dt_from_entity_id(
            hass, call.data["end_time_entity_id"], "end_time"
        )
    return end_time


async def _async_fetch_zone_end_time(
    client: VisitorParkingClient,
    start_time: datetime,
    field: str,
    *,
    log_error: bool = False,
) -> datetime | None:
    """Fetch the zone end time for a given start time."""
    try:
        zone = await client.async_fetch_zone_end_time(int(start_time.timestamp()))
    except VisitorParkingError as err:
        if log_error:
            _LOGGER.debug("Could not determine zone end time", exc_info=err)
        return None

    zone_end_str = zone.get("end_time") if zone else None
    if isinstance(zone_end_str, str):
        return _parse_required_dt(zone_end_str, field)
    return None


async def _async_validate_start_time(
    start_time: datetime,
    options: Mapping[str, Any],
    client: VisitorParkingClient,
) -> None:
    """Validate the start time against the configured schedule."""
    schedule_end = scheduled_end_for_start(start_time, options)
    if schedule_end is None:
        return

    working_to_hhmm, working_to_utc = schedule_end
    zone_end = await _async_fetch_zone_end_time(client, start_time, "zone_end_time")
    if (
        zone_end is not None
        and working_to_utc < zone_end
        and working_to_utc <= start_time < zone_end
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="start_time_after_working_to",
            translation_placeholders={
                "working_to": working_to_hhmm,
                "zone_end": _hhmm(zone_end),
            },
        )


async def _async_resolve_end_time(
    hass: HomeAssistant,
    call: ServiceCall,
    client: VisitorParkingClient,
    start_time: datetime,
) -> datetime | None:
    """Resolve the reservation end time from the call and provider."""
    end_time = _parse_end_time(hass, call)
    if end_time is None and client.requires_end_time:
        zone_end = await _async_fetch_zone_end_time(
            client,
            start_time,
            "end_time",
            log_error=True,
        )
        if zone_end is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="could_not_determine_zone_end_time",
            )
        end_time = zone_end

    if end_time is not None and end_time <= start_time:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="end_time_must_be_after_start_time",
        )
    return end_time


async def _async_create_reservation(hass: HomeAssistant, call: ServiceCall) -> None:
    """Create a reservation via the service call."""
    entry_id, runtime_data = _get_runtime_data(hass, call)

    coordinator = runtime_data.coordinator
    client = coordinator.client
    entry = hass.config_entries.async_get_entry(entry_id)
    options = entry.options if entry else {}

    license_plate = _required_license_plate(call.data["license_plate"])
    name = _normalize_optional_name(call.data.get("name"))
    start_time = _parse_start_time(hass, call)

    if bool(options.get(CONF_AUTO_END_ENABLED, True)):
        await _async_validate_start_time(start_time, options, client)

    end_time = await _async_resolve_end_time(hass, call, client, start_time)

    try:
        reservation_id = await client.async_create_reservation(
            license_plate=license_plate,
            name=name,
            start_time=start_time,
            end_time=end_time,
        )
    except VisitorParkingUnsupportedError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="action_not_supported",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err
    except VisitorParkingError as err:
        _LOGGER.debug("Could not create reservation", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_create_reservation",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    if reservation_id is not None:
        async with runtime_data.created_reservations_lock:
            runtime_data.created_reservation_ids.add(reservation_id)
            await runtime_data.created_reservations_store.async_save(
                runtime_data.created_reservation_ids
            )

    await coordinator.async_request_refresh()


async def _async_delete_reservation(hass: HomeAssistant, call: ServiceCall) -> None:
    """Delete a reservation via the service call."""
    _entry_id, runtime_data = _get_runtime_data(hass, call)

    coordinator = runtime_data.coordinator
    client = coordinator.client

    reservation_id = _normalize_identifier(
        call.data["reservation_id"], "reservation_id"
    )

    try:
        await client.async_delete_reservation(reservation_id)
    except VisitorParkingUnsupportedError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="action_not_supported",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err
    except VisitorParkingError as err:
        _LOGGER.debug("Could not delete reservation", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_delete_reservation",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    async with runtime_data.created_reservations_lock:
        if reservation_id in runtime_data.created_reservation_ids:
            runtime_data.created_reservation_ids.remove(reservation_id)
            await runtime_data.created_reservations_store.async_save(
                runtime_data.created_reservation_ids
            )

    await coordinator.async_request_refresh()


async def _async_adjust_reservation_end_time(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Adjust the reservation end time via the service call."""
    _entry_id, runtime_data = _get_runtime_data(hass, call)

    coordinator = runtime_data.coordinator
    client = coordinator.client

    if not client.supports_reservation_adjust:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="adjust_not_supported",
        )

    reservation_id = _normalize_identifier(
        call.data["reservation_id"], "reservation_id"
    )
    end_time = _parse_required_dt(call.data["end_time"], "end_time")

    reservation = _find_reservation(coordinator.data.reservations, reservation_id)
    if reservation is None:
        try:
            reservation = _find_reservation(
                await client.async_fetch_reservations(), reservation_id
            )
        except VisitorParkingError:
            reservation = None

    if reservation is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="reservation_not_available",
        )

    start_time_raw = reservation.get("start_time")
    start_time = (
        dt_util.parse_datetime(start_time_raw)
        if isinstance(start_time_raw, str)
        else None
    )
    if start_time is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="reservation_start_time_not_available",
        )
    start_utc = _as_utc(start_time)

    if end_time <= start_utc:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="end_time_must_be_after_start_time",
        )

    try:
        zone = await client.async_fetch_zone_end_time(int(start_utc.timestamp()))
    except VisitorParkingError:
        zone = None

    zone_end_str = zone.get("end_time") if zone else None
    if isinstance(zone_end_str, str):
        zone_end = dt_util.parse_datetime(zone_end_str)
        if zone_end is not None and end_time >= _as_utc(zone_end):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="end_time_must_be_before_zone_end_time",
            )

    current_end_raw = reservation.get("end_time")
    current_end = (
        dt_util.parse_datetime(current_end_raw)
        if isinstance(current_end_raw, str)
        else None
    )
    if current_end is not None and _as_utc(current_end).replace(
        microsecond=0
    ) == end_time.replace(microsecond=0):
        return

    try:
        await client.async_adjust_reservation_end_time(
            reservation_id=reservation_id,
            end_time=end_time,
        )
    except VisitorParkingError as err:
        _LOGGER.debug("Could not adjust reservation", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_adjust_reservation",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    await coordinator.async_request_refresh()


async def _async_create_favorite(hass: HomeAssistant, call: ServiceCall) -> None:
    """Create a favorite via the service call."""
    _entry_id, runtime_data = _get_runtime_data(hass, call)

    name = call.data["name"].strip()
    if not name:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_favorite_name",
        )

    license_plate = _normalize_license_plate(call.data["license_plate"])
    if not license_plate:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_license_plate",
        )

    coordinator = runtime_data.coordinator
    client = coordinator.client

    try:
        await client.async_create_favorite(
            license_plate=license_plate,
            name=name,
        )
    except VisitorParkingUnsupportedError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="action_not_supported",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err
    except VisitorParkingError as err:
        _LOGGER.debug("Could not create favorite", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_create_favorite",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    await coordinator.async_request_refresh()


async def _async_delete_favorite(hass: HomeAssistant, call: ServiceCall) -> None:
    """Delete a favorite via the service call."""
    _entry_id, runtime_data = _get_runtime_data(hass, call)

    coordinator = runtime_data.coordinator
    client = coordinator.client

    favorite_id = _normalize_identifier(call.data["favorite_id"], "favorite_id")

    if not client.supports_favorite_deletion:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="favorite_delete_not_supported",
        )

    try:
        await client.async_delete_favorite(favorite_id)
    except VisitorParkingError as err:
        _LOGGER.debug("Could not delete favorite", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_delete_favorite",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    await coordinator.async_request_refresh()


async def _async_update_favorite(hass: HomeAssistant, call: ServiceCall) -> None:
    """Update a favorite via the service call."""
    _entry_id, runtime_data = _get_runtime_data(hass, call)

    name = call.data["name"].strip()
    if not name:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_favorite_name",
        )

    license_plate = _normalize_license_plate(call.data["license_plate"])
    if not license_plate:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="missing_license_plate",
        )

    favorite_id = _normalize_identifier(call.data["favorite_id"], "favorite_id")

    coordinator = runtime_data.coordinator
    client = coordinator.client

    try:
        await client.async_update_favorite(
            favorite_id=favorite_id,
            license_plate=license_plate,
            name=name,
        )
    except VisitorParkingUnsupportedError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="action_not_supported",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err
    except VisitorParkingError as err:
        _LOGGER.debug("Could not update favorite", exc_info=err)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="could_not_update_favorite",
            translation_placeholders={"error": _error_for_user(err)},
        ) from err

    await coordinator.async_request_refresh()


async def async_register_services(hass: HomeAssistant) -> None:
    """Register services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_RESERVATION,
        partial(_async_create_reservation, hass),
        schema=SERVICE_CREATE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_RESERVATION,
        partial(_async_delete_reservation, hass),
        schema=SERVICE_DELETE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADJUST_RESERVATION_END_TIME,
        partial(_async_adjust_reservation_end_time, hass),
        schema=SERVICE_ADJUST_END_TIME_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_FAVORITE,
        partial(_async_create_favorite, hass),
        schema=SERVICE_CREATE_FAVORITE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_FAVORITE,
        partial(_async_delete_favorite, hass),
        schema=SERVICE_DELETE_FAVORITE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_FAVORITE,
        partial(_async_update_favorite, hass),
        schema=SERVICE_UPDATE_FAVORITE_SCHEMA,
    )
