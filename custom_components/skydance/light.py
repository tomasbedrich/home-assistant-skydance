import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    LightEntity,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR_TEMP,
    ATTR_COLOR_TEMP,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from skydance.network.session import Session
from skydance.protocol import (
    State,
    GetNumberOfZonesCommand,
    GetNumberOfZonesResponse,
    GetZoneNameCommand,
    GetZoneNameResponse,
    PORT,
    PowerOnCommand,
    PowerOffCommand,
    TemperatureCommand,
    BrightnessCommand,
)
from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_devices):
    session = Session(entry.data["ip"], PORT)
    state = State()
    hass.data[DOMAIN][entry.entry_id] = {
        "session": session,
        "state": state,
    }

    _LOGGER.info("Getting number of zones")
    cmd = GetNumberOfZonesCommand(state).raw
    await session.write(cmd)
    state.increment_frame_number()
    res = await session.read(64)
    number_of_zones = GetNumberOfZonesResponse(res).number

    new_devices = []
    for zone_num in range(1, number_of_zones + 1):
        _LOGGER.info("Getting name of zone=%d", zone_num)
        cmd = GetZoneNameCommand(state, zone=zone_num).raw
        await session.write(cmd)
        state.increment_frame_number()
        res = await session.read(64)
        zone_name = GetZoneNameResponse(res).name
        _LOGGER.debug("Zone=%d has name=%s", zone_num, zone_name)
        device = Zone(entry, session, state, zone_num, zone_name)
        new_devices.append(device)

    if new_devices:
        async_add_devices(new_devices)


async def async_unload_entry(hass, entry):
    session = hass.data[DOMAIN].pop(entry.entry_id)["session"]
    await session.close()


class Zone(LightEntity, RestoreEntity):
    supported_features = SUPPORT_BRIGHTNESS | SUPPORT_COLOR_TEMP

    def __init__(
        self,
        entry: ConfigEntry,
        session: Session,
        state: State,
        zone_num: int,
        zone_name: str,
    ):
        self._entry = entry
        self._session = session
        self._state = state
        self._zone_num = zone_num
        self._zone_name = zone_name

        self._is_on = None
        self._brightness = None
        self._color_temp = None

    @property
    def name(self):
        return self._zone_name

    @property
    def unique_id(self):
        return "-".join(
            [DOMAIN, self._entry.data["mac"].replace(":", ""), str(self._zone_num)]
        )

    @property
    def device_info(self):
        """Information about this entity/device."""
        # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            # If desired, the name for the device could be different to the entity
            # TODO add via_device - controller?
            "manufacturer": MANUFACTURER,
            "name": self.name,
        }

    @property
    def assumed_state(self):
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state:
            self._is_on = last_state.state == STATE_ON
            self._brightness = last_state.attributes.get("brightness")
            self._color_temp = last_state.attributes.get("color_temp")

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def color_temp(self):
        return self._color_temp

    async def async_turn_on(self, **kwargs):
        # Only execute what is necessary, nothing else
        tasks = []
        if not self.is_on:
            tasks.append(self._turn_on())
        if ATTR_BRIGHTNESS in kwargs:
            tasks.append(self._set_brightness(kwargs[ATTR_BRIGHTNESS]))
        if ATTR_COLOR_TEMP in kwargs:
            tasks.append(self._set_color_temp(kwargs[ATTR_COLOR_TEMP]))
        for i, task in enumerate(tasks):
            if i != 0:
                # FIXME do somehow better
                await asyncio.sleep(0.25)
            await task

    async def _turn_on(self):
        _LOGGER.debug("Powering on zone=%s", self.unique_id)
        cmd = PowerOnCommand(self._state, zone=self._zone_num).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        self._is_on = True

    async def _set_brightness(self, brightness):
        cmd = BrightnessCommand(
            self._state, zone=self._zone_num, brightness=brightness
        ).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        self._brightness = brightness

    async def _set_color_temp(self, color_temp):
        temperature_byte = int(
            255
            - 255
            * ((color_temp - self.min_mireds) / (self.max_mireds - self.min_mireds))
        )
        cmd = TemperatureCommand(
            self._state, zone=self._zone_num, temperature=temperature_byte
        ).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        self._color_temp = color_temp

    async def async_turn_off(self, **kwargs):
        _LOGGER.debug("Powering off zone=%s", self.unique_id)
        cmd = PowerOffCommand(self._state, zone=self._zone_num).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        self._is_on = False

    def turn_on(self, **kwargs: Any):
        # we do not support non-async API
        return None

    def turn_off(self, **kwargs: Any):
        # we do not support non-async API
        return None
