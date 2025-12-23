"""Schedule helpers for Visitor Parking."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, time
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCHEDULE,
    DEFAULT_WORKDAYS,
    DEFAULT_WORKING_FROM,
    DEFAULT_WORKING_TO,
)


def parse_time(value: object, *, default: str) -> time:
    """Parse a time from a string, using default when invalid."""
    if isinstance(value, str) and (parsed := dt_util.parse_time(value)):
        return parsed
    if parsed := dt_util.parse_time(default):
        return parsed
    return dt_util.parse_time("00:00")  # type: ignore[return-value]


def is_overnight(from_time: time, to_time: time) -> bool:
    """Return whether a schedule spans midnight."""
    return from_time > to_time


def _cfg_for_day(
    schedule: Mapping[str | int, Any], day: int
) -> Mapping[str, Any] | None:
    cfg = schedule.get(day)
    if cfg is None:
        cfg = schedule.get(str(day))
    return cfg if isinstance(cfg, Mapping) else None


def schedule_for_options(
    options: Mapping[str, Any],
    *,
    fallback_workdays: Collection[int] | None = None,
    fallback_from: str | None = None,
    fallback_to: str | None = None,
) -> dict[int, tuple[bool, time, time]]:
    """Return schedule mapping weekday -> (enabled, from, to)."""
    from_default = fallback_from or DEFAULT_WORKING_FROM
    to_default = fallback_to or DEFAULT_WORKING_TO
    default_from_time = parse_time(from_default, default=DEFAULT_WORKING_FROM)
    default_to_time = parse_time(to_default, default=DEFAULT_WORKING_TO)
    workdays = set(
        fallback_workdays if fallback_workdays is not None else DEFAULT_WORKDAYS
    )

    schedule_opt = options.get(CONF_SCHEDULE)
    schedule: dict[int, tuple[bool, time, time]] = {}

    if isinstance(schedule_opt, Mapping):
        for day in range(7):
            if (day_cfg := _cfg_for_day(schedule_opt, day)) is None:
                schedule[day] = (False, default_from_time, default_to_time)
                continue

            enabled = bool(day_cfg.get("enabled", False))
            from_time = parse_time(day_cfg.get("from"), default=from_default)
            to_time = parse_time(day_cfg.get("to"), default=to_default)
            schedule[day] = (enabled, from_time, to_time)
        return schedule

    for day in range(7):
        schedule[day] = (day in workdays, default_from_time, default_to_time)
    return schedule


def end_times(schedule: Mapping[int, tuple[bool, time, time]]) -> set[tuple[int, int]]:
    """Return the set of (hour, minute) end times for enabled schedule days."""
    return {
        (to_time.hour, to_time.minute)
        for enabled, _from_time, to_time in schedule.values()
        if enabled
    }


def scheduled_end_for_start(
    start_time: datetime, options: Mapping[str, Any]
) -> tuple[str, datetime] | None:
    """Return (working_to_hhmm, scheduled_end_utc) for start_time if applicable."""
    start_local = dt_util.as_local(start_time)
    weekday = start_local.weekday()
    prev = (weekday - 1) % 7
    start_clock = start_local.time().replace(second=0, microsecond=0)

    schedule = schedule_for_options(options)

    enabled_today, from_today, to_today = schedule[weekday]
    enabled_prev, from_prev, to_prev = schedule[prev]

    candidates: list[tuple[str, datetime]] = []

    if (
        enabled_today
        and not is_overnight(from_today, to_today)
        and start_clock >= to_today
    ):
        end_local = start_local.replace(
            hour=to_today.hour, minute=to_today.minute, second=0, microsecond=0
        )
        candidates.append(
            (
                f"{to_today.hour:02d}:{to_today.minute:02d}",
                dt_util.as_utc(end_local),
            )
        )

    active_from_today = from_today if enabled_today else None
    if (
        enabled_prev
        and is_overnight(from_prev, to_prev)
        and start_clock >= to_prev
        and active_from_today is not None
        and start_clock < active_from_today
    ):
        end_local = start_local.replace(
            hour=to_prev.hour, minute=to_prev.minute, second=0, microsecond=0
        )
        candidates.append(
            (
                f"{to_prev.hour:02d}:{to_prev.minute:02d}",
                dt_util.as_utc(end_local),
            )
        )

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])
