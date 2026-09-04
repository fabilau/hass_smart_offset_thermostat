from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    async_add_entities([SmartOffsetBoostSwitch(hass, entry, controller)])


class SmartOffsetBoostSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Callable[[], None] | None = None

        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_boost"
        self._attr_translation_key = "boost"
        self._attr_icon = "mdi:fire"

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
    def is_on(self) -> bool:
        return bool(
            self.controller.boost_active
            and (self.hass.loop.time() < self.controller.boost_until)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.start_boost()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.stop_boost()
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
