from __future__ import annotations
from homeassistant.helpers.storage import Store

_STORAGE_VERSION = 1
_STORAGE_KEY = "smart_offset_thermostat"

class OffsetStorage:
    def __init__(self, hass):
        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data = {}

    async def async_load(self):
        self._data = await self._store.async_load() or {}

    async def async_save(self):
        await self._store.async_save(self._data)

    def get_offset(self, entry_id):
        return float(self._data.get(entry_id, {}).get("offset", 0.0))

    def set_offset(self, entry_id, offset):
        self._data.setdefault(entry_id, {})
        self._data[entry_id]["offset"] = float(offset)
