from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.select import SelectEntity

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetModeSelect(hass, entry, controller)])


class SmartOffsetModeSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Optional[Callable[[], None]] = None

        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_translation_key = "mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def current_option(self) -> str | None:
        return self.controller.get_mode()

    @property
    def options(self) -> list[str]:
        return self.controller.get_mode_ids()

    async def async_select_option(self, option: str) -> None:
        if option not in self.controller.get_mode_ids():
            return
        await self.controller.set_mode(option)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        @callback
        def _update():
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(
            self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}", _update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
