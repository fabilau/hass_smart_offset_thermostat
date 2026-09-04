from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    SIGNAL_UPDATE,
    entry_registry_identity,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetResetOffsetButton(hass, entry, controller)])


class SmartOffsetResetOffsetButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Callable[[], None] | None = None

        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_reset_offset"
        self._attr_translation_key = "reset_offset"
        self._attr_icon = "mdi:restart"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._registry_identity)},
            name=self.entry.title or "Smart Offset Thermostat",
            manufacturer="fabilau",
            model="Smart Offset Thermostat",
            sw_version=INTEGRATION_VERSION,
        )

    async def async_press(self) -> None:
        await self.controller.reset_offset()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        @callback
        def _update():
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}", _update
            )
        )
