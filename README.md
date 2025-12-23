# Visitor Parking (Home Assistant custom integration)

This repository contains a Home Assistant custom integration that manages visitor parking reservations via:

- Parkeren Den Haag (via `pythehagueparking`)
- DVSPortal (via `dvsportal`)

## Features

- Config flow (UI) to select a municipality and enter credentials
- Options flow to configure auto-end and your schedule
- Data-driven municipality registry in `custom_components/visitor_parking/municipalities.yaml`
- Sensors:
  - `sensor.visitor_parking_<id>_account` (provider details in attributes)
  - `sensor.visitor_parking_<id>_reservations` (reservation count + list in attributes)
  - `sensor.visitor_parking_<id>_favorites` (favorites count + list in attributes)
- Services to create/delete reservations and manage favorites
- Lovelace custom cards (auto-loaded by the integration):
  - Active reservations card (end reservation)
  - New reservation card (favorites dropdown + create favorite)

## Installation (manual)

1. Copy `custom_components/visitor_parking` into your Home Assistant config folder under `custom_components/`.
2. Restart Home Assistant.
3. Go to **Settings** -> **Devices & services** -> **Add integration** -> **Visitor Parking**.

## Configuration

During setup you will be asked to select your municipality and enter credentials:

- **Den Haag** (Parkeren Den Haag): registration number and pin code
- **DVSPortal** municipalities: registration number and pin code

After setup, open the integration options (gear icon) to configure:

- A required `description` (for your own reference)
- Whether reservations created by this integration should be automatically ended
- Your schedule (per weekday)

To add or edit municipalities, update `custom_components/visitor_parking/municipalities.yaml`.

## Services

### `visitor_parking.create_reservation`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `license_plate`: License plate (required)
- `name`: Optional label
- `start_time`: ISO datetime (optional). If omitted, the reservation starts now.
- `start_time_entity_id`: `datetime` entity ID (optional). Alternative for `start_time`.
- `end_time`: ISO datetime (optional). If omitted, the integration uses provider defaults when available.
- `end_time_entity_id`: `datetime` entity ID (optional). Alternative for `end_time`.

### `visitor_parking.delete_reservation`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `reservation_id`: Reservation id (required)

### `visitor_parking.create_favorite`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `license_plate`: License plate (required)
- `name`: Name (required)

### `visitor_parking.delete_favorite`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `favorite_id`: Favorite id (required)

Note: DVSPortal does not support deleting favorites.

### `visitor_parking.update_favorite`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `favorite_id`: Favorite id (required)
- `license_plate`: License plate (required)
- `name`: Name (required)

### `visitor_parking.adjust_reservation_end_time`

- `config_entry_id`: Optional. Required when you have multiple entries configured
- `reservation_id`: Reservation id (required)
- `end_time`: ISO datetime (required)

## Provider notes

- DVSPortal does not support adjusting reservation end times or deleting favorites.
- Parkeren Den Haag uses your account zone settings when determining default end times.
- Parkeren Den Haag website: https://parkerendenhaag.denhaag.nl

## Not working

- Maastricht — https://mijn.2park.nl/login
- Amstelveen — https://mijn.2park.nl/login
- Amsterdam

## Lovelace cards

The integration serves and auto-loads the card JavaScript files, so you normally do not need to add a Lovelace resource manually.

### Active reservations card

```yaml
type: custom:visitor-parking-card
config_entry_id: <entry_id> # optional, omit to show reservations from all services
title: Visitor parking
```

### New reservation card

```yaml
type: custom:visitor-parking-new-reservation-card
config_entry_id: <entry_id> # optional, shows a service picker when multiple
title: New reservation
```

## Removal

1. Go to **Settings** -> **Devices & services**.
2. Select **Visitor Parking**.
3. Use the overflow menu (three dots) -> **Delete**.
