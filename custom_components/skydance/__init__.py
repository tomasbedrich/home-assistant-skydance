"""A Home Assistant integration for communication with Skydance lighting WiFi relay."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from skydance.controller import DEFAULT_PORT, Controller

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = ["light"]


async def async_setup(hass, config):
    """Set up the Skydance platform."""
    hass.data.setdefault(DOMAIN, {})
    # we don't support YAML configuration, therefore just return True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up a Controller from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    ip = entry.data["host"]
    _LOGGER.info("Opening connection to %s:%d", ip, DEFAULT_PORT)
    # TODO the streams should probably be handled somehow more robust
    reader, writer = await asyncio.open_connection(ip, DEFAULT_PORT)
    controller = Controller(reader, writer)
    hass.data[DOMAIN][entry.entry_id] = controller

    # # https://developers.home-assistant.io/docs/device_registry_index
    # # Components are also able to register devices in the case that there are no entities representing them.
    # # An example is a hub that communicates with the lights.
    # device_registry = await dr.async_get_registry(hass)
    # device_registry.async_get_or_create(
    #     config_entry_id=entry.entry_id,
    #     identifiers={(DOMAIN, ip)},
    #     name=f"{MANUFACTURER} WiFi relay {ip}",
    #     manufacturer=MANUFACTURER,
    # )

    for component in PLATFORMS:
        hass.async_create_task(hass.config_entries.async_forward_entry_setup(entry, component))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        _LOGGER.info("Closing connection")
        controller = hass.data[DOMAIN][entry.entry_id]
        controller.writer.close()
        hass.data[DOMAIN].pop(entry.entry_id)
        await controller.writer.wait_closed()

    return unload_ok
