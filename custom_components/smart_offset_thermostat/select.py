from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.select import SelectEntity
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
    async_add_entities([SmartOffsetModeSelect(hass, entry, controller)])


class SmartOffsetModeSelect(SelectEntity):
    _attr_has_entity_name = True
    # Keep the legacy automation bridge enabled for upgrade compatibility.
    _attr_entity_registry_enabled_default = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Callable[[], None] | None = None

        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_mode"
        self._attr_translation_key = "preset_legacy"
        self._attr_icon = "mdi:form-dropdown"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._registry_identity)},
            name=self.entry.title or "Smart Offset Thermostat",
            manufacturer="fabilau",
            model="Smart Offset Thermostat",
            sw_version=INTEGRATION_VERSION,
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

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}", _update
            )
        )
