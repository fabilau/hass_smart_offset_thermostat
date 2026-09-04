"""Pure config-entry migration helpers."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from .const import (
    CONF_CLIMATE,
    CONF_HVAC_MODE,
    CONF_MODES,
    CONF_PRESETS,
    CONF_ROOM_SENSOR,
    CONF_ROOM_TARGET,
    CONF_WINDOW_DELAY_SEC,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_SENSORS,
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_ROOM_TARGET,
    DEFAULT_WINDOW_DELAY_SEC,
    MODE_AWAY,
    MODE_PRESENT,
    MODE_SUMMER,
    MODE_WINTER,
    PRESET_HVAC_KEEP,
    default_presets,
)
from .control import normalize_entity_ids, normalize_presets

_LEGACY_PRESET_KEYS = (
    "mode_present_target",
    "mode_present_pause",
    "mode_away_target",
    "mode_away_pause",
    "mode_summer_target",
    "mode_summer_pause",
    "mode_winter_target",
    "mode_winter_pause",
)

_REQUIRED_SOURCE_KEYS = (CONF_CLIMATE, CONF_ROOM_SENSOR)


def _safe_float(value: Any, fallback: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return result if isfinite(result) else float(fallback)


def _safe_bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"", "0", "false", "no", "off", "disabled"}:
            return False
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return isfinite(float(value)) and float(value) != 0.0
        except (TypeError, ValueError):
            return fallback
    return fallback


def _first(
    mapping_a: dict[str, Any], mapping_b: dict[str, Any], key: str, fallback=None
):
    if key in mapping_a:
        return mapping_a[key]
    if key in mapping_b:
        return mapping_b[key]
    return fallback


def _entity_id(value: Any) -> str | None:
    """Return a usable entity ID from persisted config-entry data."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def config_entry_source(entry: Any, key: str) -> str | None:
    """Read a canonical or partially migrated source entity from an entry."""
    for payload in (
        getattr(entry, "data", {}),
        getattr(entry, "options", {}),
    ):
        if hasattr(payload, "get") and (source := _entity_id(payload.get(key))):
            return source
    return None


def select_source_entry_owner(entries: Any, entry: Any) -> Any:
    """Elect the oldest complete entry for one physical thermostat."""
    climate_source = config_entry_source(entry, CONF_CLIMATE)
    if climate_source is None:
        return entry
    candidates = [
        candidate
        for candidate in entries
        if getattr(candidate, "disabled_by", None) is None
        and config_entry_source(candidate, CONF_CLIMATE) == climate_source
        and config_entry_source(candidate, CONF_ROOM_SENSOR) is not None
    ]
    if not candidates:
        return entry

    # Never start a second controller beside one that is already active. This
    # also covers enabling an older repaired entry while a workaround entry is
    # still loaded; after the workaround is removed, the original can reload.
    loaded = [
        candidate
        for candidate in candidates
        if str(getattr(getattr(candidate, "state", None), "value", "")) == "loaded"
    ]
    if loaded:
        candidates = loaded

    def _order(candidate: Any) -> tuple[Any, ...]:
        created_at = getattr(candidate, "created_at", None)
        return (
            created_at is None,
            created_at,
            str(getattr(candidate, "entry_id", "")),
        )

    return min(candidates, key=_order)


def integration_disabled_entity_ids(
    entries: Any,
    entry_id: str,
) -> list[str]:
    """Return entities safe to restore after the 2.0 UI regression.

    Version 2.0.0/2.0.1 marked several existing controls and diagnostics as
    disabled by the integration. Home Assistant persists that initial default,
    so merely changing the entity class does not turn those entities back on.
    User-, device- and config-entry-disabled entities are deliberately ignored.
    The config-entry preference for newly added entities is only consulted when
    a registry row is first created. These rows already exist and were assigned
    the wrong integration default by 2.0.0/2.0.1, so the one-shot migration
    applies today's enabled-default contract to them. Future new rows continue
    to follow that Home Assistant preference.
    """
    recoverable: list[str] = []
    for registry_entry in entries:
        if getattr(registry_entry, "config_entry_id", None) != entry_id:
            continue
        disabled_by = getattr(registry_entry, "disabled_by", None)
        disabled_value = getattr(disabled_by, "value", disabled_by)
        if disabled_value != "integration":
            continue
        entity_id = getattr(registry_entry, "entity_id", None)
        if isinstance(entity_id, str) and entity_id:
            recoverable.append(entity_id)
    return recoverable


def _restore_required_sources(data: dict[str, Any], options: dict[str, Any]) -> None:
    """Move required source entities back to their canonical data payload.

    Config-entry source entities have always belonged in ``entry.data``. A
    partially applied or intermediate upgrade can nevertheless leave one in
    ``entry.options`` while already marking the entry as current. The
    controller indexes these keys from ``entry.data`` during startup, so such
    an entry otherwise fails before any of its existing entities are added.
    """
    for key in _REQUIRED_SOURCE_KEYS:
        source = _entity_id(data.get(key)) or _entity_id(options.get(key))
        if source is None:
            continue
        data[key] = source
        # Once a canonical value exists, discard a stale duplicate so future
        # option edits cannot silently diverge from the configured source.
        options.pop(key, None)


def _legacy_presets(
    data: dict[str, Any], options: dict[str, Any], fallback_target: float
) -> list[dict[str, Any]] | None:
    if not any(key in options or key in data for key in _LEGACY_PRESET_KEYS):
        return None
    specs = (
        (MODE_PRESENT, False, fallback_target),
        (MODE_AWAY, True, fallback_target - 4.0),
        (MODE_SUMMER, False, fallback_target),
        (MODE_WINTER, False, fallback_target),
    )
    presets: list[dict[str, Any]] = []
    for preset_id, default_pause, default_target in specs:
        target_key = f"mode_{preset_id}_target"
        pause_key = f"mode_{preset_id}_pause"
        presets.append(
            {
                "id": preset_id,
                "target": _safe_float(
                    _first(options, data, target_key, default_target), default_target
                ),
                "pause": _safe_bool(
                    _first(options, data, pause_key, default_pause), default_pause
                ),
                # The legacy integration never controlled HVAC mode. Keeping
                # the current physical mode is therefore the only
                # behavior-preserving upgrade.
                CONF_HVAC_MODE: PRESET_HVAC_KEEP,
            }
        )
    return presets


def migrate_config_entry_payload(
    data: dict[str, Any],
    options: dict[str, Any],
    version: int | None,
    minor_version: int | None = 0,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Return migrated copies and whether either payload changed.

    Unknown keys are deliberately preserved. The helper is idempotent and does
    not downgrade entries created by a newer integration version.
    """
    migrated_data = deepcopy(dict(data or {}))
    migrated_options = deepcopy(dict(options or {}))
    original_data = deepcopy(migrated_data)
    original_options = deepcopy(migrated_options)

    current_version = int(version or 1)
    current_minor = int(minor_version or 0)
    if current_version > CONFIG_ENTRY_VERSION or (
        current_version == CONFIG_ENTRY_VERSION
        and current_minor > CONFIG_ENTRY_MINOR_VERSION
    ):
        return migrated_data, migrated_options, False

    # Repair entries that were prematurely marked as 3.1 while one of their
    # required source selectors still lived in options. Schema 3.2 introduced
    # this payload repair; later minor schemas also revisit entries for
    # targeted registry/UI repairs.
    _restore_required_sources(migrated_data, migrated_options)

    # Single-window installations are normalized to the multiple selector.
    windows = _first(migrated_options, migrated_data, CONF_WINDOW_SENSORS)
    if not isinstance(windows, (str, list, tuple, dict)):
        legacy_window = _first(migrated_options, migrated_data, CONF_WINDOW_SENSOR)
        windows = legacy_window
    migrated_options[CONF_WINDOW_SENSORS] = normalize_entity_ids(windows)
    migrated_options.pop(CONF_WINDOW_SENSOR, None)
    migrated_options.pop("pause_entities", None)

    # v1 controlled windows immediately. v2 already used the 60 second runtime
    # default when the option was absent, so preserve each version's behavior.
    if CONF_WINDOW_DELAY_SEC not in migrated_options:
        migrated_options[CONF_WINDOW_DELAY_SEC] = (
            0 if current_version < 2 else DEFAULT_WINDOW_DELAY_SEC
        )

    room_target = _safe_float(
        _first(
            migrated_options,
            migrated_data,
            CONF_ROOM_TARGET,
            DEFAULT_ROOM_TARGET,
        ),
        DEFAULT_ROOM_TARGET,
    )

    source_presets = _first(migrated_options, migrated_data, CONF_PRESETS)
    if source_presets is None:
        source_presets = _first(migrated_options, migrated_data, CONF_MODES)
    if source_presets is None:
        source_presets = _legacy_presets(migrated_data, migrated_options, room_target)
    if source_presets is None:
        if current_version < 3:
            # Preserve the exact implicit v1/v2 defaults. In particular Away
            # was paused and Summer was active; changing either on upgrade can
            # unexpectedly start or stop heating.
            source_presets = [
                {
                    "id": MODE_PRESENT,
                    "target": room_target,
                    "pause": False,
                    CONF_HVAC_MODE: PRESET_HVAC_KEEP,
                },
                {
                    "id": MODE_AWAY,
                    "target": room_target - 4.0,
                    "pause": True,
                    CONF_HVAC_MODE: PRESET_HVAC_KEEP,
                },
                {
                    "id": MODE_SUMMER,
                    "target": room_target,
                    "pause": False,
                    CONF_HVAC_MODE: PRESET_HVAC_KEEP,
                },
                {
                    "id": MODE_WINTER,
                    "target": room_target,
                    "pause": False,
                    CONF_HVAC_MODE: PRESET_HVAC_KEEP,
                },
            ]
        else:
            source_presets = default_presets(room_target, PRESET_HVAC_KEEP)

    # The pre-v3 integration never changed the physical HVAC mode. Missing
    # values must therefore inherit the currently active mode, not force heat.
    migrated_options[CONF_PRESETS] = normalize_presets(
        source_presets,
        fallback_target=room_target,
        default_hvac_mode=PRESET_HVAC_KEEP,
    )
    migrated_options.pop(CONF_MODES, None)
    for key in _LEGACY_PRESET_KEYS:
        migrated_options.pop(key, None)

    changed = (
        migrated_data != original_data
        or migrated_options != original_options
        or current_version != CONFIG_ENTRY_VERSION
        or current_minor != CONFIG_ENTRY_MINOR_VERSION
    )
    return migrated_data, migrated_options, changed
