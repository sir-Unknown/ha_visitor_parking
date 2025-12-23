"""Normalize provider data to integration-wide keys."""

from __future__ import annotations

from typing import Any, Final

from .const import PROVIDER_DVSPORTAL, PROVIDER_THE_HAGUE

ACCOUNT_BASE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "debit_minutes": ("debit_minutes",),
    "api_host": ("api_host",),
    "identifier": ("identifier",),
    "zone": ("zone",),
}

ACCOUNT_PROVIDER_ALIASES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    PROVIDER_DVSPORTAL: {
        "debit_minutes": ("balance",),
    },
}

ZONE_BASE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "name": ("name",),
    "start_time": ("start_time",),
    "end_time": ("end_time",),
}

ZONE_PROVIDER_ALIASES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    PROVIDER_THE_HAGUE: {
        "name": ("zone_name", "zoneName"),
        "start_time": ("zone_start_time", "zoneStartTime"),
        "end_time": ("zone_end_time", "zoneEndTime"),
    },
}

RESERVATION_BASE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "id": ("id",),
    "license_plate": ("license_plate",),
    "name": ("name",),
    "start_time": ("start_time",),
    "end_time": ("end_time",),
    "units": ("units",),
    "cost": ("cost",),
}

RESERVATION_PROVIDER_ALIASES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    PROVIDER_THE_HAGUE: {
        "id": ("reservation_id", "reservationId", "ReservationID", "ReservationId"),
        "license_plate": ("licensePlate", "plate"),
        "name": ("label",),
        "start_time": ("valid_from", "validFrom", "start"),
        "end_time": ("valid_until", "validUntil", "end"),
        "units": ("minutes", "duration"),
        "cost": ("price", "amount"),
    },
}

FAVORITE_BASE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "id": ("id",),
    "license_plate": ("license_plate",),
    "name": ("name",),
}

FAVORITE_PROVIDER_ALIASES: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    PROVIDER_THE_HAGUE: {
        "id": ("favorite_id", "favoriteId"),
        "license_plate": ("licensePlate", "plate"),
        "name": ("label",),
    },
}


def _normalize_mapping(
    data: dict[str, Any], aliases: dict[str, tuple[str, ...]]
) -> dict[str, Any]:
    """Apply alias mappings to a data payload."""
    normalized = dict(data)
    for canonical, keys in aliases.items():
        if normalized.get(canonical) is not None:
            continue
        for key in keys:
            if key in data and data.get(key) is not None:
                normalized[canonical] = data.get(key)
                break
    return normalized


def _aliases_for_provider(
    base: dict[str, tuple[str, ...]],
    provider_aliases: dict[str, dict[str, tuple[str, ...]]],
    provider: str,
) -> dict[str, tuple[str, ...]]:
    """Merge base aliases with provider-specific aliases."""
    if provider not in provider_aliases:
        return base
    merged: dict[str, tuple[str, ...]] = {}
    for key, base_values in base.items():
        extras = provider_aliases[provider].get(key, ())
        merged[key] = (*base_values, *extras)
    return merged


def normalize_account_data(account: dict[str, Any], provider: str) -> dict[str, Any]:
    """Normalize account fields to integration-wide keys."""
    aliases = _aliases_for_provider(
        ACCOUNT_BASE_ALIASES, ACCOUNT_PROVIDER_ALIASES, provider
    )
    normalized = _normalize_mapping(account, aliases)
    zone_value = normalized.get("zone")
    zone_aliases = _aliases_for_provider(
        ZONE_BASE_ALIASES, ZONE_PROVIDER_ALIASES, provider
    )
    if isinstance(zone_value, dict):
        normalized["zone"] = _normalize_mapping(zone_value, zone_aliases)
    else:
        zone_candidate: dict[str, Any] = {}
        for field, keys in zone_aliases.items():
            for key in keys:
                if key in normalized and normalized.get(key) is not None:
                    zone_candidate[field] = normalized.get(key)
                    break
        if zone_candidate:
            normalized["zone"] = zone_candidate
    return normalized


def normalize_reservation_data(
    reservation: dict[str, Any], provider: str
) -> dict[str, Any]:
    """Normalize reservation fields to integration-wide keys."""
    aliases = _aliases_for_provider(
        RESERVATION_BASE_ALIASES, RESERVATION_PROVIDER_ALIASES, provider
    )
    return _normalize_mapping(reservation, aliases)


def normalize_favorite_data(favorite: dict[str, Any], provider: str) -> dict[str, Any]:
    """Normalize favorite fields to integration-wide keys."""
    aliases = _aliases_for_provider(
        FAVORITE_BASE_ALIASES, FAVORITE_PROVIDER_ALIASES, provider
    )
    return _normalize_mapping(favorite, aliases)


def normalize_reservations(
    reservations: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    """Normalize reservation entries."""
    return [
        normalize_reservation_data(reservation, provider)
        for reservation in reservations
        if isinstance(reservation, dict)
    ]


def normalize_favorites(
    favorites: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    """Normalize favorite entries."""
    return [
        normalize_favorite_data(favorite, provider)
        for favorite in favorites
        if isinstance(favorite, dict)
    ]
