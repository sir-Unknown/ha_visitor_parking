"""Config flow for Visitor Parking."""

from __future__ import annotations

import logging
from typing import Any, Self, cast

from aiohttp import CookieJar
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import dt as dt_util

from .api import VisitorParkingClient
from .const import (
    CONF_API_HOST,
    CONF_AUTO_END_ENABLED,
    CONF_DESCRIPTION,
    CONF_IDENTIFIER,
    CONF_MUNICIPALITY,
    CONF_PROVIDER,
    CONF_SCHEDULE,
    DEFAULT_WORKDAYS,
    DEFAULT_WORKING_FROM,
    DEFAULT_WORKING_TO,
    DOMAIN,
)
from .errors import (
    VisitorParkingAuthError,
    VisitorParkingConnectionError,
    VisitorParkingError,
)
from .provider_registry import (
    MunicipalityEntry,
    ProviderConfig,
    ProviderRegistry,
    async_get_registry,
    build_entry_title,
    build_unique_id,
    field_description,
    field_label,
    municipality_label,
    normalize_api_host,
    provider_label,
    unique_id_error_key,
)

_LOGGER = logging.getLogger(__name__)

_DAY_KEYS: tuple[tuple[int, str], ...] = (
    (0, "mon"),
    (1, "tue"),
    (2, "wed"),
    (3, "thu"),
    (4, "fri"),
    (5, "sat"),
    (6, "sun"),
)


def _normalize_time(value: str) -> str | None:
    """Normalize a time string to HH:MM."""
    if not value:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    parsed = dt_util.parse_time(normalized)
    if parsed is None and normalized.isdigit():
        hour = int(normalized)
        if 0 <= hour < 24:
            return f"{hour:02d}:00"
    if parsed is None:
        return None
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _validate_time_range(from_value: str | None, to_value: str | None) -> str | None:
    """Validate a time range.

    A range where `from_value` is after `to_value` is valid and means the range
    spans midnight (for example `09:00`–`02:00` continues into the next day).
    """
    if from_value is None or to_value is None:
        return "invalid_time"
    if from_value == to_value:
        return "invalid_time_range"
    return None


def _parse_schedule(value: object) -> dict[int, dict[str, object]] | None:
    """Parse a stored per-day schedule."""
    if not isinstance(value, dict):
        return None
    schedule: dict[int, dict[str, object]] = {}
    for raw_day, day_value in value.items():
        if isinstance(raw_day, int):
            day = raw_day
        elif isinstance(raw_day, str) and raw_day.isdigit():
            day = int(raw_day)
        else:
            continue

        if not 0 <= day <= 6:
            continue
        if not isinstance(day_value, dict):
            continue
        schedule[day] = day_value
    return schedule or None


def _zone_time_to_hhmm(value: object) -> str | None:
    """Convert a zone datetime string to local HH:MM."""
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    local = dt_util.as_local(parsed)
    return f"{local.hour:02d}:{local.minute:02d}"


class VisitorParkingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Visitor Parking."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._registry: ProviderRegistry | None = None
        self._selected_municipality: MunicipalityEntry | None = None
        self._selected_provider: ProviderConfig | None = None

    async def _async_registry(self) -> ProviderRegistry:
        """Return the cached provider registry."""
        if self._registry is None:
            self._registry = await async_get_registry()
        return self._registry

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return VisitorParkingOptionsFlowHandler(config_entry)

    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow is matching this flow."""
        if self.unique_id is None or other_flow.unique_id is None:
            return False
        return self.unique_id == other_flow.unique_id

    async def _async_get_account(
        self,
        *,
        provider: str,
        username: str | None = None,
        password: str | None = None,
        api_host: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        """Log in and fetch account data."""
        session = async_create_clientsession(
            self.hass,
            auto_cleanup=False,
            connector_owner=False,
            cookie_jar=CookieJar(),
        )
        client = VisitorParkingClient(
            provider=provider,
            session=session,
            username=username,
            password=password,
            api_host=api_host,
            identifier=identifier,
        )
        try:
            return await client.async_fetch_account()
        finally:
            await session.close()

    async def _municipality_options(self) -> dict[str, str]:
        registry = await self._async_registry()
        language = self.hass.config.language
        options = [
            (selection, municipality_label(entry, language))
            for selection, entry in registry.municipality_by_selection.items()
        ]
        options.sort(key=lambda item: item[1].casefold())
        return dict(options)

    async def _municipality_schema(
        self, user_input: dict[str, str] | None
    ) -> vol.Schema:
        defaults = user_input or {}
        options = await self._municipality_options()
        municipality_default = str(defaults.get(CONF_MUNICIPALITY, "")).strip()
        if municipality_default not in options:
            municipality_default = next(iter(options), "")
        return vol.Schema(
            {
                vol.Required(CONF_MUNICIPALITY, default=municipality_default): vol.In(
                    options
                )
            }
        )

    def _credentials_schema(
        self, provider: ProviderConfig, user_input: dict[str, Any] | None
    ) -> vol.Schema:
        """Build the credentials step schema."""
        defaults = user_input or {}
        fields: dict[vol.Marker, object] = {}
        for field in provider.fields:
            if not field.show or field.source != "user":
                continue
            default_value = str(defaults.get(field.key, "")).strip()
            marker: vol.Marker = (
                vol.Required(field.key, default=default_value)
                if field.required
                else vol.Optional(field.key, default=default_value)
            )
            fields[marker] = str
        return vol.Schema(fields)

    def _credentials_placeholders(self, provider: ProviderConfig) -> dict[str, str]:
        """Build translation placeholders for provider fields."""
        language = self.hass.config.language
        placeholders = {
            "provider_label": provider_label(provider, language),
        }
        for field in provider.fields:
            placeholders[f"{field.key}_label"] = field_label(field, language)
            placeholders[f"{field.key}_description"] = field_description(
                field, language
            )
        for key in (CONF_API_HOST, CONF_USERNAME, CONF_IDENTIFIER, CONF_PASSWORD):
            placeholders.setdefault(f"{key}_label", "")
            placeholders.setdefault(f"{key}_description", "")
        return placeholders

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Handle the municipality selection step."""
        if user_input is not None:
            selection = user_input[CONF_MUNICIPALITY]
            registry = await self._async_registry()
            if not (entry := registry.municipality_by_selection.get(selection)):
                return self.async_abort(reason="unknown")
            if not (provider := registry.providers.get(entry.provider)):
                return self.async_abort(reason="unknown")
            self._selected_municipality = entry
            self._selected_provider = provider
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="user",
            data_schema=await self._municipality_schema(user_input),
            errors={},
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the provider credentials step."""
        errors: dict[str, str] = {}
        provider = self._selected_provider
        municipality = self._selected_municipality
        if provider is None or municipality is None:
            return self.async_abort(reason="unknown")

        if user_input is not None:
            values: dict[str, Any] = {}
            for field in provider.fields:
                field_error: str | None = None
                if field.source == "municipality":
                    value = (
                        municipality.api_host if field.key == CONF_API_HOST else None
                    )
                else:
                    raw = user_input.get(field.key)
                    value = raw.strip() if isinstance(raw, str) else raw
                if field.validator == "api_host":
                    value = (
                        normalize_api_host(value) if isinstance(value, str) else None
                    )
                    if not value:
                        field_error = field.error_key or "invalid_host"
                if field.required and not value and field_error is None:
                    field_error = field.error_key or f"missing_{field.key}"
                if field_error is not None:
                    errors["base" if not field.show else field.key] = field_error
                values[field.key] = value

            if errors:
                return self.async_show_form(
                    step_id="credentials",
                    data_schema=self._credentials_schema(provider, user_input),
                    errors=errors,
                    description_placeholders=self._credentials_placeholders(provider),
                )

            try:
                account = await self._async_get_account(
                    provider=provider.provider,
                    username=values.get(CONF_USERNAME),
                    password=values.get(CONF_PASSWORD),
                    api_host=values.get(CONF_API_HOST),
                    identifier=values.get(CONF_IDENTIFIER),
                )
            except VisitorParkingAuthError:
                errors["base"] = "invalid_auth"
            except VisitorParkingConnectionError:
                errors["base"] = "cannot_connect"
            except VisitorParkingError:
                _LOGGER.exception("Unexpected error while fetching account data")
                errors["base"] = "unknown"
            else:
                unique_id = build_unique_id(
                    provider,
                    account=account,
                    values=values,
                )
                if unique_id is None:
                    _LOGGER.error("Account response did not include a valid id")
                    errors["base"] = unique_id_error_key(provider)
                    return self.async_show_form(
                        step_id="credentials",
                        data_schema=self._credentials_schema(provider, user_input),
                        errors=errors,
                        description_placeholders=self._credentials_placeholders(
                            provider
                        ),
                    )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                municipality_name = municipality_label(
                    municipality, self.hass.config.language
                )
                entry_data = {
                    CONF_PROVIDER: provider.provider,
                }
                for field in provider.fields:
                    value = values.get(field.key)
                    if value is not None:
                        entry_data[field.key] = value
                return self.async_create_entry(
                    title=build_entry_title(
                        provider,
                        account=account,
                        values=values,
                        municipality_name=municipality_name,
                    ),
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="credentials",
            data_schema=self._credentials_schema(provider, user_input),
            errors=errors,
            description_placeholders=self._credentials_placeholders(provider),
        )

    async def async_step_reauth(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication."""
        errors: dict[str, str] = {}

        reauth_entry = self._get_reauth_entry()
        provider_id = reauth_entry.data.get(CONF_PROVIDER)
        registry = await self._async_registry()
        provider = (
            registry.providers.get(provider_id)
            if isinstance(provider_id, str)
            else None
        )
        if provider is None:
            _LOGGER.error("Re-authentication entry is missing a provider")
            errors["base"] = "unknown"
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                errors=errors,
            )

        if user_input is not None:
            password = user_input[CONF_PASSWORD].strip()
            if not password:
                errors[CONF_PASSWORD] = "missing_password"
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                    errors=errors,
                )

            try:
                values: dict[str, Any] = {}
                missing = False
                for field in provider.fields:
                    if field.key == CONF_PASSWORD:
                        values[field.key] = password
                        continue
                    value = reauth_entry.data.get(field.key)
                    if field.required and (value is None or value == ""):
                        missing = True
                    values[field.key] = value
                if missing:
                    _LOGGER.error("Re-authentication entry is missing required data")
                    errors["base"] = "unknown"
                    return self.async_show_form(
                        step_id="reauth_confirm",
                        data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                        errors=errors,
                    )

                account = await self._async_get_account(
                    provider=provider.provider,
                    username=values.get(CONF_USERNAME),
                    password=values.get(CONF_PASSWORD),
                    api_host=values.get(CONF_API_HOST),
                    identifier=values.get(CONF_IDENTIFIER),
                )

                existing_unique_id = reauth_entry.unique_id
                expected_unique_id = build_unique_id(
                    provider,
                    account=account,
                    values=values,
                )
                if expected_unique_id is None:
                    _LOGGER.error(
                        "Account response did not include a valid id during re-auth"
                    )
                    errors["base"] = unique_id_error_key(provider)
                    return self.async_show_form(
                        step_id="reauth_confirm",
                        data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
                        errors=errors,
                    )
                if existing_unique_id and existing_unique_id != expected_unique_id:
                    return self.async_abort(reason="wrong_account")

                if not existing_unique_id:
                    self.hass.config_entries.async_update_entry(
                        reauth_entry, unique_id=expected_unique_id
                    )
            except VisitorParkingAuthError:
                errors["base"] = "invalid_auth"
            except VisitorParkingConnectionError:
                errors["base"] = "cannot_connect"
            except VisitorParkingError:
                _LOGGER.exception(
                    "Unexpected error while fetching account data during re-auth"
                )
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: password},
                )

        data_schema = vol.Schema({vol.Required(CONF_PASSWORD): str})

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=data_schema,
            errors=errors,
        )


class VisitorParkingOptionsFlowHandler(OptionsFlow):
    """Handle Visitor Parking options."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            description = user_input[CONF_DESCRIPTION].strip()
            if not description:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(defaults=user_input),
                    errors={"base": "description_required"},
                )

            auto_end_enabled = bool(user_input.get(CONF_AUTO_END_ENABLED, True))
            schedule_input = user_input.get(CONF_SCHEDULE, {})
            if not isinstance(schedule_input, dict):
                schedule_input = {}
            schedule: dict[str, dict[str, object]] = {}
            selected_days = 0
            for day, key in _DAY_KEYS:
                enabled = bool(schedule_input.get(f"{key}_enabled"))
                raw_from = schedule_input.get(f"{key}_from")
                raw_to = schedule_input.get(f"{key}_to")
                from_value = (
                    _normalize_time(raw_from) if isinstance(raw_from, str) else None
                )
                to_value = _normalize_time(raw_to) if isinstance(raw_to, str) else None
                if enabled:
                    selected_days += 1
                if enabled and (error := _validate_time_range(from_value, to_value)):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._schema(defaults=user_input),
                        errors={"base": error},
                    )

                schedule[str(day)] = {
                    "enabled": enabled,
                    "from": from_value if enabled else None,
                    "to": to_value if enabled else None,
                }

            if auto_end_enabled and selected_days == 0:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(defaults=user_input),
                    errors={"base": "no_workdays_selected"},
                )

            options_data = {
                **self._config_entry.options,
                CONF_DESCRIPTION: description,
                CONF_AUTO_END_ENABLED: auto_end_enabled,
                CONF_SCHEDULE: schedule,
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry, title=description
            )
            return self.async_create_entry(title="", data=options_data)

        return self.async_show_form(
            step_id="init", data_schema=self._schema(defaults=None)
        )

    def _schema(self, *, defaults: dict[str, Any] | None) -> vol.Schema:
        options = self._config_entry.options
        description = str(
            options.get(
                CONF_DESCRIPTION, self._config_entry.data.get(CONF_DESCRIPTION, "")
            )
        ).strip()
        auto_end_enabled = bool(options.get(CONF_AUTO_END_ENABLED, True))
        stored_schedule = _parse_schedule(options.get(CONF_SCHEDULE))
        base_from: str | None = None
        base_to: str | None = None
        if base_from is None or base_to is None:
            runtime_data = self.hass.data.get(DOMAIN, {}).get(
                self._config_entry.entry_id
            )
            coordinator = getattr(runtime_data, "coordinator", None)
            account = getattr(getattr(coordinator, "data", None), "account", None)
            zone = account.get("zone") if isinstance(account, dict) else None
            if base_from is None:
                base_from = _zone_time_to_hhmm(
                    zone.get("start_time") if isinstance(zone, dict) else None
                )
            if base_to is None:
                base_to = _zone_time_to_hhmm(
                    zone.get("end_time") if isinstance(zone, dict) else None
                )

        base_from = base_from or DEFAULT_WORKING_FROM
        base_to = base_to or DEFAULT_WORKING_TO

        schedule: dict[str | int, dict[str, object]] = cast(
            dict[str | int, dict[str, object]], stored_schedule or {}
        )
        defaults_map: dict[str, Any] = defaults or {}
        schedule_defaults = defaults_map.get(CONF_SCHEDULE, {})
        if not isinstance(schedule_defaults, dict):
            schedule_defaults = {}

        def _day_cfg(day: int, key: str) -> dict[str, object]:
            if day in schedule:
                raw = schedule[day]
            else:
                raw = schedule.get(str(day), {})
            if not isinstance(raw, dict):
                raw = {}
            enabled = bool(raw.get("enabled", day in DEFAULT_WORKDAYS))
            from_value = raw.get("from") if raw.get("from") is not None else base_from
            to_value = raw.get("to") if raw.get("to") is not None else base_to
            return {
                f"{key}_enabled": schedule_defaults.get(f"{key}_enabled", enabled),
                f"{key}_from": schedule_defaults.get(f"{key}_from", from_value),
                f"{key}_to": schedule_defaults.get(f"{key}_to", to_value),
            }

        day_schema: dict[vol.Marker, object] = {}
        for day, key in _DAY_KEYS:
            day_defaults = _day_cfg(day, key)
            day_schema[
                vol.Optional(f"{key}_enabled", default=day_defaults[f"{key}_enabled"])
            ] = bool
            day_schema[
                vol.Optional(f"{key}_from", default=day_defaults[f"{key}_from"])
            ] = str
            day_schema[vol.Optional(f"{key}_to", default=day_defaults[f"{key}_to"])] = (
                str
            )

        schema_data: dict[Any, object] = {
            vol.Required(
                CONF_DESCRIPTION,
                default=defaults_map.get(CONF_DESCRIPTION, description),
            ): str,
            vol.Required(
                CONF_AUTO_END_ENABLED,
                default=defaults_map.get(CONF_AUTO_END_ENABLED, auto_end_enabled),
            ): bool,
            vol.Required(CONF_SCHEDULE): section(
                vol.Schema(day_schema), {"collapsed": True}
            ),
        }
        return vol.Schema(schema_data)
