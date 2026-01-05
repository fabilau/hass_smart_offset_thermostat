from __future__ import annotations

from typing import Any, Callable, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, ClimateEntityFeature
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from .const import DOMAIN, SIGNAL_UPDATE, CONF_ROOM_TARGET, DEFAULTS

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetVirtualThermostat(hass, entry, controller)])

class SmartOffsetVirtualThermostat(ClimateEntity):
    _attr_has_entity_name = True
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._unsub: Optional[Callable[[], None]] = None

        self._attr_unique_id = f"{entry.entry_id}_virtual_thermostat"
        self._attr_name = "Smart Thermostat"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def current_temperature(self) -> float | None:
        room_state = self.hass.states.get(self.entry.data.get("room_sensor_entity"))
        if not room_state:
            return None
        try:
            return float(room_state.state)
        except Exception:
            return None

    @property
    def target_temperature(self) -> float | None:
        v = self.controller.opt(CONF_ROOM_TARGET)
        try:
            return float(v)
        except Exception:
            return float(DEFAULTS[CONF_ROOM_TARGET])

    @property
    def min_temp(self) -> float:
        try:
            return float(self.controller.opt("trv_min") or 5.0)
        except Exception:
            return 5.0

    @property
    def max_temp(self) -> float:
        try:
            return float(self.controller.opt("trv_max") or 35.0)
        except Exception:
            return 35.0

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        new_target = float(kwargs[ATTR_TEMPERATURE])

        new_options = dict(self.entry.options)
        new_options[CONF_ROOM_TARGET] = new_target
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

        await self.controller.trigger_once()
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
