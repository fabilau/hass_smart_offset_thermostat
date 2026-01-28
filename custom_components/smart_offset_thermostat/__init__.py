from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, PLATFORMS
from .storage import OffsetStorage
from .controller import SmartOffsetController
from homeassistant.helpers import config_validation as cv

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await controller.async_start()
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    controller = hass.data[DOMAIN].pop(entry.entry_id, None)
    if controller:
        await controller.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    return unload_ok
