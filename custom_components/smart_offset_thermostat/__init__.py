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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})

    if "storage" not in hass.data[DOMAIN]:
        store = OffsetStorage(hass)
        await store.async_load()
        hass.data[DOMAIN]["storage"] = store

    store = hass.data[DOMAIN]["storage"]
    # Migrate window sensor from entry.data -> entry.options (so it can be changed later in Options)
    # Backwards compatible: controller reads via opt(), but we copy once so the UI can modify it.
    if "window_sensor_entity" in entry.data and "window_sensor_entity" not in entry.options:
        new_options = dict(entry.options)
        new_options["window_sensor_entity"] = entry.data.get("window_sensor_entity")
        hass.config_entries.async_update_entry(entry, options=new_options)

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
