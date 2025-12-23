"""Tests for the visitor parking options flow."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.data_entry_flow import section

from custom_components.visitor_parking.config_flow import (
    VisitorParkingOptionsFlowHandler,
)
from custom_components.visitor_parking.const import (
    CONF_AUTO_END_ENABLED,
    CONF_DESCRIPTION,
    CONF_SCHEDULE,
)


def _build_handler() -> VisitorParkingOptionsFlowHandler:
    """Return an options flow handler with stub config entry and hass."""
    entry = SimpleNamespace(entry_id="entry-1", options={}, data={})
    handler = VisitorParkingOptionsFlowHandler(entry)
    handler.hass = SimpleNamespace(data={})
    return handler


def test_options_schema_uses_collapsed_schedule_section() -> None:
    """Verify schedule fields are grouped into a collapsed section."""
    handler = _build_handler()
    schema = handler._schema(defaults=None)

    schedule_section = None
    for key, value in schema.schema.items():
        if str(key) == CONF_SCHEDULE:
            schedule_section = value
            break

    assert isinstance(schedule_section, section)
    assert schedule_section.options["collapsed"] is True


def test_options_schema_accepts_schedule_input() -> None:
    """Ensure the options schema accepts schedule updates."""
    handler = _build_handler()
    schema = handler._schema(defaults=None)

    validated = schema(
        {
            CONF_DESCRIPTION: "Visitor parking",
            CONF_AUTO_END_ENABLED: True,
            CONF_SCHEDULE: {},
        }
    )

    assert CONF_SCHEDULE in validated
