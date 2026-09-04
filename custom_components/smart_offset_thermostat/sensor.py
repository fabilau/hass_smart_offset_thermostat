"""Diagnostics and long-term statistics sensors."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE,
    CONF_ROOM_SENSOR,
    DOMAIN,
    INTEGRATION_VERSION,
    LAST_ACTION_OPTIONS,
    SIGNAL_UPDATE,
    entry_registry_identity,
)


@dataclass(frozen=True)
class _SensorDefinition:
    key: str
    value_fn: Callable[[Any], Any]
    unit: str | None = None
    temperature_kind: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    options: Sequence[str] | None = None
    icon: str | None = None
    entity_category: EntityCategory | None = None
    enabled: bool = True
    precision: int | None = None


def _rounded(value: Any, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


SENSORS = (
    _SensorDefinition(
        "error",
        lambda c: _rounded(c.last_error),
        temperature_kind="delta",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-alert",
        precision=2,
    ),
    _SensorDefinition(
        "absolute_error",
        lambda c: None if c.last_error is None else abs(round(c.last_error, 3)),
        temperature_kind="delta",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve-cumulative",
        precision=2,
    ),
    _SensorDefinition(
        "mean_absolute_error",
        lambda c: _rounded(c.mean_absolute_error),
        temperature_kind="delta",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-timeline-variant-shimmer",
        precision=2,
    ),
    _SensorDefinition(
        "comfort_score",
        lambda c: _rounded(c.comfort_score, 1),
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-heart",
        precision=1,
    ),
    _SensorDefinition(
        "temperature_trend",
        lambda c: _rounded(c.temperature_trend),
        temperature_kind="rate",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:trending-up",
        precision=2,
    ),
    _SensorDefinition(
        "control_output",
        lambda c: _rounded(c.control_output, 1),
        unit=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        precision=1,
    ),
    _SensorDefinition(
        "offset",
        lambda c: round(c.storage.get_offset(c.entry.entry_id, c.get_hvac_mode()), 3),
        temperature_kind="delta",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune-vertical-variant",
        precision=2,
    ),
    _SensorDefinition(
        "target_trv",
        lambda c: _rounded(c.last_target_trv),
        temperature_kind="absolute",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermostat",
        entity_category=EntityCategory.DIAGNOSTIC,
        precision=1,
    ),
    _SensorDefinition(
        "last_set",
        lambda c: _rounded(c.last_set),
        temperature_kind="absolute",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        precision=1,
    ),
    _SensorDefinition(
        "confirmed_setpoint",
        lambda c: _rounded(c.last_confirmed_setpoint),
        temperature_kind="absolute",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:check-decagram-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        precision=1,
    ),
    _SensorDefinition(
        "correction",
        lambda c: _rounded(c.last_correction),
        temperature_kind="delta",
        device_class=SensorDeviceClass.TEMPERATURE_DELTA,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:delta",
        entity_category=EntityCategory.DIAGNOSTIC,
        precision=2,
    ),
    _SensorDefinition(
        "last_action",
        lambda c: c.last_action,
        icon="mdi:code-tags",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _SensorDefinition(
        "last_action_text",
        lambda c: c.last_action,
        device_class=SensorDeviceClass.ENUM,
        options=LAST_ACTION_OPTIONS,
        icon="mdi:state-machine",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _SensorDefinition(
        "change_count",
        lambda c: int(c.change_count),
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
    ),
    _SensorDefinition(
        "manual_change_count",
        lambda c: int(c.manual_change_count),
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:gesture-tap-button",
    ),
    # Legacy sensor unique IDs remain enabled for dashboards and automations.
    # Their semantic binary replacements are also available in binary_sensor.py.
    _SensorDefinition(
        "window_state",
        lambda c: "open" if c.window_is_open else "closed",
        icon="mdi:window-open-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _SensorDefinition(
        "boost_remaining",
        lambda c: (
            int(max(0.0, c.boost_until - c.hass.loop.time())) if c.boost_active else 0
        ),
        unit="s",
        device_class=SensorDeviceClass.DURATION,
        icon="mdi:timer-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _SensorDefinition(
        "boost_active",
        lambda c: bool(c.boost_active and c.hass.loop.time() < c.boost_until),
        icon="mdi:fire",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _SensorDefinition(
        "control_paused",
        lambda c: bool(c.pause_active or c._window_setback_active),
        icon="mdi:pause-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SmartOffsetSensor(hass, entry, controller, definition) for definition in SENSORS
    )


class SmartOffsetSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        controller,
        definition: _SensorDefinition,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self.definition = definition
        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_{definition.key}"
        self._attr_translation_key = definition.key
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        self._attr_options = list(definition.options) if definition.options else None
        self._attr_icon = definition.icon
        self._attr_entity_category = definition.entity_category
        self._attr_entity_registry_enabled_default = definition.enabled
        self._attr_suggested_display_precision = definition.precision

        # Controller values are canonical Celsius; SensorEntity handles user
        # display conversion for temperature device classes.
        temperature_unit = UnitOfTemperature.CELSIUS
        if definition.temperature_kind == "rate":
            self._attr_native_unit_of_measurement = f"{temperature_unit}/h"
        elif definition.temperature_kind:
            self._attr_native_unit_of_measurement = temperature_unit
        else:
            self._attr_native_unit_of_measurement = definition.unit

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
    def native_value(self):
        return self.definition.value_fn(self.controller)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "physical_thermostat": self.entry.data.get(CONF_CLIMATE),
            "room_sensor": self.entry.data.get(CONF_ROOM_SENSOR),
            "preset": self.controller.get_preset(),
            "hvac_mode": self.controller.get_hvac_mode(),
            "room_target": self.controller.get_preset_target(),
        }

    async def async_added_to_hass(self) -> None:
        @callback
        def _update() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self.entry.entry_id}",
                _update,
            )
        )
