"""Constants for Smart Offset Thermostat."""

from __future__ import annotations

from typing import Any, Final

DOMAIN: Final = "smart_offset_thermostat"
INTEGRATION_VERSION: Final = "2.0.5"
CONFIG_ENTRY_VERSION: Final = 3
CONFIG_ENTRY_MINOR_VERSION: Final = 5

PLATFORMS: Final = [
    "binary_sensor",
    "button",
    "climate",
    "select",
    "sensor",
    "switch",
]

CONF_CLIMATE: Final = "climate_entity"
CONF_ROOM_SENSOR: Final = "room_sensor_entity"
CONF_ROOM_TARGET: Final = "room_target"
# Internal recovery metadata. The stable identity deliberately remains in the
# entry so recovered thermostats keep their historical entities and state.
CONF_REGISTRY_IDENTITY: Final = "_registry_identity"
CONF_RECOVERY_SOURCE_ENTRY_ID: Final = "_recovery_source_entry_id"
CONF_RECOVERY_DEVICE_ID: Final = "_recovery_device_id"
CONF_RECOVERY_FINGERPRINT: Final = "_recovery_fingerprint"
CONF_INTERVAL_SEC: Final = "interval_sec"
CONF_DEADBAND: Final = "deadband"
CONF_STEP_MAX: Final = "step_max"
CONF_STEP_MIN: Final = "step_min"
CONF_CONTROL_GAIN: Final = "control_gain"
CONF_LEARN_RATE: Final = "learn_rate"
CONF_TRV_MIN: Final = "trv_min"
CONF_TRV_MAX: Final = "trv_max"
CONF_COOLDOWN_SEC: Final = "cooldown_sec"
CONF_ENABLE_LEARNING: Final = "enable_learning"
CONF_PAUSE_ON_HVAC_OFF: Final = "pause_on_hvac_off"
CONF_MANUAL_TARGET_SYNC: Final = "manual_target_sync"
CONF_MANUAL_DELAY_SEC: Final = "manual_delay_sec"
CONF_PRESETS: Final = "presets"
CONF_HVAC_MODE: Final = "hvac_mode"

# Legacy keys are retained only for migration and compatibility reads.
CONF_MODES: Final = "modes"
CONF_WINDOW_SENSOR: Final = "window_sensor_entity"
CONF_WINDOW_SENSORS: Final = "window_sensor_entities"
CONF_WINDOW_DELAY_SEC: Final = "window_delay_sec"
CONF_BOOST_DURATION_SEC: Final = "boost_duration_sec"

CONF_STUCK_ENABLE: Final = "stuck_enable"
CONF_STUCK_SECONDS: Final = "stuck_seconds"
CONF_STUCK_MIN_DROP: Final = "stuck_min_drop"
CONF_STUCK_STEP: Final = "stuck_step"

DEFAULT_ROOM_TARGET: Final = 22.0
DEFAULT_INTERVAL_SEC: Final = 240
DEFAULT_DEADBAND: Final = 0.2
DEFAULT_STEP_MAX: Final = 1.0
DEFAULT_STEP_MIN: Final = 0.5
DEFAULT_CONTROL_GAIN: Final = 0.5
DEFAULT_LEARN_RATE: Final = 0.05
DEFAULT_TRV_MIN: Final = 12.0
DEFAULT_TRV_MAX: Final = 30.0
DEFAULT_COOLDOWN_SEC: Final = 600
DEFAULT_ENABLE_LEARNING: Final = True
DEFAULT_PAUSE_ON_HVAC_OFF: Final = False
DEFAULT_MANUAL_TARGET_SYNC: Final = False
DEFAULT_MANUAL_DELAY_SEC: Final = 10
DEFAULT_BOOST_DURATION_SEC: Final = 300
DEFAULT_WINDOW_DELAY_SEC: Final = 60
DEFAULT_STUCK_ENABLE: Final = True
DEFAULT_STUCK_SECONDS: Final = 1800
DEFAULT_STUCK_MIN_DROP: Final = 0.10
DEFAULT_STUCK_STEP: Final = 0.5

MODE_PRESENT: Final = "present"
MODE_AWAY: Final = "away"
MODE_SUMMER: Final = "summer"
MODE_WINTER: Final = "winter"
MODES: Final = [MODE_PRESENT, MODE_AWAY, MODE_SUMMER, MODE_WINTER]

PRESET_HVAC_KEEP: Final = "keep"
PRESET_HVAC_MODES: Final = (
    PRESET_HVAC_KEEP,
    "heat",
    "cool",
    "auto",
    "dry",
    "fan_only",
    "off",
)
REGULATED_HVAC_MODES: Final = ("heat", "cool")
# AUTO represents a device-owned schedule/strategy in Home Assistant. It can
# be selected by a preset, but this integration must not overwrite its target.
PASSIVE_HVAC_MODES: Final = ("auto", "dry", "fan_only")


def default_presets(
    room_target: float = DEFAULT_ROOM_TARGET,
    default_hvac_mode: str = "heat",
    *,
    ac_capable: bool = False,
) -> list[dict]:
    """Return a fresh, user-friendly default preset list."""
    target = float(room_target)
    away_target = max(DEFAULT_TRV_MIN, target - 4.0)
    return [
        {
            "id": MODE_PRESENT,
            "target": target,
            "pause": False,
            CONF_HVAC_MODE: default_hvac_mode,
        },
        {
            "id": MODE_AWAY,
            "target": away_target,
            "pause": False,
            CONF_HVAC_MODE: default_hvac_mode,
        },
        {
            "id": MODE_SUMMER,
            "target": target,
            "pause": not ac_capable,
            CONF_HVAC_MODE: "cool" if ac_capable else default_hvac_mode,
        },
        {
            "id": MODE_WINTER,
            "target": target,
            "pause": False,
            CONF_HVAC_MODE: (
                PRESET_HVAC_KEEP if default_hvac_mode == PRESET_HVAC_KEEP else "heat"
            ),
        },
    ]


# Compatibility only. New code must call default_presets() to receive a fresh copy.
DEFAULT_MODES: Final = default_presets()


def entry_registry_identity(entry: Any) -> str:
    """Return the stable entity/device registry identity for a config entry."""
    data = getattr(entry, "data", {})
    identity = data.get(CONF_REGISTRY_IDENTITY) if hasattr(data, "get") else None
    if isinstance(identity, str) and identity.strip():
        return identity.strip()
    return str(getattr(entry, "entry_id", ""))


DEFAULTS: Final = {
    CONF_ROOM_TARGET: DEFAULT_ROOM_TARGET,
    CONF_INTERVAL_SEC: DEFAULT_INTERVAL_SEC,
    CONF_DEADBAND: DEFAULT_DEADBAND,
    CONF_STEP_MAX: DEFAULT_STEP_MAX,
    CONF_STEP_MIN: DEFAULT_STEP_MIN,
    CONF_CONTROL_GAIN: DEFAULT_CONTROL_GAIN,
    CONF_LEARN_RATE: DEFAULT_LEARN_RATE,
    CONF_TRV_MIN: DEFAULT_TRV_MIN,
    CONF_TRV_MAX: DEFAULT_TRV_MAX,
    CONF_COOLDOWN_SEC: DEFAULT_COOLDOWN_SEC,
    CONF_ENABLE_LEARNING: DEFAULT_ENABLE_LEARNING,
    CONF_PAUSE_ON_HVAC_OFF: DEFAULT_PAUSE_ON_HVAC_OFF,
    CONF_MANUAL_TARGET_SYNC: DEFAULT_MANUAL_TARGET_SYNC,
    CONF_MANUAL_DELAY_SEC: DEFAULT_MANUAL_DELAY_SEC,
    CONF_BOOST_DURATION_SEC: DEFAULT_BOOST_DURATION_SEC,
    CONF_WINDOW_DELAY_SEC: DEFAULT_WINDOW_DELAY_SEC,
    CONF_STUCK_ENABLE: DEFAULT_STUCK_ENABLE,
    CONF_STUCK_SECONDS: DEFAULT_STUCK_SECONDS,
    CONF_STUCK_MIN_DROP: DEFAULT_STUCK_MIN_DROP,
    CONF_STUCK_STEP: DEFAULT_STUCK_STEP,
}

# Keep this list in one place. The enum sensor and translations use the same values.
LAST_ACTION_OPTIONS: Final = (
    "init",
    "deadband_init",
    "deadband_rebase",
    "hold",
    "stable_learn",
    "cooldown",
    "set_temperature",
    "skipped_no_change",
    "skipped_unavailable_entities",
    "skipped_invalid_room_temp",
    "boost",
    "window_open",
    "paused",
    "hvac_off",
    "hvac_mode_set",
    "passive_mode",
    "stuck_overtemp_down",
    "reset_offset",
    "manual_target_sync",
    "manual_hold",
    "manual_echo",
    "service_error",
)

SIGNAL_UPDATE: Final = "smart_offset_thermostat_update"
