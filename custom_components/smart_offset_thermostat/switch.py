from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN, SIGNAL_UPDATE

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetBoostSwitch(hass, entry, controller)])

class SmartOffsetBoostSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Optional[Callable[[], None]] = None

        self._attr_unique_id = f"{entry.entry_id}_boost"
        self._attr_name = "Boost"
        self._attr_icon = "mdi:fire"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.controller.boost_active and (self.hass.loop.time() < self.controller.boost_until))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.start_boost()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.controller._cancel_boost()
        await self.controller.trigger_once()
        self.controller._notify()
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
