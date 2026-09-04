"""Operational status binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    REGULATED_HVAC_MODES,
    SIGNAL_UPDATE,
    entry_registry_identity,
)


@dataclass(frozen=True)
class _StatusDescription:
    key: str
    device_class: BinarySensorDeviceClass
    value_fn: Callable[[object], bool]
    entity_category: EntityCategory | None = None


STATUSES = (
    _StatusDescription(
        "window_open",
        BinarySensorDeviceClass.WINDOW,
        lambda controller: bool(controller.window_is_open),
    ),
    _StatusDescription(
        "boost_running",
        BinarySensorDeviceClass.RUNNING,
        lambda controller: bool(
            controller.boost_active
            and controller.hass.loop.time() < controller.boost_until
        ),
    ),
    _StatusDescription(
        "control_active",
        BinarySensorDeviceClass.RUNNING,
        lambda controller: bool(
            controller.get_hvac_mode() in REGULATED_HVAC_MODES
            and not controller.pause_active
            and not controller._window_setback_active
        ),
    ),
    _StatusDescription(
        "controller_problem",
        BinarySensorDeviceClass.PROBLEM,
        lambda controller: (
            controller.last_action
            in {
                "service_error",
                "skipped_unavailable_entities",
                "skipped_invalid_room_temp",
            }
        ),
        EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        SmartOffsetStatusBinarySensor(entry, controller, description)
        for description in STATUSES
    )


class SmartOffsetStatusBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller, description) -> None:
        self.entry = entry
        self.controller = controller
        self.description = description
        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category

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
        return self.description.value_fn(self.controller)

    @property
    def extra_state_attributes(self) -> dict:
        if self.description.key != "window_open":
            return {}
        return {"sensor_state_unknown": self.controller.window_state_unknown}

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
