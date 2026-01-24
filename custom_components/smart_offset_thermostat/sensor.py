from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.const import UnitOfTemperature

from .const import DOMAIN, SIGNAL_UPDATE, CONF_ROOM_TARGET


@dataclass(frozen=True)
class _Def:
    key: str
    unit: str | None = None
    device_class: str | None = None
    options: Sequence[str] | None = None

LAST_ACTION_OPTIONS = (
    "init",
    "deadband",
    "deadband_rebase",
    "cooldown",
    "set_temperature",
    "skipped_no_change",
    "skipped_unavailable_entities",
    "skipped_invalid_room_temp",
    "boost",
    "window_open",
    "stuck_overtemp_down",
    "reset_offset",
)

SENSORS = (
    _Def("error", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    _Def("offset", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    _Def("target_trv", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    _Def("last_set", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    _Def("last_action", None, None),
    _Def("last_action_text", None, SensorDeviceClass.ENUM, options=LAST_ACTION_OPTIONS),
    _Def("change_count", None, None),
    _Def("window_state", None, None),
    _Def("boost_remaining", "s", SensorDeviceClass.DURATION),
    _Def("boost_active", None, None),
    _Def("control_paused", None, None),
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    entities = [SmartOffsetDebugSensor(hass, entry, controller, d) for d in SENSORS]
    async_add_entities(entities)

class SmartOffsetDebugSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller, definition: _Def):
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self.definition = definition

        self._attr_unique_id = f"{entry.entry_id}_{definition.key}"
        self._attr_translation_key = definition.key
        self._attr_native_unit_of_measurement = definition.unit
        if definition.device_class:
            self._attr_device_class = definition.device_class

        if definition.options:
            self._attr_options = list(definition.options)

        self._unsub: Optional[Callable[[], None]] = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name="Smart Offset Thermostat",
            manufacturer="Custom",
            model="Smart Offset Thermostat",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "thermostat": self.entry.data.get("climate_entity"),
            "room_sensor": self.entry.data.get("room_sensor_entity"),
            "room_target": self.controller.opt(CONF_ROOM_TARGET),
        }

    @property
    def native_value(self):
        k = self.definition.key
        if k == "error":
            return None if self.controller.last_error is None else round(float(self.controller.last_error), 3)
        if k == "offset":
            return round(float(self.controller.storage.get_offset(self.entry.entry_id)), 3)
        if k == "target_trv":
            return None if self.controller.last_target_trv is None else float(self.controller.last_target_trv)
        if k == "last_set":
            return None if self.controller.last_set is None else float(self.controller.last_set)
        if k == "last_action":
            return self.controller.last_action
        if k == "last_action_text":
            return self.controller.last_action
        if k == "change_count":
            return int(self.controller.change_count)
        if k == "window_state":
            return "open" if self.controller.window_is_open else "closed"
        if k == "boost_remaining":
            if not self.controller.boost_active:
                return 0
            remaining = int(max(0.0, self.controller.boost_until - self.hass.loop.time()))
            return remaining
        if k == "boost_active":
            return bool(self.controller.boost_active and (self.hass.loop.time() < self.controller.boost_until))
        if k == "control_paused":
            paused = self.controller.window_is_open or (self.controller.boost_active and (self.hass.loop.time() < self.controller.boost_until))
            return bool(paused)
        return None

    async def async_added_to_hass(self) -> None:
        @callback
        def _update():
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(
            self.hass,
            f"{SIGNAL_UPDATE}_{self.entry.entry_id}",
            _update,
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
