"""Downloadable diagnostics for support requests."""

from __future__ import annotations

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIMATE,
    CONF_MODES,
    CONF_PRESETS,
    CONF_RECOVERY_DEVICE_ID,
    CONF_RECOVERY_FINGERPRINT,
    CONF_RECOVERY_SOURCE_ENTRY_ID,
    CONF_REGISTRY_IDENTITY,
    CONF_ROOM_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_SENSORS,
    DOMAIN,
)

TO_REDACT = {
    CONF_CLIMATE,
    CONF_ROOM_SENSOR,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_SENSORS,
    CONF_REGISTRY_IDENTITY,
    CONF_RECOVERY_SOURCE_ENTRY_ID,
    CONF_RECOVERY_DEVICE_ID,
    CONF_RECOVERY_FINGERPRINT,
    CONF_PRESETS,
    CONF_MODES,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return configuration and controller state without Home Assistant secrets."""
    controller = hass.data[DOMAIN][entry.entry_id]
    return {
        "config_entry": {
            "version": entry.version,
            "minor_version": getattr(entry, "minor_version", 0),
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "controller": {
            "preset": REDACTED,
            "hvac_mode": controller.get_hvac_mode(),
            "last_action": controller.last_action,
            "last_error": controller.last_error,
            "last_requested_setpoint": controller.last_set,
            "last_confirmed_setpoint": controller.last_confirmed_setpoint,
            "learned_offset": controller.storage.get_offset(
                entry.entry_id, controller.get_hvac_mode()
            ),
            "comfort_score": controller.comfort_score,
            "mean_absolute_error": controller.mean_absolute_error,
            "temperature_trend": controller.temperature_trend,
            "control_output": controller.control_output,
            "setpoint_change_count": controller.change_count,
            "manual_change_count": controller.manual_change_count,
            "window_open": controller.window_is_open,
            "window_state_unknown": controller.window_state_unknown,
            "boost_active": controller.boost_active,
            "control_paused": controller.pause_active,
        },
    }
