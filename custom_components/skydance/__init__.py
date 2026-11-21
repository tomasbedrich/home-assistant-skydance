"""A Home Assistant integration for communication with Skydance lighting Wi-Fi relay."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, async_get
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from skydance.network.session import Session
from skydance.protocol import (
    PORT,
    FrameError,
    GetNumberOfZonesCommand,
    GetNumberOfZonesResponse,
    GetZoneInfoCommand,
    GetZoneInfoResponse,
)

from .const import DOMAIN, MANUFACTURER, PLATFORMS

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)


@dataclass
class SkydanceRuntimeData:
    """Objects shared by the entities of a config entry."""

    session: Session
    coordinator: DataUpdateCoordinator[list[dict]]


SkydanceConfigEntry = ConfigEntry[SkydanceRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration (YAML configuration is not supported)."""
    return True


async def _async_discover_zones(session: Session) -> list[dict]:
    """Read the zone layout of a relay."""
    try:
        _LOGGER.debug("Getting number of zones")
        raw = await session.request(GetNumberOfZonesCommand)
        number_of_zones = GetNumberOfZonesResponse(raw).number

        zones = []
        for zone_num in range(1, number_of_zones + 1):
            _LOGGER.debug("Getting info about zone=%d", zone_num)
            raw = await session.request(partial(GetZoneInfoCommand, zone=zone_num))
            zone_info = GetZoneInfoResponse(raw)
            _LOGGER.debug(
                "Zone=%d has type=%s, name=%s",
                zone_num,
                zone_info.type,
                zone_info.name,
            )
            zones.append(
                {"num": zone_num, "name": zone_info.name, "type": zone_info.type}
            )
        return zones
    except (OSError, asyncio.TimeoutError, EOFError, FrameError) as err:
        raise UpdateFailed(f"unable to read zones: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: SkydanceConfigEntry) -> bool:
    """Set up Skydance from a config entry."""
    session = Session(entry.data["ip"], PORT)
    entry.async_on_unload(session.close)

    coordinator: DataUpdateCoordinator[list[dict]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=partial(_async_discover_zones, session),
        # do NOT update data at all - only after HA restart and on demand
    )
    # Raises ConfigEntryNotReady when the relay cannot be reached.
    await coordinator.async_config_entry_first_refresh()

    async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, entry.data["mac"])},
        name=f"{MANUFACTURER} Wi-Fi relay",  # TODO localize?
        manufacturer=MANUFACTURER,
    )

    entry.runtime_data = SkydanceRuntimeData(session=session, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SkydanceConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
