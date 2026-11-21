"""Light platform for the Skydance Wi-Fi relay."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from skydance.enum import ZoneType
from skydance.network.session import Session
from skydance.protocol import (
    BrightnessCommand,
    FrameError,
    PowerOffCommand,
    PowerOnCommand,
    RGBWCommand,
    TemperatureCommand,
)

from . import SkydanceConfigEntry
from .const import DOMAIN

_COMMUNICATION_ERRORS = (OSError, asyncio.TimeoutError, EOFError, FrameError)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkydanceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Skydance lights from a config entry."""
    runtime = entry.runtime_data

    async_add_entities(
        [
            Zone(
                entry,
                runtime.coordinator,
                runtime.session,
                zone_info["num"],
                zone_info["type"],
                zone_info["name"],
            )
            for zone_info in runtime.coordinator.data
        ]
    )


class Zone(CoordinatorEntity, LightEntity, RestoreEntity):
    """A single zone of a Skydance Wi-Fi relay."""

    _attr_min_color_temp_kelvin = DEFAULT_MIN_KELVIN
    _attr_max_color_temp_kelvin = DEFAULT_MAX_KELVIN

    def __init__(
        self,
        entry: SkydanceConfigEntry,
        coordinator: DataUpdateCoordinator,
        session: Session,
        zone_num: int,
        zone_type: ZoneType,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator)

        if zone_type is ZoneType.RGBCCT:
            # TODO add RGBCCT support
            zone_type = ZoneType.RGBW
            _LOGGER.warning(
                "RGBCCT / RGBWW lights are not supported yet. Please file an issue on Github!"
            )

        self._entry = entry
        self._session = session
        self._zone_num = zone_num
        self._zone_type = zone_type
        self._zone_name = zone_name

        self._is_on = None

    @property
    def name(self) -> str:
        """Return the name of the zone."""
        return self._zone_name

    @property
    def unique_id(self) -> str:
        """Return a unique ID of the zone."""
        return "-".join((DOMAIN, self._entry.data["mac"], str(self._zone_num)))

    @property
    def device_info(self):
        # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
        return {
            "connections": {(CONNECTION_NETWORK_MAC, self._entry.data["mac"])},
        }

    @property
    def assumed_state(self) -> bool:
        """Return True as the relay does not report the state back."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the last known state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state:
            self._is_on = last_state.state == STATE_ON
            self._attr_brightness = last_state.attributes.get(ATTR_BRIGHTNESS)
            self._attr_color_temp_kelvin = last_state.attributes.get(
                ATTR_COLOR_TEMP_KELVIN
            )
            self._attr_rgb_color = last_state.attributes.get(ATTR_RGB_COLOR)
            self._attr_rgbw_color = last_state.attributes.get(ATTR_RGBW_COLOR)

    @property
    def is_on(self) -> bool:
        """Return True if the zone is on."""
        return self._is_on

    @property
    def color_mode(self) -> str:
        """Return the color mode of the zone."""
        return {
            ZoneType.RGBW: ColorMode.RGBW,
            ZoneType.RGB: ColorMode.RGB,
            ZoneType.CCT: ColorMode.COLOR_TEMP,
            ZoneType.Dimmer: ColorMode.BRIGHTNESS,
            ZoneType.Switch: ColorMode.ONOFF,
        }[self._zone_type]

    @property
    def supported_color_modes(self) -> set[str]:
        """Return the supported color modes of the zone."""
        return {self.color_mode}

    async def _async_send(self, factory) -> bytes:
        """Send a single command to the relay.

        Communication errors are reported as HomeAssistantError, so that a
        service call fails fast and visibly instead of hanging forever.
        """
        try:
            return await self._session.request(factory)
        except _COMMUNICATION_ERRORS as err:
            raise HomeAssistantError(
                f"Skydance relay did not answer a command for zone "
                f"{self._zone_name!r}: {err}"
            ) from err

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the zone on."""
        # Only execute what is necessary, nothing else
        await self._turn_on()
        if ATTR_RGBW_COLOR in kwargs:
            await self._set_rgbw(*kwargs[ATTR_RGBW_COLOR])
        if ATTR_RGB_COLOR in kwargs:
            await self._set_rgb(*kwargs[ATTR_RGB_COLOR])
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self._set_color_temp(kwargs[ATTR_COLOR_TEMP_KELVIN])
        if ATTR_BRIGHTNESS in kwargs:
            await self._set_brightness(kwargs[ATTR_BRIGHTNESS])
        self.async_write_ha_state()

    async def _turn_on(self) -> None:
        _LOGGER.debug("Powering on zone=%s", self.unique_id)
        await self._async_send(partial(PowerOnCommand, zone=self._zone_num))
        self._is_on = True

    async def _set_brightness(self, brightness: int) -> None:
        _LOGGER.debug("Setting brightness=%d for zone=%s", brightness, self.unique_id)
        await self._async_send(
            partial(BrightnessCommand, zone=self._zone_num, brightness=brightness)
        )
        self._attr_brightness = brightness

    async def _set_color_temp(self, color_temp: int) -> None:
        _LOGGER.debug("Setting color_temp=%d for zone=%s", color_temp, self.unique_id)
        temperature_byte = self._convert_color_temp(color_temp)
        await self._async_send(
            partial(
                TemperatureCommand,
                zone=self._zone_num,
                temperature=temperature_byte,
            )
        )
        self._attr_color_temp_kelvin = color_temp

    async def _set_rgb(self, red: int, green: int, blue: int) -> None:
        _LOGGER.debug(
            "Setting red=%d green=%d blue=%d for zone=%s",
            red,
            green,
            blue,
            self.unique_id,
        )
        # no dedicated command for RGB only is available
        await self._async_send(
            partial(
                RGBWCommand,
                zone=self._zone_num,
                red=red,
                green=green,
                blue=blue,
                white=0,
            )
        )
        self._attr_rgb_color = red, green, blue

    async def _set_rgbw(self, red: int, green: int, blue: int, white: int) -> None:
        _LOGGER.debug(
            "Setting red=%d green=%d blue=%d white=%d for zone=%s",
            red,
            green,
            blue,
            white,
            self.unique_id,
        )
        await self._async_send(
            partial(
                RGBWCommand,
                zone=self._zone_num,
                red=red,
                green=green,
                blue=blue,
                white=white,
            )
        )
        self._attr_rgbw_color = red, green, blue, white

    def _convert_color_temp(self, kelvin: int) -> int:
        """Convert color temperature from kelvin to byte (0-255).

        Lower kelvin values (warmer) map to lower byte values,
        higher kelvin values (cooler) map to higher byte values.
        """
        # Clamp kelvin to valid range
        kelvin = max(
            self._attr_min_color_temp_kelvin,
            min(kelvin, self._attr_max_color_temp_kelvin),
        )
        temp_range = self._attr_max_color_temp_kelvin - self._attr_min_color_temp_kelvin
        if temp_range == 0:
            return 0
        return int(255 * ((kelvin - self._attr_min_color_temp_kelvin) / temp_range))

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the zone off."""
        await self._turn_off()
        self.async_write_ha_state()

    async def _turn_off(self) -> None:
        _LOGGER.debug("Powering off zone=%s", self.unique_id)
        await self._async_send(partial(PowerOffCommand, zone=self._zone_num))
        self._is_on = False

    def turn_on(self, **kwargs) -> None:
        """We do not support non-async API."""
        return None

    def turn_off(self, **kwargs) -> None:
        """We do not support non-async API."""
        return None
