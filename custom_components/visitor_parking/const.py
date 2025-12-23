"""Constants for the Visitor Parking integration."""

from __future__ import annotations

DOMAIN = "visitor_parking"

PROVIDER_THE_HAGUE = "the_hague"
PROVIDER_DVSPORTAL = "dvsportal"

CONF_PROVIDER = "provider"
CONF_MUNICIPALITY = "municipality"
CONF_API_HOST = "api_host"
CONF_IDENTIFIER = "identifier"
CONF_DESCRIPTION = "description"
CONF_AUTO_END_ENABLED = "auto_end_enabled"
CONF_SCHEDULE = "schedule"

DEFAULT_WORKDAYS: set[int] = {0, 1, 2, 3, 4}  # Mon-Fri
DEFAULT_WORKING_FROM = "09:00"
DEFAULT_WORKING_TO = "18:00"

SERVICE_CREATE_RESERVATION = "create_reservation"
SERVICE_DELETE_RESERVATION = "delete_reservation"
SERVICE_ADJUST_RESERVATION_END_TIME = "adjust_reservation_end_time"
SERVICE_CREATE_FAVORITE = "create_favorite"
SERVICE_DELETE_FAVORITE = "delete_favorite"
SERVICE_UPDATE_FAVORITE = "update_favorite"
