from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_ROOM_TARGET,
    CONF_MODES,
    DEFAULTS,
    DEFAULT_MODES,
)
from .storage import OffsetStorage
from .controller import SmartOffsetController
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

CONFIG_SCHEMA = cv.config_entry_only_config_schema("smart_offset_thermostat")

async def async_setup(hass: HomeAssistant, config: dict):
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old options/data to the latest format."""
    # Note: We use a very small, safe migration:
    # - old: window_sensor_entity (single string)
    # - new: window_sensor_entities (list of strings)
    if entry.version is None:
        # Some HA versions use 1 as default; keep safe.
        current_version = 1
    else:
        current_version = entry.version

    options = dict(entry.options)
    data = dict(entry.data)

    changed = False

    # Migrate from single -> multiple (options)
    if "window_sensor_entities" not in options:
        if "window_sensor_entity" in options and options.get("window_sensor_entity"):
            options["window_sensor_entities"] = [options.get("window_sensor_entity")]
            options.pop("window_sensor_entity", None)
            changed = True
        elif "window_sensor_entity" in data and data.get("window_sensor_entity"):
            options["window_sensor_entities"] = [data.get("window_sensor_entity")]
            changed = True

    # Remove legacy key from options if still present
    if "window_sensor_entity" in options:
        options.pop("window_sensor_entity", None)
        changed = True
    if "pause_entities" in options:
        options.pop("pause_entities", None)
        changed = True

    # Remove legacy per-mode keys if present
    legacy_keys = [
        "mode_present_target",
        "mode_present_pause",
        "mode_away_target",
        "mode_away_pause",
        "mode_summer_target",
        "mode_summer_pause",
        "mode_winter_target",
        "mode_winter_pause",
    ]
    legacy_present = any(k in options for k in legacy_keys)

    # Initialize modes list if missing (present uses existing room target if available)
    if CONF_MODES not in options:
        if legacy_present:
            modes = [
                {"id": "present", "target": float(options.get("mode_present_target", options.get(CONF_ROOM_TARGET, DEFAULTS[CONF_ROOM_TARGET]))), "pause": bool(options.get("mode_present_pause", False))},
                {"id": "away", "target": float(options.get("mode_away_target", DEFAULTS[CONF_ROOM_TARGET])), "pause": bool(options.get("mode_away_pause", True))},
                {"id": "summer", "target": float(options.get("mode_summer_target", DEFAULTS[CONF_ROOM_TARGET])), "pause": bool(options.get("mode_summer_pause", False))},
                {"id": "winter", "target": float(options.get("mode_winter_target", DEFAULTS[CONF_ROOM_TARGET])), "pause": bool(options.get("mode_winter_pause", False))},
            ]
        else:
            modes = list(DEFAULT_MODES)
            for item in modes:
                if item.get("id") == "present":
                    item["target"] = float(options.get(CONF_ROOM_TARGET, DEFAULTS[CONF_ROOM_TARGET]))
        options[CONF_MODES] = modes
        changed = True

    for key in legacy_keys:
        if key in options:
            options.pop(key, None)
            changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, options=options, version=current_version)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})

    if "storage" not in hass.data[DOMAIN]:
        store = OffsetStorage(hass)
        await store.async_load()
        hass.data[DOMAIN]["storage"] = store

    store = hass.data[DOMAIN]["storage"]
    # Legacy migration is handled in async_migrate_entry

    controller = SmartOffsetController(hass, entry, store)
    hass.data[DOMAIN][entry.entry_id] = controller

    async def _async_entry_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        ctrl = hass.data[DOMAIN].get(updated_entry.entry_id)
        if ctrl:
            await ctrl.trigger_once(force=True)
            ctrl._notify()

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    async def _post_start(_):
        await controller.trigger_once(force=True)
        controller._notify()
    async_call_later(hass, 2, _post_start)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    controller = hass.data[DOMAIN].pop(entry.entry_id, None)
    if controller:
        await controller.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok
