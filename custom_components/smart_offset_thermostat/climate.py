"""Virtual climate entity for Smart Offset Thermostat."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CLIMATE,
    CONF_ROOM_SENSOR,
    DOMAIN,
    INTEGRATION_VERSION,
    SIGNAL_UPDATE,
    entry_registry_identity,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SmartOffsetVirtualThermostat(hass, entry, controller)])


class SmartOffsetVirtualThermostat(ClimateEntity):
    """Native HA climate control for one room/physical thermostat pair."""

    _attr_has_entity_name = True
    _attr_translation_key = "thermostat"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, controller) -> None:
        self.hass = hass
        self.entry = entry
        self.controller = controller
        self._registry_identity = entry_registry_identity(entry)
        self._attr_unique_id = f"{self._registry_identity}_virtual_thermostat"

    def _calculate_supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )
        if "off" in self.controller.available_hvac_modes():
            features |= getattr(ClimateEntityFeature, "TURN_ON", 0)
            features |= getattr(ClimateEntityFeature, "TURN_OFF", 0)
        return features

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Expose source capabilities dynamically for late-loading entities."""
        return self._calculate_supported_features()

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
    def available(self) -> bool:
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        room = self.hass.states.get(self.entry.data.get(CONF_ROOM_SENSOR))
        return bool(
            climate
            and room
            and climate.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            and room.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            and self.controller.current_room_temperature() is not None
        )

    @property
    def temperature_unit(self) -> str:
        # Configuration and learned values have historically been Celsius.
        # ClimateEntity converts this native unit for the user's frontend.
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self) -> float | None:
        return self.controller.current_room_temperature()

    @property
    def target_temperature(self) -> float | None:
        return self.controller.get_preset_target()

    @property
    def target_temperature_step(self) -> float:
        return self.controller.target_temperature_step()

    @property
    def min_temp(self) -> float:
        return self.controller.target_temperature_limits()[0]

    @property
    def max_temp(self) -> float:
        return self.controller.target_temperature_limits()[1]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        result: list[HVACMode] = []
        for mode in self.controller.available_hvac_modes():
            try:
                result.append(HVACMode(mode))
            except ValueError:
                continue
        return result or [HVACMode.OFF, HVACMode.HEAT]

    @property
    def hvac_mode(self) -> HVACMode:
        try:
            return HVACMode(self.controller.get_hvac_mode())
        except ValueError:
            return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        physical = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        raw = physical.attributes.get("hvac_action") if physical else None
        try:
            return HVACAction(raw) if raw is not None else HVACAction.IDLE
        except ValueError:
            return None

    @property
    def preset_modes(self) -> list[str]:
        return self.controller.get_preset_ids()

    @property
    def preset_mode(self) -> str | None:
        return self.controller.get_preset()

    @property
    def icon(self) -> str:
        if self.hvac_mode == HVACMode.OFF:
            return "mdi:thermostat-off"
        if self.hvac_mode == HVACMode.COOL:
            return "mdi:snowflake-thermometer"
        return "mdi:thermostat-auto"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "physical_thermostat": self.entry.data.get(CONF_CLIMATE),
            "external_temperature_sensor": self.entry.data.get(CONF_ROOM_SENSOR),
            "learned_offset": round(
                self.controller.storage.get_offset(
                    self.entry.entry_id, self.controller.get_hvac_mode()
                ),
                3,
            ),
            "control_error": (
                None
                if self.controller.last_error is None
                else round(self.controller.last_error, 3)
            ),
            "control_output": (
                None
                if self.controller.control_output is None
                else round(self.controller.control_output, 1)
            ),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE not in kwargs:
            return
        target = max(self.min_temp, min(self.max_temp, float(kwargs[ATTR_TEMPERATURE])))
        await self.controller.set_preset_target(target)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.controller.async_set_hvac_mode(hvac_mode)

    async def async_turn_off(self) -> None:
        await self.controller.async_turn_off()

    async def async_turn_on(self) -> None:
        await self.controller.async_turn_on()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.controller.set_preset(preset_mode)

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
