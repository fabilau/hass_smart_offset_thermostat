"""Persistent runtime state for Smart Offset Thermostat."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store

_STORAGE_VERSION = 1
_PAYLOAD_VERSION = 4
_STORAGE_KEY = "smart_offset_thermostat"


class OffsetStorage:
    """Store learned and user-controlled runtime values.

    The Home Assistant Store envelope remains at version 1. The payload has its
    own schema so installations using the original ``{entry_id: values}``
    layout can be upgraded without relying on a version-specific Store API.
    """

    def __init__(self, hass) -> None:
        self._store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._data: dict[str, Any] = {
            "schema_version": _PAYLOAD_VERSION,
            "entries": {},
            "recovery_aliases": {},
        }
        self._save_lock = asyncio.Lock()
        self._future_schema = False

    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        migrated = False

        raw_schema = raw.get("schema_version") if isinstance(raw, dict) else None
        try:
            schema_version = int(raw_schema) if raw_schema is not None else 1
        except (TypeError, ValueError):
            schema_version = 1
        if schema_version > _PAYLOAD_VERSION:
            # Never downgrade or rewrite a payload created by newer code.
            self._future_schema = True
            self._data = deepcopy(raw)
            if not isinstance(self._data.get("entries"), dict):
                self._data["entries"] = {}
            return

        if isinstance(raw, dict) and isinstance(raw.get("entries"), dict):
            entries = deepcopy(raw["entries"])
            raw_aliases = raw.get("recovery_aliases", {})
            recovery_aliases = (
                {
                    str(source): str(target)
                    for source, target in raw_aliases.items()
                    if isinstance(source, str)
                    and source
                    and isinstance(target, str)
                    and target
                    and source != target
                }
                if isinstance(raw_aliases, dict)
                else {}
            )
            migrated = raw.get("schema_version") != _PAYLOAD_VERSION
            migrated |= recovery_aliases != raw_aliases
        elif isinstance(raw, dict):
            # v1 payload: entry IDs were keys at the top level.
            entries = {
                str(entry_id): deepcopy(values)
                for entry_id, values in raw.items()
                if isinstance(values, dict) and entry_id != "schema_version"
            }
            recovery_aliases = {}
            migrated = bool(raw)
        else:
            entries = {}
            recovery_aliases = {}
            migrated = True

        for entry_id, values in list(entries.items()):
            if not isinstance(values, dict):
                entries[entry_id] = values = {}
                migrated = True
            original_values = deepcopy(values)
            if "preset" not in values and values.get("mode") is not None:
                values["preset"] = str(values["mode"])
                migrated = True
            if "mode" in values:
                values.pop("mode", None)
                migrated = True
            if "offsets" not in values:
                try:
                    legacy_offset = float(values.get("offset", 0.0))
                except (TypeError, ValueError):
                    legacy_offset = 0.0
                legacy_offset = legacy_offset if isfinite(legacy_offset) else 0.0
                # The legacy controller used one value in both directions.
                # Seed both regulated modes, then let them learn separately.
                values["offsets"] = {
                    "heat": legacy_offset,
                    "cool": legacy_offset,
                }
            # A legacy entry has no virtual HVAC state. Leaving it unset lets
            # the controller adopt the current physical state without a
            # dangerous heat/cool change during the upgrade.
            values.setdefault("change_count", 0)
            values.setdefault("manual_change_count", 0)
            if values != original_values:
                migrated = True

        self._data = {
            "schema_version": _PAYLOAD_VERSION,
            "entries": entries,
            "recovery_aliases": recovery_aliases,
        }
        if migrated:
            await self.async_save()

    async def async_save(self) -> None:
        if self._future_schema:
            return
        async with self._save_lock:
            await self._store.async_save(self._data)

    def _entry(self, entry_id: str) -> dict[str, Any]:
        entries = self._data.setdefault("entries", {})
        return entries.setdefault(entry_id, {})

    def get_offset(self, entry_id: str, hvac_mode: str | None = None) -> float:
        values = self._entry(entry_id)
        offsets = values.get("offsets")
        if hvac_mode and isinstance(offsets, dict):
            raw_value = offsets.get(str(hvac_mode), 0.0)
        else:
            raw_value = values.get("offset", 0.0)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.0
        return value if isfinite(value) else 0.0

    def set_offset(
        self, entry_id: str, offset: float, hvac_mode: str | None = None
    ) -> None:
        values = self._entry(entry_id)
        if hvac_mode:
            offsets = values.setdefault("offsets", {})
            if not isinstance(offsets, dict):
                offsets = values["offsets"] = {}
            offsets[str(hvac_mode)] = float(offset)
        else:
            values["offset"] = float(offset)

    def get_preset(self, entry_id: str) -> str | None:
        preset = self._entry(entry_id).get("preset")
        return str(preset) if preset is not None else None

    def set_preset(self, entry_id: str, preset: str) -> None:
        self._entry(entry_id)["preset"] = str(preset)

    # Compatibility wrappers for the pre-v2 controller and legacy select.
    def get_mode(self, entry_id: str) -> str | None:
        return self.get_preset(entry_id)

    def set_mode(self, entry_id: str, mode: str) -> None:
        self.set_preset(entry_id, mode)

    def get_hvac_mode(self, entry_id: str) -> str | None:
        value = self._entry(entry_id).get("hvac_mode")
        return str(value) if value else None

    def set_hvac_mode(self, entry_id: str, hvac_mode: str) -> None:
        values = self._entry(entry_id)
        mode = str(hvac_mode)
        values["hvac_mode"] = mode
        if mode != "off":
            values["last_non_off_hvac_mode"] = mode

    def get_last_non_off_hvac_mode(self, entry_id: str) -> str | None:
        value = self._entry(entry_id).get("last_non_off_hvac_mode")
        if not value or str(value) == "off":
            return None
        return str(value)

    def get_counter(self, entry_id: str, key: str) -> int:
        try:
            return max(0, int(self._entry(entry_id).get(key, 0)))
        except (TypeError, ValueError):
            return 0

    def increment_counter(self, entry_id: str, key: str) -> int:
        value = self.get_counter(entry_id, key) + 1
        self._entry(entry_id)[key] = value
        return value

    def validate_entry_adoption(self, old_entry_id: str, new_entry_id: str) -> None:
        """Raise before registry writes if runtime state cannot move safely."""
        if old_entry_id == new_entry_id:
            return
        if self._future_schema:
            raise RuntimeError("Cannot recover an entry from a future storage schema")
        entries = self._data.setdefault("entries", {})
        aliases = self._data.setdefault("recovery_aliases", {})
        if (
            old_entry_id in entries
            and new_entry_id in entries
            and entries[old_entry_id] != entries[new_entry_id]
            and aliases.get(old_entry_id) != new_entry_id
        ):
            raise RuntimeError(
                "Recovery storage contains conflicting old and new entry data"
            )

    async def async_adopt_entry(self, old_entry_id: str, new_entry_id: str) -> bool:
        """Move learned runtime state to a recovered config entry.

        The operation is idempotent so setup can resume safely after an
        interrupted registry recovery. A future payload schema is deliberately
        rejected instead of being rewritten by older code.
        """
        if old_entry_id == new_entry_id:
            return False
        self.validate_entry_adoption(old_entry_id, new_entry_id)

        entries = self._data.setdefault("entries", {})
        old_values = entries.get(old_entry_id)
        if old_values is None:
            return False
        had_new_entry = new_entry_id in entries
        previous_new_values = deepcopy(entries.get(new_entry_id))
        if not had_new_entry:
            entries[new_entry_id] = deepcopy(old_values)
        entries.pop(old_entry_id)
        try:
            await self.async_save()
        except (Exception, asyncio.CancelledError):
            entries[old_entry_id] = old_values
            if had_new_entry:
                entries[new_entry_id] = previous_new_values
            else:
                entries.pop(new_entry_id, None)
            raise
        return True

    async def async_prepare_entry_adoption(
        self, old_entry_id: str, new_entry_id: str
    ) -> bool:
        """Copy runtime state while retaining the crash-safe old key."""
        if old_entry_id == new_entry_id:
            return False
        self.validate_entry_adoption(old_entry_id, new_entry_id)

        entries = self._data.setdefault("entries", {})
        old_values = entries.get(old_entry_id)
        if old_values is None or new_entry_id in entries:
            return False
        entries[new_entry_id] = deepcopy(old_values)
        try:
            await self.async_save()
        except (Exception, asyncio.CancelledError):
            entries.pop(new_entry_id, None)
            raise
        return True

    async def async_finalize_entry_adoption(
        self, old_entry_id: str, new_entry_id: str
    ) -> bool:
        """Persist a crash-safe alias after registry recovery was verified.

        The old values deliberately remain as a recovery checkpoint. Home
        Assistant persists config-entry updates asynchronously, so deleting
        them in the same setup pass could lose learned data if power fails
        after this Store save but before the cleared recovery markers reach
        disk. The checkpoint is removed with the recovered entry on an
        intentional uninstall.
        """
        if old_entry_id == new_entry_id:
            return False
        self.validate_entry_adoption(old_entry_id, new_entry_id)

        entries = self._data.setdefault("entries", {})
        if old_entry_id not in entries:
            return False
        if new_entry_id not in entries:
            raise RuntimeError("Recovery storage was not prepared")
        aliases = self._data.setdefault("recovery_aliases", {})
        if aliases.get(old_entry_id) == new_entry_id:
            return False
        previous_alias = aliases.get(old_entry_id)
        aliases[old_entry_id] = new_entry_id
        try:
            await self.async_save()
        except (Exception, asyncio.CancelledError):
            if previous_alias is None:
                aliases.pop(old_entry_id, None)
            else:
                aliases[old_entry_id] = previous_alias
            raise
        return True

    async def async_remove_entry(self, entry_id: str) -> None:
        entries = self._data.setdefault("entries", {})
        aliases = self._data.setdefault("recovery_aliases", {})
        related = {entry_id}
        # Follow reverse recovery links so intentionally deleting the current
        # integration also removes every retained checkpoint from A → B → C.
        while True:
            ancestors = {
                str(source)
                for source, target in aliases.items()
                if str(target) in related
            }
            if ancestors <= related:
                break
            related.update(ancestors)

        changed = False
        for related_entry_id in related:
            changed |= entries.pop(related_entry_id, None) is not None
        for source, target in list(aliases.items()):
            if source in related or target in related:
                aliases.pop(source, None)
                changed = True
        if changed:
            await self.async_save()
