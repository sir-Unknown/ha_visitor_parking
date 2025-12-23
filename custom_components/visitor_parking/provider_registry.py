"""Provider registry and municipality metadata."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.yaml import load_yaml

from .const import CONF_IDENTIFIER

_LOGGER = logging.getLogger(__name__)

_MUNICIPALITIES_PATH = Path(__file__).with_name("municipalities.yaml")

_SOURCE_USER = "user"

_UNIQUE_ID_ACCOUNT = "account_id"
_UNIQUE_ID_IDENTIFIER = "identifier"


@dataclass(frozen=True, slots=True)
class ProviderField:
    """Describe a provider field."""

    key: str
    required: bool
    source: str
    show: bool
    validator: str | None
    error_key: str | None
    label_translations: dict[str, str]
    description_translations: dict[str, str]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Describe provider configuration."""

    provider: str
    label: str
    label_translations: dict[str, str]
    unique_id_strategy: str
    fields: tuple[ProviderField, ...]


@dataclass(frozen=True, slots=True)
class MunicipalityEntry:
    """Describe a municipality choice."""

    name: str
    name_translations: dict[str, str]
    provider: str
    api_host: str | None
    selection: str


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """Loaded provider registry data."""

    providers: dict[str, ProviderConfig]
    municipalities: tuple[MunicipalityEntry, ...]
    municipality_by_selection: dict[str, MunicipalityEntry]


def _normalize_text(value: str) -> str:
    """Normalize text values from YAML."""
    return value.strip()


def _normalize_language(value: str) -> str:
    """Normalize language tags for matching."""
    return value.replace("_", "-").casefold().strip()


def _parse_translations(value: object) -> dict[str, str]:
    """Parse a translation mapping from YAML."""
    if not isinstance(value, dict):
        return {}
    translations: dict[str, str] = {}
    for lang, text in value.items():
        if not isinstance(lang, str) or not isinstance(text, str):
            continue
        lang_key = _normalize_language(lang)
        text_value = _normalize_text(text)
        if not lang_key or not text_value:
            continue
        translations[lang_key] = text_value
    return translations


def _parse_provider_fields(value: object) -> tuple[ProviderField, ...]:
    """Parse provider field definitions from YAML."""
    if not isinstance(value, list):
        return tuple()
    results: list[ProviderField] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        required = bool(entry.get("required", True))
        source = str(entry.get("source", _SOURCE_USER)).strip() or _SOURCE_USER
        show = bool(entry.get("show", True))
        validator = entry.get("validator")
        error_key = entry.get("error_key")
        label_translations = _parse_translations(entry.get("label_translations"))
        description_translations = _parse_translations(
            entry.get("description_translations")
        )
        label = entry.get("label")
        if isinstance(label, str) and label.strip():
            label_translations.setdefault("default", label.strip())
        description = entry.get("description")
        if isinstance(description, str) and description.strip():
            description_translations.setdefault("default", description.strip())
        results.append(
            ProviderField(
                key=key.strip(),
                required=required,
                source=source,
                show=show,
                validator=validator if isinstance(validator, str) else None,
                error_key=error_key if isinstance(error_key, str) else None,
                label_translations=label_translations,
                description_translations=description_translations,
            )
        )
    return tuple(results)


def _parse_providers(value: object) -> dict[str, ProviderConfig]:
    """Parse provider configuration from YAML."""
    if not isinstance(value, dict):
        return {}
    providers: dict[str, ProviderConfig] = {}
    for provider, data in value.items():
        if not isinstance(provider, str) or not isinstance(data, dict):
            continue
        label = data.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        label_translations = _parse_translations(data.get("label_translations"))
        label_translations.setdefault("default", label.strip())
        unique_id_strategy = data.get("unique_id_strategy")
        if not isinstance(unique_id_strategy, str):
            continue
        fields = _parse_provider_fields(data.get("fields"))
        providers[provider.strip()] = ProviderConfig(
            provider=provider.strip(),
            label=label.strip(),
            label_translations=label_translations,
            unique_id_strategy=unique_id_strategy.strip(),
            fields=fields,
        )
    return providers


def _parse_municipalities(value: object) -> tuple[MunicipalityEntry, ...]:
    """Parse municipality entries from YAML."""
    if not isinstance(value, list):
        return tuple()
    results: list[MunicipalityEntry] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        provider = entry.get("provider")
        api_host = entry.get("api_host")
        if not isinstance(name, str) or not isinstance(provider, str):
            continue
        name_value = _normalize_text(name)
        provider_value = _normalize_text(provider)
        if not name_value or not provider_value:
            continue
        api_host_value = (
            _normalize_text(api_host) if isinstance(api_host, str) else None
        )
        name_translations = _parse_translations(entry.get("name_translations"))
        selection = api_host_value if api_host_value else provider_value
        results.append(
            MunicipalityEntry(
                name=name_value,
                name_translations=name_translations,
                provider=provider_value,
                api_host=api_host_value,
                selection=selection,
            )
        )
    return tuple(results)


def _load_registry() -> ProviderRegistry:
    """Load the provider registry from YAML."""
    try:
        data = load_yaml(str(_MUNICIPALITIES_PATH))
    except (FileNotFoundError, HomeAssistantError) as err:
        _LOGGER.error("Failed to load municipality registry file: %s", err)
        return ProviderRegistry(
            providers={}, municipalities=tuple(), municipality_by_selection={}
        )

    if not isinstance(data, dict):
        _LOGGER.error("Municipality registry file is not a mapping")
        return ProviderRegistry(
            providers={}, municipalities=tuple(), municipality_by_selection={}
        )

    providers = _parse_providers(data.get("providers"))
    municipalities = _parse_municipalities(data.get("municipalities"))
    if not providers:
        _LOGGER.error("Municipality registry file has no providers")
    if not municipalities:
        _LOGGER.error("Municipality registry file has no municipalities")
    municipality_by_selection = {entry.selection: entry for entry in municipalities}
    return ProviderRegistry(
        providers=providers,
        municipalities=municipalities,
        municipality_by_selection=municipality_by_selection,
    )


_REGISTRY: ProviderRegistry | None = None
_REGISTRY_LOCK = asyncio.Lock()


async def async_get_registry() -> ProviderRegistry:
    """Load the provider registry off the event loop and cache it."""
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    async with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = await asyncio.to_thread(_load_registry)
    return _REGISTRY


def _translated_text(translations: dict[str, str], language: str) -> str | None:
    """Return the translated text for a language."""
    normalized = _normalize_language(language)
    if normalized in translations:
        return translations[normalized]
    if "-" in normalized:
        base = normalized.split("-", 1)[0]
        if base in translations:
            return translations[base]
    return translations.get("default")


def municipality_label(entry: MunicipalityEntry, language: str) -> str:
    """Return the localized municipality label."""
    return _translated_text(entry.name_translations, language) or entry.name


def provider_label(provider: ProviderConfig, language: str) -> str:
    """Return the localized provider label."""
    return _translated_text(provider.label_translations, language) or provider.label


def field_label(field: ProviderField, language: str) -> str:
    """Return the localized field label."""
    return _translated_text(field.label_translations, language) or field.key


def field_description(field: ProviderField, language: str) -> str:
    """Return the localized field description."""
    return _translated_text(field.description_translations, language) or ""


def normalize_api_host(value: str | None) -> str | None:
    """Normalize an API host by stripping scheme and path."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    for prefix in ("https://", "http://"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break

    if "/" in stripped:
        stripped = stripped.split("/", 1)[0]

    return stripped or None


def account_id_from_account(account: object) -> str | None:
    """Return the account id as a string, if available."""
    if not isinstance(account, dict):
        return None
    account_id = account.get("id")
    if isinstance(account_id, int):
        return str(account_id)
    if isinstance(account_id, str):
        trimmed = account_id.strip()
        if not trimmed or trimmed.casefold() == "none":
            return None
        return trimmed
    return None


def build_unique_id(
    provider: ProviderConfig,
    *,
    account: dict[str, Any],
    values: dict[str, Any],
) -> str | None:
    """Build the unique id for a provider."""
    if provider.unique_id_strategy == _UNIQUE_ID_ACCOUNT:
        if account_id := account_id_from_account(account):
            return f"{provider.provider}:{account_id}"
        return None
    if provider.unique_id_strategy == _UNIQUE_ID_IDENTIFIER:
        identifier = values.get(CONF_IDENTIFIER)
        if isinstance(identifier, str) and identifier.strip():
            return f"{provider.provider}:{identifier.strip()}"
        return None
    return None


def unique_id_error_key(provider: ProviderConfig) -> str:
    """Return the error key to use when unique id generation fails."""
    if provider.unique_id_strategy == _UNIQUE_ID_IDENTIFIER:
        return "missing_identifier"
    return "missing_account_id"


def build_entry_title(
    provider: ProviderConfig,
    *,
    account: dict[str, Any],
    values: dict[str, Any],
    municipality_name: str,
) -> str:
    """Build a title for a config entry."""
    if provider.unique_id_strategy == _UNIQUE_ID_ACCOUNT:
        account_id = account_id_from_account(account) or "unknown"
        return f"{municipality_name} ({account_id})"
    if provider.unique_id_strategy == _UNIQUE_ID_IDENTIFIER:
        identifier = values.get(CONF_IDENTIFIER)
        if isinstance(identifier, str) and identifier.strip():
            title_value = identifier.strip()
        else:
            title_identifier = account.get(CONF_IDENTIFIER)
            title_value = (
                title_identifier if isinstance(title_identifier, str) else None
            )
        return f"{municipality_name} ({title_value or 'unknown'})"
    return municipality_name
