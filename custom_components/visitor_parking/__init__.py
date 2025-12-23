"""Integration for visitor parking permits and reservations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import logging
from pathlib import Path
from typing import Final

from aiohttp import ClientSession, CookieJar

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import VisitorParkingClient, normalize_identifier
from .const import (
    CONF_API_HOST,
    CONF_AUTO_END_ENABLED,
    CONF_IDENTIFIER,
    CONF_PROVIDER,
    DOMAIN,
)
from .coordinator import VisitorParkingCoordinator
from .errors import VisitorParkingError
from .schedule import (
    end_times as schedule_end_times,
    is_overnight,
    schedule_for_options,
)
from .services import async_register_services

PLATFORMS: tuple[str, ...] = ("sensor",)
_STORAGE_VERSION: Final = 1
_STORAGE_KEY: Final = f"{DOMAIN}.created_reservations"

_LOGGER = logging.getLogger(__name__)


class CreatedReservationsStore:
    """Persist reservation ids created by this integration."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, list[str]]] = Store(
            hass, _STORAGE_VERSION, f"{_STORAGE_KEY}.{entry_id}"
        )
        self._lock = asyncio.Lock()

    async def async_load(self) -> set[str]:
        """Load created reservation ids."""
        async with self._lock:
            if not (data := await self._store.async_load()):
                return set()
            raw_ids = data.get("reservation_ids", [])
            return {
                normalized
                for reservation_id in raw_ids
                if (normalized := normalize_identifier(reservation_id))
            }

    async def async_save(self, reservation_ids: Iterable[str]) -> None:
        """Save created reservation ids."""
        async with self._lock:
            ids = sorted(
                {
                    normalized
                    for reservation_id in reservation_ids
                    if (normalized := normalize_identifier(reservation_id))
                }
            )
            await self._store.async_save({"reservation_ids": ids})


@dataclass(slots=True)
class VisitorParkingRuntimeData:
    """Runtime data for visitor parking."""

    session: ClientSession
    coordinator: VisitorParkingCoordinator
    created_reservations_store: CreatedReservationsStore
    created_reservation_ids: set[str] = field(default_factory=set)
    created_reservations_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    prune_task: asyncio.Task[None] | None = None
    auto_end_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    auto_end_unsubs: list[Callable[[], None]] = field(default_factory=list)
    update_listener_unsub: Callable[[], None] | None = None


type VisitorParkingConfigEntry = ConfigEntry[VisitorParkingRuntimeData]


async def async_migrate_entry(_hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry."""
    _LOGGER.debug("Migrating from version %s:%s", entry.version, entry.minor_version)

    if entry.version > 1:
        return False

    return True


def _zone_hhmm(entry: VisitorParkingConfigEntry) -> tuple[str | None, str | None]:
    """Return zone start/end time (local) as HH:MM if available."""
    account = entry.runtime_data.coordinator.data.account
    zone = account.get("zone") if isinstance(account, dict) else None
    if not isinstance(zone, dict):
        return None, None

    def _to_hhmm(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        local = dt_util.as_local(parsed)
        return f"{local.hour:02d}:{local.minute:02d}"

    return _to_hhmm(zone.get("start_time")), _to_hhmm(zone.get("end_time"))


def _reservation_start_utc(value: object) -> datetime | None:
    """Parse reservation start time to UTC datetime."""
    if not isinstance(value, str):
        return None
    if not (parsed := dt_util.parse_datetime(value)):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(parsed)


def _last_scheduled_end_utc(
    now: datetime, schedule: dict[int, tuple[bool, time, time]]
) -> datetime | None:
    """Return the most recent schedule end time (UTC) that is <= now."""
    now_local = dt_util.as_local(now)
    candidates: list[datetime] = []
    for days_back in range(8):
        day_date = now_local.date() - timedelta(days=days_back)
        weekday = day_date.weekday()
        enabled, from_time, to_time = schedule[weekday]
        if not enabled:
            continue

        end_date = (
            day_date
            if not is_overnight(from_time, to_time)
            else day_date + timedelta(days=1)
        )
        end_local = datetime.combine(
            end_date,
            to_time,
            tzinfo=dt_util.DEFAULT_TIME_ZONE,
        ).replace(second=0, microsecond=0)
        end_utc = dt_util.as_utc(end_local)
        if end_utc <= now:
            candidates.append(end_utc)

    return max(candidates) if candidates else None


async def _async_end_active_reservations(
    entry: VisitorParkingConfigEntry, *, started_before: datetime | None = None
) -> None:
    runtime_data = entry.runtime_data
    async with runtime_data.auto_end_lock:
        coordinator = runtime_data.coordinator
        client = coordinator.client

        await coordinator.async_request_refresh()
        async with runtime_data.created_reservations_lock:
            created_ids = set(runtime_data.created_reservation_ids)

        if not created_ids:
            return

        reservation_ids: list[str] = []
        for reservation in coordinator.data.reservations:
            if not (reservation_id := normalize_identifier(reservation.get("id"))):
                continue
            if reservation_id not in created_ids:
                continue
            if started_before is not None:
                start_utc = _reservation_start_utc(reservation.get("start_time"))
                if start_utc is None or start_utc > started_before:
                    continue
            reservation_ids.append(reservation_id)

        if not reservation_ids:
            return

        try:
            await client.async_login()
        except VisitorParkingError:
            _LOGGER.exception("Failed to log in before ending reservations")
            return

        results = await asyncio.gather(
            *(
                client.async_delete_reservation(reservation_id)
                for reservation_id in reservation_ids
            ),
            return_exceptions=True,
        )
        ended = 0
        ended_ids: list[str] = []
        for reservation_id, result in zip(reservation_ids, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.error(
                    "Failed to end reservation %s", reservation_id, exc_info=result
                )
            else:
                ended += 1
                ended_ids.append(reservation_id)

        if ended:
            _LOGGER.info("Ended %s active reservation(s)", ended)
            async with runtime_data.created_reservations_lock:
                runtime_data.created_reservation_ids.difference_update(ended_ids)
                await runtime_data.created_reservations_store.async_save(
                    runtime_data.created_reservation_ids
                )
            await coordinator.async_request_refresh()


def _async_setup_auto_end(
    hass: HomeAssistant, entry: VisitorParkingConfigEntry
) -> None:
    runtime_data = entry.runtime_data
    for unsub in runtime_data.auto_end_unsubs:
        unsub()
    runtime_data.auto_end_unsubs.clear()

    options = entry.options
    if not bool(options.get(CONF_AUTO_END_ENABLED, True)):
        return

    zone_from, zone_to = _zone_hhmm(entry)
    schedule = schedule_for_options(
        options, fallback_from=zone_from, fallback_to=zone_to
    )
    if not (end_time_set := schedule_end_times(schedule)):
        return

    async def _async_handle(now: datetime) -> None:
        now_local = dt_util.as_local(now)
        now_time = now_local.time().replace(second=0, microsecond=0)
        weekday = now_local.weekday()
        prev = (weekday - 1) % 7

        enabled_today, from_today, to_today = schedule[weekday]
        enabled_prev, from_prev, to_prev = schedule[prev]

        should_end = False
        if (
            enabled_today
            and not is_overnight(from_today, to_today)
            and now_time == to_today
        ):
            should_end = True
        if enabled_prev and is_overnight(from_prev, to_prev) and now_time == to_prev:
            should_end = True

        if should_end:
            await _async_end_active_reservations(entry)

    for end_hour, end_minute in end_time_set:
        runtime_data.auto_end_unsubs.append(
            async_track_time_change(
                hass,
                _async_handle,
                hour=end_hour,
                minute=end_minute,
                second=0,
            )
        )

    now = dt_util.now()
    if (last_end := _last_scheduled_end_utc(now, schedule)) is not None:
        hass.async_create_task(
            _async_end_active_reservations(entry, started_before=last_end)
        )


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up Visitor Parking."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path="/visitor_parking",
                path=str(Path(__file__).parent / "frontend" / "dist"),
                cache_headers=False,
            )
        ]
    )
    add_extra_js_url(
        hass, "/visitor_parking/visitor-parking-active-reservation-card.js"
    )
    add_extra_js_url(hass, "/visitor_parking/visitor-parking-new-reservation-card.js")
    await async_register_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: VisitorParkingConfigEntry
) -> bool:
    """Set up Visitor Parking from a config entry."""
    session = async_create_clientsession(
        hass,
        auto_cleanup=False,
        connector_owner=False,
        cookie_jar=CookieJar(),
    )

    provider = entry.data[CONF_PROVIDER]
    client = VisitorParkingClient(
        provider=provider,
        session=session,
        username=entry.data.get(CONF_USERNAME),
        password=entry.data[CONF_PASSWORD],
        api_host=entry.data.get(CONF_API_HOST),
        identifier=entry.data.get(CONF_IDENTIFIER),
    )

    coordinator = VisitorParkingCoordinator(hass, client=client, config_entry=entry)
    refresh_ok = False
    try:
        await coordinator.async_config_entry_first_refresh()
        refresh_ok = True
    finally:
        if not refresh_ok:
            await session.close()

    created_reservations_store = CreatedReservationsStore(hass, entry.entry_id)
    created_reservation_ids = await created_reservations_store.async_load()
    active_ids = {
        reservation_id
        for reservation in coordinator.data.reservations
        if (reservation_id := normalize_identifier(reservation.get("id")))
    }
    created_reservation_ids.intersection_update(active_ids)
    await created_reservations_store.async_save(created_reservation_ids)

    runtime_data = VisitorParkingRuntimeData(
        session=session,
        coordinator=coordinator,
        created_reservations_store=created_reservations_store,
        created_reservation_ids=created_reservation_ids,
    )
    entry.runtime_data = runtime_data
    runtime_data.update_listener_unsub = entry.add_update_listener(
        _async_update_listener
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime_data

    @callback
    def _async_prune_created_reservations() -> None:
        if (prune_task := runtime_data.prune_task) and not prune_task.done():
            return

        async def _async_prune() -> None:
            await asyncio.sleep(1)
            active_ids = {
                reservation_id
                for reservation in runtime_data.coordinator.data.reservations
                if (reservation_id := normalize_identifier(reservation.get("id")))
            }
            async with runtime_data.created_reservations_lock:
                if runtime_data.created_reservation_ids.issubset(active_ids):
                    return
                runtime_data.created_reservation_ids.intersection_update(active_ids)
                await runtime_data.created_reservations_store.async_save(
                    runtime_data.created_reservation_ids
                )

        runtime_data.prune_task = hass.async_create_task(_async_prune())

        def _async_clear_prune_task(_task: asyncio.Task[None]) -> None:
            runtime_data.prune_task = None

        runtime_data.prune_task.add_done_callback(_async_clear_prune_task)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_prune_created_reservations)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_setup_auto_end(hass, entry)
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: VisitorParkingConfigEntry
) -> None:
    """Handle options updates."""
    _async_setup_auto_end(hass, entry)


async def async_unload_entry(
    hass: HomeAssistant, entry: VisitorParkingConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime_data = entry.runtime_data
        if runtime_data.update_listener_unsub:
            runtime_data.update_listener_unsub()
        runtime_data.update_listener_unsub = None

        for unsub in runtime_data.auto_end_unsubs:
            unsub()
        runtime_data.auto_end_unsubs.clear()

        if (prune_task := runtime_data.prune_task) and not prune_task.done():
            prune_task.cancel()

        await runtime_data.session.close()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
