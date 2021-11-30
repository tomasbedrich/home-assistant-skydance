import asyncio
import logging
from datetime import timedelta

from homeassistant.components.light import (
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    COLOR_MODE_ONOFF,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_COLOR_TEMP,
    COLOR_MODE_RGBW,
    COLOR_MODE_RGB,
    ATTR_RGBW_COLOR,
    ATTR_RGB_COLOR,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import UpdateFailed, DataUpdateCoordinator, CoordinatorEntity

from skydance.enum import ZoneType
from skydance.network.session import Session
from skydance.protocol import (
    State,
    GetNumberOfZonesCommand,
    GetNumberOfZonesResponse,
    GetZoneInfoCommand,
    GetZoneInfoResponse,
    PORT,
    PowerOnCommand,
    PowerOffCommand,
    TemperatureCommand,
    BrightnessCommand,
    PingCommand,
    RGBWCommand,
)
from .const import DOMAIN, MANUFACTURER
from .session import SequentialWriterSession

_LOGGER = logging.getLogger(__name__)

# TODO this is a pattern - create some kind of wrapper around request-response protocol:
# await self._session.write(cmd)
# self._state.increment_frame_number()
# _ = await self._session.read(64)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    session = SequentialWriterSession(entry.data["ip"], PORT)
    state = State()

    try:
        cmd = PingCommand(state).raw
        await asyncio.wait_for(session.write(cmd), timeout=5)
        state.increment_frame_number()
        _ = await session.read(64)
    except (asyncio.TimeoutError, IOError) as e:
        raise ConfigEntryNotReady from e

    async def async_update():
        try:
            _LOGGER.info("Getting number of zones")
            cmd = GetNumberOfZonesCommand(state).raw
            await session.write(cmd)
            state.increment_frame_number()
            res = await session.read(64)
            number_of_zones = GetNumberOfZonesResponse(res).number

            zones = []
            for zone_num in range(1, number_of_zones + 1):
                _LOGGER.info("Getting info about zone=%d", zone_num)
                cmd = GetZoneInfoCommand(state, zone=zone_num).raw
                await session.write(cmd)
                state.increment_frame_number()
                res = await session.read(64)
                zone_info = GetZoneInfoResponse(res)
                _LOGGER.debug("Zone=%d has type=%s, name=%s", zone_num, zone_info.type, zone_info.name)
                zones.append({"num": zone_num, "name": zone_info.name, "type": zone_info.type})
            return zones

        except (IOError, ValueError) as e:
            # IOError can hardly happen when Session is too resilient...
            # but ValueError happens quite often because of malformed (out-of-order) zone_info responses
            raise UpdateFailed(e) from e

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update,
        # update_interval=timedelta(hours=1),  # do NOT update data at all - only after HA restart
    )
    await coordinator.async_config_entry_first_refresh()

    dr = device_registry.async_get(hass)
    dr.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(CONNECTION_NETWORK_MAC, entry.data["mac"])},
        name=f"{MANUFACTURER} Wi-Fi relay",  # TODO localize?
        manufacturer=MANUFACTURER,
    )

    new_entities = []
    for zone_info in coordinator.data:
        zone = Zone(entry, coordinator, session, state, zone_info["num"], zone_info["type"], zone_info["name"])
        new_entities.append(zone)

    if new_entities:
        async_add_entities(new_entities)

    hass.data[DOMAIN][entry.entry_id] = {
        "session": session,
    }


async def async_unload_entry(hass, entry):
    session = hass.data[DOMAIN].pop(entry.entry_id)["session"]
    await session.close()


class Zone(CoordinatorEntity, LightEntity, RestoreEntity):
    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator,
        session: Session,
        state: State,
        zone_num: int,
        zone_type: ZoneType,
        zone_name: str,
    ):
        super().__init__(coordinator)

        if zone_type is ZoneType.RGBCCT:
            # TODO add RGBCCT support
            zone_type = ZoneType.RGBW
            _LOGGER.warning("RGBCCT / RGBWW lights are not supported yet. Please file an issue on Github!")

        self._entry = entry
        self._session = session
        self._state = state
        self._zone_num = zone_num
        self._zone_type = zone_type
        self._zone_name = zone_name

        self._is_on = None

    @property
    def name(self):
        return self._zone_name

    @property
    def unique_id(self):
        return "-".join((DOMAIN, self._entry.data["mac"], str(self._zone_num)))

    @property
    def device_info(self):
        # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
        return {
            "connections": {(CONNECTION_NETWORK_MAC, self._entry.data["mac"])},
        }

    @property
    def assumed_state(self):
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state:
            self._is_on = last_state.state == STATE_ON
            self._attr_brightness = last_state.attributes.get(ATTR_BRIGHTNESS)
            self._attr_color_temp = last_state.attributes.get(ATTR_COLOR_TEMP)
            self._attr_rgb_color = last_state.attributes.get(ATTR_RGB_COLOR)
            self._attr_rgbw_color = last_state.attributes.get(ATTR_RGBW_COLOR)

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def color_mode(self) -> str:
        return {
            ZoneType.RGBW: COLOR_MODE_RGBW,
            ZoneType.RGB: COLOR_MODE_RGB,
            ZoneType.CCT: COLOR_MODE_COLOR_TEMP,
            ZoneType.Dimmer: COLOR_MODE_BRIGHTNESS,
            ZoneType.Switch: COLOR_MODE_ONOFF,
        }[self._zone_type]

    @property
    def supported_color_modes(self) -> set[str]:
        return {self.color_mode}

    async def async_turn_on(self, **kwargs):
        # Only execute what is necessary, nothing else
        await self._turn_on()
        if ATTR_RGBW_COLOR in kwargs:
            await self._set_rgbw(*kwargs[ATTR_RGBW_COLOR])
        if ATTR_RGB_COLOR in kwargs:
            await self._set_rgb(*kwargs[ATTR_RGB_COLOR])
        if ATTR_COLOR_TEMP in kwargs:
            await self._set_color_temp(kwargs[ATTR_COLOR_TEMP])
        if ATTR_BRIGHTNESS in kwargs:
            await self._set_brightness(kwargs[ATTR_BRIGHTNESS])
        self.async_write_ha_state()

    async def _turn_on(self):
        _LOGGER.debug("Powering on zone=%s", self.unique_id)
        cmd = PowerOnCommand(self._state, zone=self._zone_num).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._is_on = True

    async def _set_brightness(self, brightness: int):
        _LOGGER.debug("Setting brightness=%d for zone=%s", brightness, self.unique_id)
        cmd = BrightnessCommand(self._state, zone=self._zone_num, brightness=brightness).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._attr_brightness = brightness

    async def _set_color_temp(self, color_temp: int):
        _LOGGER.debug("Setting color_temp=%d for zone=%s", color_temp, self.unique_id)
        temperature_byte = self._convert_color_temp(color_temp)
        cmd = TemperatureCommand(self._state, zone=self._zone_num, temperature=temperature_byte).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._attr_color_temp = color_temp

    async def _set_rgb(self, red: int, green: int, blue: int):
        _LOGGER.debug("Setting red=%d green=%d blue=%d for zone=%s", red, green, blue, self.unique_id)
        # no dedicated command for RGB only is available
        cmd = RGBWCommand(self._state, zone=self._zone_num, red=red, green=green, blue=blue, white=0).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._attr_rgb_color = red, green, blue

    async def _set_rgbw(self, red: int, green: int, blue: int, white: int):
        _LOGGER.debug("Setting red=%d green=%d blue=%d white=%d for zone=%s", red, green, blue, white, self.unique_id)
        cmd = RGBWCommand(self._state, zone=self._zone_num, red=red, green=green, blue=blue, white=white).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._attr_rgbw_color = red, green, blue, white

    def _convert_color_temp(self, mireds):
        """Convert color temperature from mireds to byte."""
        return int(255 - 255 * ((mireds - self.min_mireds) / (self.max_mireds - self.min_mireds)))

    async def async_turn_off(self, **kwargs):
        await self._turn_off()
        self.async_write_ha_state()

    async def _turn_off(self):
        _LOGGER.debug("Powering off zone=%s", self.unique_id)
        cmd = PowerOffCommand(self._state, zone=self._zone_num).raw
        await self._session.write(cmd)
        self._state.increment_frame_number()
        _ = await self._session.read(64)
        self._is_on = False

    def turn_on(self, **kwargs):
        # we do not support non-async API
        return None

    def turn_off(self, **kwargs):
        # we do not support non-async API
        return None
