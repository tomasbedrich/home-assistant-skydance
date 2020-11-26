import asyncio

from homeassistant.components.light import (ATTR_BRIGHTNESS, LightEntity, SUPPORT_BRIGHTNESS, SUPPORT_COLOR_TEMP,
                                            ATTR_COLOR_TEMP)
from skydance.controller import Controller

from .const import DOMAIN, MANUFACTURER


# This function is called as part of the __init__.async_setup_entry (via the
# hass.config_entries.async_forward_entry_setup call)
async def async_setup_entry(hass, config, async_add_devices):
    controller = hass.data[DOMAIN][config.entry_id]
    # TODO zone discovery
    new_devices = [CCTLight(controller, zone) for zone in (1, 2)]
    if new_devices:
        async_add_devices(new_devices)


class CCTLight(LightEntity):
    supported_features = SUPPORT_BRIGHTNESS | SUPPORT_COLOR_TEMP

    def __init__(self, controller, zone):
        self._controller: Controller = controller
        self._zone = zone
        self._name = f"Skydance Zone {zone}"

        self._state = None
        self._brightness = None
        self._color_temp = None

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        # An entity is looked up in the registry based on a combination of the platform type (e.g., light),
        # and the integration name (domain) (e.g. hue)
        # and the unique ID of the entity.
        # TODO find something more unique
        return f"{DOMAIN}-{self._zone}"

    # Information about the devices that is partially visible in the UI.
    # The most critical thing here is to give this entity a name so it is displayed
    # as a "device" in the HA UI. This name is used on the Devices overview table,
    # and the initial screen when the device is added (rather than the entity name
    # property below). You can then associate other Entities (eg: a battery
    # sensor) with this device, so it shows more like a unified element in the UI.
    # For example, an associated battery sensor will be displayed in the right most
    # column in the Configuration > Devices view for a device.
    # To associate an entity with this device, the device_info must also return an
    # identical "identifiers" attribute, but not return a name attribute.
    # See the sensors.py file for the corresponding example setup.
    # Additional meta data can also be returned here, including sw_version (displayed
    # as Firmware), model and manufacturer (displayed as <model> by <manufacturer>)
    # shown on the device info screen. The Manufacturer and model also have their
    # respective columns on the Devices overview table. Note: Many of these must be
    # set when the device is first added, and they are not always automatically
    # refreshed by HA from it's internal cache.
    # For more information see:
    # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            # If desired, the name for the device could be different to the entity
            # TODO add via_device - controller?
            "manufacturer": MANUFACTURER,
            "name": self.name,
        }

    @property
    def is_on(self):
        return self._state

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
        await self._controller.power_zone(self._zone, True)
        self._state = True

    async def _set_brightness(self, brightness):
        await self._controller.dim_zone(self._zone, brightness)
        self._brightness = brightness

    async def _set_color_temp(self, color_temp):
        temperature_byte = int(255 - 255 * ((color_temp - self.min_mireds) / (self.max_mireds - self.min_mireds)))
        await self._controller.temp_zone(self._zone, temperature_byte)
        self._color_temp = color_temp

    async def async_turn_off(self, **kwargs):
        await self._controller.power_zone(self._zone, False)
        self._state = False

    def update(self):
        """Fetch new state data for this light.
        This is the only method that should fetch new data (do I/O).
        """
        # TODO implement
        pass
        # self._light.update()
        # self._state = self._light.is_on()
        # self._brightness = self._light.brightness
