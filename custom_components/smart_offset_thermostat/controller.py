"""Deterministic controller for Smart Offset Thermostat."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from math import exp, isfinite
from typing import Any

from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_BOOST_DURATION_SEC,
    CONF_CLIMATE,
    CONF_CONTROL_GAIN,
    CONF_COOLDOWN_SEC,
    CONF_DEADBAND,
    CONF_ENABLE_LEARNING,
    CONF_HVAC_MODE,
    CONF_INTERVAL_SEC,
    CONF_LEARN_RATE,
    CONF_MANUAL_DELAY_SEC,
    CONF_MANUAL_TARGET_SYNC,
    CONF_MODES,
    CONF_PAUSE_ON_HVAC_OFF,
    CONF_PRESETS,
    CONF_ROOM_SENSOR,
    CONF_ROOM_TARGET,
    CONF_STEP_MAX,
    CONF_STEP_MIN,
    CONF_STUCK_ENABLE,
    CONF_STUCK_MIN_DROP,
    CONF_STUCK_SECONDS,
    CONF_STUCK_STEP,
    CONF_TRV_MAX,
    CONF_TRV_MIN,
    CONF_WINDOW_DELAY_SEC,
    CONF_WINDOW_SENSOR,
    CONF_WINDOW_SENSORS,
    DEFAULT_BOOST_DURATION_SEC,
    DEFAULT_CONTROL_GAIN,
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_DEADBAND,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_INTERVAL_SEC,
    DEFAULT_LEARN_RATE,
    DEFAULT_MANUAL_DELAY_SEC,
    DEFAULT_ROOM_TARGET,
    DEFAULT_STEP_MAX,
    DEFAULT_STEP_MIN,
    DEFAULT_STUCK_ENABLE,
    DEFAULT_STUCK_MIN_DROP,
    DEFAULT_STUCK_SECONDS,
    DEFAULT_STUCK_STEP,
    DEFAULT_TRV_MAX,
    DEFAULT_TRV_MIN,
    DEFAULT_WINDOW_DELAY_SEC,
    PASSIVE_HVAC_MODES,
    PRESET_HVAC_KEEP,
    PRESET_HVAC_MODES,
    REGULATED_HVAC_MODES,
    SIGNAL_UPDATE,
    default_presets,
)
from .control import (
    calculate_setpoint,
    command_matches,
    manual_target_from_delta,
    normalize_entity_ids,
    normalize_presets,
)
from .temperature import delta_to_celsius, from_celsius, to_celsius

LOGGER = logging.getLogger(__name__)

STABLE_LEARN_SECONDS = 900
STABLE_LEARN_ALPHA = 0.25
MANUAL_COMMAND_TTL_SECONDS = 120.0
COMMAND_TRANSITION_WINDOW_SECONDS = 30.0
STATISTICS_TIME_CONSTANT_SECONDS = 6 * 3600.0
MAX_OFFSET = 10.0


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _mode_value(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


@dataclass(frozen=True)
class _PendingTemperatureCommand:
    value: float
    issued_at: float
    context_id: str


class SmartOffsetController:
    """Coordinate physical climate state and the virtual room thermostat."""

    def __init__(self, hass, entry, storage) -> None:
        self.hass = hass
        self.entry = entry
        self.storage = storage

        self.last_set: float | None = None
        self.last_confirmed_setpoint: float | None = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error: float | None = None
        self.last_target_trv: float | None = None
        self.last_correction = 0.0
        self.change_count = storage.get_counter(entry.entry_id, "change_count")
        self.manual_change_count = storage.get_counter(
            entry.entry_id, "manual_change_count"
        )

        self.mean_absolute_error: float | None = None
        self.comfort_score: float | None = None
        self.temperature_trend: float | None = None
        self.control_output: float | None = None
        self._statistics_updated_at: float | None = None
        self._last_stat_room_temperature: float | None = None
        self._last_stat_room_time: float | None = None

        self.boost_active = False
        self.boost_until = 0.0
        self.window_is_open = False
        self.window_state_unknown = False
        self.pause_active = False
        self.mode = storage.get_preset(entry.entry_id)

        self._started = False
        self._stopped = False
        self._tick_lock = asyncio.Lock()
        self._control_requested = False
        self._force_next_control = False
        self._trigger_reasons: set[str] = set()

        self._interval_unsub: Callable[[], None] | None = None
        self._interval_seconds: int | None = None
        self._room_unsub: Callable[[], None] | None = None
        self._climate_unsub: Callable[[], None] | None = None
        self._window_unsub: Callable[[], None] | None = None
        self._window_entities: tuple[str, ...] = ()
        self._window_delay_unsub: Callable[[], None] | None = None
        self._manual_delay_unsub: Callable[[], None] | None = None
        self._boost_unsub: Callable[[], None] | None = None

        self._window_raw_open = False
        self._window_open_since: float | None = None
        self._window_setback_active = False
        self._override_was_active = False
        self._rebase_required = False

        self._last_room_target: float | None = None
        self._last_room_state_updated: Any = None
        self._last_learning_time: float | None = None
        self._learning_block_until = 0.0

        # Explicit initialization fixes issue #14's startup/deadband crash.
        self._stable_since: float | None = None
        self._stable_target: float | None = None
        self._stable_last_set: float | None = None

        self._last_seen_device_target: float | None = None
        self._last_climate_context_id: str | None = None
        self._last_climate_context_user_id: str | None = None
        self._last_climate_context_parent_id: str | None = None
        self._pending_commands: deque[_PendingTemperatureCommand] = deque(maxlen=8)
        self._manual_pending_device_target: float | None = None
        self._manual_anchor_device_target: float | None = None
        self._manual_hold_until = 0.0

        self._stuck_active = False
        self._stuck_ref_temp: float | None = None
        self._stuck_ref_time: float | None = None
        self._stuck_bias = 0.0
        self._preset_hvac_snapshot = self._preset_hvac_modes()

    def opt(self, key: str) -> Any:
        """Read an option while preserving explicit false and zero values."""
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        from .const import DEFAULTS

        return DEFAULTS.get(key)

    def _number(self, key: str, default: float) -> float:
        value = self.opt(key)
        try:
            result = float(default if value is None else value)
        except (TypeError, ValueError):
            return float(default)
        return result if isfinite(result) else float(default)

    def _integer(self, key: str, default: int) -> int:
        value = self.opt(key)
        try:
            return int(default if value is None else value)
        except (TypeError, ValueError, OverflowError):
            return int(default)

    def _system_temperature_unit(self) -> str:
        try:
            return str(self.hass.config.units.temperature_unit)
        except AttributeError:
            return str(UnitOfTemperature.CELSIUS)

    def current_room_temperature(self) -> float | None:
        """Return the external room temperature in canonical Celsius."""
        room = self.hass.states.get(self.entry.data.get(CONF_ROOM_SENSOR))
        if room is None:
            return None
        unit = str(
            room.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            or self._system_temperature_unit()
        )
        return to_celsius(room.state, unit)

    def target_temperature_limits(self) -> tuple[float, float]:
        """Return physical target limits in canonical Celsius."""
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        if climate is None:
            return 5.0, 35.0
        return self._target_limits(climate)

    def target_temperature_step(self) -> float:
        """Return the physical target step as a Celsius delta."""
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        if climate is None:
            return DEFAULT_STEP_MIN
        return self._device_limits(climate)[2]

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    # ---------------------------------------------------------------------
    # Presets and backward-compatible mode API
    # ---------------------------------------------------------------------
    def _get_presets(self) -> list[dict[str, Any]]:
        raw = self.opt(CONF_PRESETS)
        if raw is None:
            raw = self.opt(CONF_MODES)
        fallback_target = self._number(CONF_ROOM_TARGET, DEFAULT_ROOM_TARGET)
        if raw is None:
            raw = default_presets(fallback_target)
        return normalize_presets(raw, fallback_target, "heat")

    def get_preset_ids(self) -> list[str]:
        return [str(item["id"]) for item in self._get_presets()]

    def _preset_hvac_modes(self) -> dict[str, str]:
        return {
            str(item["id"]): str(item.get(CONF_HVAC_MODE, PRESET_HVAC_KEEP))
            for item in self._get_presets()
        }

    def get_preset(self) -> str:
        preset_ids = self.get_preset_ids()
        stored = self.storage.get_preset(self.entry.entry_id)
        if stored in preset_ids:
            return str(stored)
        return preset_ids[0] if preset_ids else "present"

    def _preset_settings(self, preset: str | None = None) -> dict[str, Any]:
        current = preset or self.get_preset()
        for item in self._get_presets():
            if item["id"] == current:
                return item
        return {
            "id": current,
            "target": self._number(CONF_ROOM_TARGET, DEFAULT_ROOM_TARGET),
            "pause": False,
            CONF_HVAC_MODE: "heat",
        }

    def get_preset_target(self, preset: str | None = None) -> float:
        return float(self._preset_settings(preset)["target"])

    def _set_preset_target_unlocked(
        self, target: float, preset: str | None = None
    ) -> bool:
        preset_id = preset or self.get_preset()
        presets = self._get_presets()
        for item in presets:
            if item["id"] == preset_id:
                item["target"] = float(target)
                break
        else:
            return False
        options = dict(self.entry.options)
        options[CONF_PRESETS] = presets
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        return True

    async def set_preset_target(self, target: float, preset: str | None = None) -> None:
        """Persist a room target without racing a running control pass."""
        async with self._tick_lock:
            updated = self._set_preset_target_unlocked(target, preset)
            if updated:
                self._reset_dynamic_state(rebase=True)
                self._block_learning_for_settle()
        if updated:
            await self.trigger_once(force=True, reason="virtual_target")

    async def set_preset(self, preset: str) -> None:
        async with self._tick_lock:
            if preset not in self.get_preset_ids():
                raise ValueError(f"Unknown preset: {preset}")
            settings = self._preset_settings(preset)
            preset_hvac_mode = str(settings.get(CONF_HVAC_MODE, PRESET_HVAC_KEEP))
            if preset_hvac_mode != PRESET_HVAC_KEEP:
                if not await self._set_hvac_mode(preset_hvac_mode, persist=False):
                    raise HomeAssistantError(
                        f"Could not apply HVAC mode {preset_hvac_mode}"
                    )
                self.storage.set_hvac_mode(self.entry.entry_id, preset_hvac_mode)
            self.storage.set_preset(self.entry.entry_id, preset)
            self.mode = preset
            await self.storage.async_save()
            self._reset_dynamic_state(rebase=True)
            self._block_learning_for_settle()
        await self.trigger_once(force=True, reason="preset")

    # Legacy mode-select compatibility.
    def _get_modes(self) -> list[dict[str, Any]]:
        return self._get_presets()

    def get_mode_ids(self) -> list[str]:
        return self.get_preset_ids()

    def get_mode(self) -> str:
        return self.get_preset()

    def get_mode_target(self, mode: str | None = None) -> float:
        return self.get_preset_target(mode)

    async def set_mode(self, mode: str) -> None:
        await self.set_preset(mode)

    async def set_mode_target(self, target: float, mode: str | None = None) -> None:
        await self.set_preset_target(target, mode)

    # ---------------------------------------------------------------------
    # HVAC API
    # ---------------------------------------------------------------------
    def _physical_hvac_modes(self) -> list[str]:
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        raw = climate.attributes.get("hvac_modes", []) if climate else []
        if isinstance(raw, str):
            raw = [raw]
        result = [_mode_value(item) for item in raw]
        current = _mode_value(climate.state) if climate else ""
        if current and current not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            result.append(current)
        return list(dict.fromkeys(mode for mode in result if mode))

    def available_hvac_modes(self) -> list[str]:
        physical = self._physical_hvac_modes()
        supported = [
            mode
            for mode in PRESET_HVAC_MODES
            if mode != PRESET_HVAC_KEEP and mode in physical
        ]
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        try:
            features = int(
                climate.attributes.get("supported_features", 0) if climate else 0
            )
        except (TypeError, ValueError):
            features = 0
        off_capable = "off" in physical or bool(
            features & ClimateEntityFeature.TURN_OFF
        )
        if not off_capable:
            supported = [mode for mode in supported if mode != "off"]
        elif "off" not in supported:
            supported.insert(0, "off")
        else:
            supported = ["off", *[mode for mode in supported if mode != "off"]]
        return list(dict.fromkeys(supported))

    def get_hvac_mode(self) -> str:
        mode = self.storage.get_hvac_mode(self.entry.entry_id)
        available = self.available_hvac_modes()
        if mode in available:
            return str(mode)
        climate = self.hass.states.get(self.entry.data.get(CONF_CLIMATE))
        physical_mode = _mode_value(climate.state) if climate else ""
        if physical_mode in available:
            return physical_mode
        return next((item for item in available if item != "off"), "off")

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        mode = _mode_value(hvac_mode)
        async with self._tick_lock:
            if mode not in self.available_hvac_modes():
                raise ValueError(f"Unsupported HVAC mode: {mode}")
            if not await self._set_hvac_mode(mode, persist=True):
                raise HomeAssistantError(f"Could not apply HVAC mode {mode}")
            if mode == "off":
                self._cancel_boost(mark_rebase=False)
                self._clear_manual_candidate()
                self._reset_dynamic_state(rebase=False)
            else:
                self._reset_dynamic_state(rebase=True)
            self._block_learning_for_settle()
        await self.trigger_once(force=True, reason="hvac_mode")

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode("off")

    async def async_turn_on(self) -> None:
        mode = self.storage.get_last_non_off_hvac_mode(self.entry.entry_id)
        if mode not in self.available_hvac_modes() or mode == "off":
            mode = next(
                (item for item in self.available_hvac_modes() if item != "off"),
                None,
            )
        if mode is None:
            raise HomeAssistantError("No regulated HVAC mode is available")
        await self.async_set_hvac_mode(mode)

    async def _set_hvac_mode(self, mode: str, *, persist: bool) -> bool:
        climate_entity = self.entry.data[CONF_CLIMATE]
        climate = self.hass.states.get(climate_entity)
        current = _mode_value(climate.state) if climate else ""
        if current != mode:
            try:
                physical_modes = self._physical_hvac_modes()
                if mode == "off" and "off" not in physical_modes:
                    await self.hass.services.async_call(
                        "climate",
                        "turn_off",
                        {"entity_id": climate_entity},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": climate_entity, "hvac_mode": mode},
                        blocking=True,
                    )
            except Exception:  # Home Assistant service errors vary by platform.
                LOGGER.exception(
                    "Failed to set HVAC mode %s on %s", mode, climate_entity
                )
                self.last_action = "service_error"
                self._notify()
                return False
            self._reset_dynamic_state(rebase=mode != "off")
            self._block_learning_for_settle()

        if mode == "off":
            self._cancel_boost(mark_rebase=False)
            self._clear_manual_candidate()
            self._reset_dynamic_state(rebase=False)

        # Commit virtual state only after the physical command succeeded.
        if persist:
            self.storage.set_hvac_mode(self.entry.entry_id, mode)
            await self.storage.async_save()

        self.last_action = "hvac_mode_set"
        self._notify()
        return True

    # ---------------------------------------------------------------------
    # Lifecycle and event coalescing
    # ---------------------------------------------------------------------
    async def async_start(self) -> None:
        self._stopped = False
        self._started = True
        preset = self.get_preset()
        storage_changed = False
        if self.storage.get_preset(self.entry.entry_id) != preset:
            self.storage.set_preset(self.entry.entry_id, preset)
            storage_changed = True
        if storage_changed:
            await self.storage.async_save()
        self.mode = preset
        self._ensure_listeners()
        self._schedule_interval()
        await self.trigger_once(force=True, reason="startup")

    async def async_stop(self) -> None:
        self._stopped = True
        async with self._tick_lock:
            self._started = False
            self._cancel_boost(mark_rebase=False)
            self._cancel_window_delay()
            self._cancel_manual_delay()
            for attribute in (
                "_interval_unsub",
                "_room_unsub",
                "_climate_unsub",
                "_window_unsub",
            ):
                unsubscribe = getattr(self, attribute)
                if unsubscribe is not None:
                    try:
                        unsubscribe()
                    except Exception:
                        LOGGER.debug("Listener cleanup failed", exc_info=True)
                    setattr(self, attribute, None)
            self._window_entities = ()

    async def async_options_updated(self) -> None:
        """Apply option changes without a full config-entry reload."""
        async with self._tick_lock:
            current_preset = self.get_preset()
            stored_preset = self.storage.get_preset(self.entry.entry_id)
            preset_hvac_modes = self._preset_hvac_modes()
            desired_mode = preset_hvac_modes.get(current_preset, PRESET_HVAC_KEEP)
            preset_selection_changed = stored_preset != current_preset
            preset_mode_changed = (
                self._preset_hvac_snapshot.get(current_preset) != desired_mode
            )
            if (
                (preset_selection_changed or preset_mode_changed)
                and desired_mode != PRESET_HVAC_KEEP
                and desired_mode in self.available_hvac_modes()
                and not await self._set_hvac_mode(desired_mode, persist=True)
            ):
                return
            if preset_selection_changed:
                self.storage.set_preset(self.entry.entry_id, current_preset)
                await self.storage.async_save()
            self._preset_hvac_snapshot = preset_hvac_modes
            self._ensure_window_listener()
            interval = max(30, self._integer(CONF_INTERVAL_SEC, DEFAULT_INTERVAL_SEC))
            if interval != self._interval_seconds:
                self._schedule_interval()
            self._reset_dynamic_state(rebase=True)
            self._block_learning_for_settle()
        await self.trigger_once(force=True, reason="options")

    async def trigger_once(self, force: bool = False, reason: str = "event") -> None:
        """Coalesce concurrent callbacks into deterministic serial runs."""
        if self._stopped:
            return
        self._control_requested = True
        self._force_next_control = self._force_next_control or force
        self._trigger_reasons.add(reason)
        if self._tick_lock.locked():
            return

        async with self._tick_lock:
            while self._control_requested and not self._stopped:
                self._control_requested = False
                run_force = self._force_next_control
                reasons = tuple(sorted(self._trigger_reasons))
                self._force_next_control = False
                self._trigger_reasons.clear()
                await self._async_control(run_force, reasons)

    async def _tick(self, _now) -> None:
        await self.trigger_once(reason="interval")

    def _schedule_interval(self) -> None:
        if self._interval_unsub is not None:
            self._interval_unsub()
        interval = max(30, self._integer(CONF_INTERVAL_SEC, DEFAULT_INTERVAL_SEC))
        self._interval_seconds = interval
        self._interval_unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=interval)
        )

    def _ensure_listeners(self) -> None:
        climate_entity = self.entry.data[CONF_CLIMATE]
        room_entity = self.entry.data[CONF_ROOM_SENSOR]

        if self._room_unsub is None:

            async def _room_changed(event) -> None:
                old = event.data.get("old_state")
                new = event.data.get("new_state")
                if old is None or new is None or old.state != new.state:
                    await self.trigger_once(reason="room_temperature")

            self._room_unsub = async_track_state_change_event(
                self.hass, [room_entity], _room_changed
            )

        if self._climate_unsub is None:

            async def _climate_changed(event) -> None:
                old = event.data.get("old_state")
                new = event.data.get("new_state")
                if new is None:
                    await self.trigger_once(reason="climate_unavailable")
                    return
                old_target = old.attributes.get(ATTR_TEMPERATURE) if old else None
                new_target = new.attributes.get(ATTR_TEMPERATURE)
                old_mode = old.state if old else None
                control_changed = old_target != new_target or old_mode != new.state
                old_action = old.attributes.get("hvac_action") if old else None
                action_changed = old_action != new.attributes.get("hvac_action")
                if control_changed:
                    context = getattr(new, "context", None)
                    self._last_climate_context_id = getattr(context, "id", None)
                    self._last_climate_context_user_id = getattr(
                        context, "user_id", None
                    )
                    self._last_climate_context_parent_id = getattr(
                        context, "parent_id", None
                    )
                    await self.trigger_once(reason="physical_climate")
                elif action_changed:
                    # HVAC action is display state, not a control input. Refresh
                    # the virtual climate card immediately without a control pass.
                    self._notify()

            self._climate_unsub = async_track_state_change_event(
                self.hass, [climate_entity], _climate_changed
            )

        self._ensure_window_listener()

    def _ensure_window_listener(self) -> None:
        configured = self.opt(CONF_WINDOW_SENSORS)
        if configured is None:
            configured = self.opt(CONF_WINDOW_SENSOR)
        entities = tuple(normalize_entity_ids(configured))
        if entities == self._window_entities:
            return
        if self._window_unsub is not None:
            self._window_unsub()
            self._window_unsub = None
        self._window_entities = entities
        if not entities:
            return

        async def _window_changed(_event) -> None:
            was_open = self._window_raw_open
            is_open, _unknown = self._read_window_state()
            now = self.hass.loop.time()
            if is_open and not was_open:
                self._window_open_since = now
            elif not is_open and was_open:
                self._window_open_since = None
                self._rebase_required = True
                self._cancel_window_delay()
            self._window_raw_open = is_open
            await self.trigger_once(force=True, reason="window")

        self._window_unsub = async_track_state_change_event(
            self.hass, list(entities), _window_changed
        )

    # ---------------------------------------------------------------------
    # Timed overrides
    # ---------------------------------------------------------------------
    def _cancel_window_delay(self) -> None:
        if self._window_delay_unsub is not None:
            self._window_delay_unsub()
            self._window_delay_unsub = None

    def _schedule_window_delay(self, delay: float) -> None:
        self._cancel_window_delay()
        if delay <= 0:
            return

        async def _fire(_now) -> None:
            self._window_delay_unsub = None
            await self.trigger_once(force=True, reason="window_delay")

        self._window_delay_unsub = async_call_later(self.hass, delay, _fire)

    def _cancel_manual_delay(self) -> None:
        if self._manual_delay_unsub is not None:
            self._manual_delay_unsub()
            self._manual_delay_unsub = None

    def _schedule_manual_delay(self, delay: float) -> None:
        self._cancel_manual_delay()
        if delay <= 0:
            return

        async def _fire(_now) -> None:
            self._manual_delay_unsub = None
            await self.trigger_once(force=True, reason="manual_delay")

        self._manual_delay_unsub = async_call_later(self.hass, delay, _fire)

    def _cancel_boost(self, *, mark_rebase: bool = True) -> None:
        was_active = self.boost_active
        if self._boost_unsub is not None:
            self._boost_unsub()
            self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0
        if was_active and mark_rebase:
            self._rebase_required = True

    async def stop_boost(self) -> None:
        async with self._tick_lock:
            self._cancel_boost(mark_rebase=True)
            self._block_learning_for_settle()
        await self.trigger_once(force=True, reason="boost_end")

    async def start_boost(self) -> None:
        duration = max(
            30,
            min(
                self._integer(CONF_BOOST_DURATION_SEC, DEFAULT_BOOST_DURATION_SEC),
                3600,
            ),
        )
        async with self._tick_lock:
            self._cancel_boost(mark_rebase=False)
            self.boost_active = True
            self.boost_until = self.hass.loop.time() + duration
            self._block_learning_for_settle()

            async def _end(_now) -> None:
                async with self._tick_lock:
                    self._boost_unsub = None
                    self.boost_active = False
                    self.boost_until = 0.0
                    self._rebase_required = True
                    self._block_learning_for_settle()
                await self.trigger_once(force=True, reason="boost_end")

            self._boost_unsub = async_call_later(self.hass, duration, _end)
        await self.trigger_once(force=True, reason="boost")

    async def reset_offset(self) -> None:
        async with self._tick_lock:
            self.storage.set_offset(self.entry.entry_id, 0.0, self.get_hvac_mode())
            await self.storage.async_save()
            self.last_action = "reset_offset"
            self._reset_dynamic_state(rebase=True)
            self._block_learning_for_settle()
        await self.trigger_once(force=True, reason="reset_offset")

    # ---------------------------------------------------------------------
    # State helpers
    # ---------------------------------------------------------------------
    def _reset_dynamic_state(self, *, rebase: bool) -> None:
        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None
        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0
        if rebase:
            self._rebase_required = True

    def _block_learning_for_settle(self) -> None:
        settle = max(
            float(self._interval_seconds or DEFAULT_INTERVAL_SEC) * 2.0,
            self._number(CONF_COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC),
        )
        self._learning_block_until = max(
            self._learning_block_until,
            self.hass.loop.time() + settle,
        )

    def _clear_manual_candidate(self) -> None:
        self._manual_pending_device_target = None
        self._manual_anchor_device_target = None
        self._manual_hold_until = 0.0
        self._cancel_manual_delay()

    def _read_window_state(self) -> tuple[bool, bool]:
        if not self._window_entities:
            return False, False
        unknown = False
        for entity_id in self._window_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                unknown = True
                continue
            if str(state.state).lower() in ("on", "open", "true", "1"):
                return True, unknown
        # Fail safe: an already-open window remains open while its sensor is
        # temporarily unavailable; a previously closed one remains closed.
        return (self._window_raw_open if unknown else False), unknown

    def _window_setback(self, now: float) -> bool:
        is_open, unknown = self._read_window_state()
        self.window_state_unknown = unknown
        if is_open and not self._window_raw_open:
            self._window_open_since = now
        elif not is_open and self._window_raw_open:
            self._window_open_since = None
            self._rebase_required = True
            self._cancel_window_delay()
        self._window_raw_open = is_open
        self.window_is_open = is_open

        if not is_open:
            return False
        if self._window_open_since is None:
            self._window_open_since = now
        delay = max(
            0,
            min(
                self._integer(CONF_WINDOW_DELAY_SEC, DEFAULT_WINDOW_DELAY_SEC),
                24 * 3600,
            ),
        )
        elapsed = now - self._window_open_since
        if delay > 0 and elapsed < delay:
            if self._window_delay_unsub is None:
                self._schedule_window_delay(delay - elapsed)
            return False
        self._cancel_window_delay()
        return True

    def _device_limits(self, climate) -> tuple[float, float, float]:
        system_unit = self._system_temperature_unit()
        physical_min = to_celsius(climate.attributes.get("min_temp"), system_unit)
        physical_max = to_celsius(climate.attributes.get("max_temp"), system_unit)
        physical_step = delta_to_celsius(
            climate.attributes.get("target_temp_step"), system_unit
        )

        configured_min = (
            self._number(CONF_TRV_MIN, DEFAULT_TRV_MIN)
            if CONF_TRV_MIN in self.entry.options or CONF_TRV_MIN in self.entry.data
            else (physical_min if physical_min is not None else DEFAULT_TRV_MIN)
        )
        configured_max = (
            self._number(CONF_TRV_MAX, DEFAULT_TRV_MAX)
            if CONF_TRV_MAX in self.entry.options or CONF_TRV_MAX in self.entry.data
            else (physical_max if physical_max is not None else DEFAULT_TRV_MAX)
        )
        minimum = (
            max(configured_min, physical_min)
            if physical_min is not None
            else configured_min
        )
        maximum = (
            min(configured_max, physical_max)
            if physical_max is not None
            else configured_max
        )
        if maximum <= minimum:
            minimum = physical_min if physical_min is not None else DEFAULT_TRV_MIN
            maximum = physical_max if physical_max is not None else DEFAULT_TRV_MAX
        configured_step = max(0.01, self._number(CONF_STEP_MIN, DEFAULT_STEP_MIN))
        device_step = max(configured_step, physical_step or configured_step)
        return float(minimum), float(maximum), float(device_step)

    def _target_limits(self, climate) -> tuple[float, float]:
        system_unit = self._system_temperature_unit()
        minimum = to_celsius(climate.attributes.get("min_temp"), system_unit)
        maximum = to_celsius(climate.attributes.get("max_temp"), system_unit)
        return (
            minimum if minimum is not None else 5.0,
            maximum if maximum is not None else 35.0,
        )

    def _cleanup_pending_commands(self, now: float) -> None:
        while (
            self._pending_commands
            and (now - self._pending_commands[0].issued_at) > MANUAL_COMMAND_TTL_SECONDS
        ):
            self._pending_commands.popleft()

    def _is_command_echo(
        self,
        observed: float,
        device_step: float,
        now: float,
        context_id: str | None,
        context_parent_id: str | None,
    ) -> bool:
        self._cleanup_pending_commands(now)
        matched = False
        remaining: deque[_PendingTemperatureCommand] = deque(maxlen=8)
        for command in self._pending_commands:
            exact = command_matches(observed, command.value, device_step)
            same_context = bool(
                (context_id and context_id == command.context_id)
                or (context_parent_id and context_parent_id == command.context_id)
            )
            if not matched and (exact or same_context):
                matched = True
                # Keep a contextual intermediate acknowledgement until the
                # final target arrives with the same service context.
                if not exact:
                    remaining.append(command)
                continue
            remaining.append(command)
        self._pending_commands = remaining
        return matched

    def _is_command_transition(
        self,
        observed: float,
        previous: float | None,
        device_step: float,
        now: float,
        context_id: str | None,
        context_user_id: str | None,
        context_parent_id: str | None,
    ) -> bool:
        """Recognize a short, monotonic device acknowledgement.

        Home Assistant assigns every state a context ID, including device
        updates which do not propagate the service-call context.  Therefore a
        fresh ID alone cannot distinguish a physical acknowledgement from a
        manual change.  A user ID or an unrelated parent context can.
        """
        self._cleanup_pending_commands(now)
        if previous is None:
            return False
        pending_context_ids = {command.context_id for command in self._pending_commands}
        controller_parent = bool(
            context_parent_id and context_parent_id in pending_context_ids
        )
        if context_user_id is not None or (
            context_parent_id is not None and not controller_parent
        ):
            return False
        tolerance = max(0.01, device_step / 2.0)
        for command in self._pending_commands:
            if now - command.issued_at > COMMAND_TRANSITION_WINDOW_SECONDS:
                continue
            lower = min(previous, command.value) - tolerance
            upper = max(previous, command.value) + tolerance
            movement = observed - previous
            command_direction = command.value - previous
            if lower <= observed <= upper and movement * command_direction > 0:
                return True
        return False

    async def _command_temperature(
        self,
        value: float,
        *,
        normal_control: bool,
    ) -> bool:
        climate_entity = self.entry.data[CONF_CLIMATE]
        now = self.hass.loop.time()
        service_context = Context()
        command = _PendingTemperatureCommand(float(value), now, service_context.id)
        # Register before the service call; fast devices may publish from inside it.
        self._pending_commands.append(command)
        service_value = from_celsius(value, self._system_temperature_unit())
        if service_value is None:
            self._pending_commands.remove(command)
            self.last_action = "service_error"
            self._notify()
            return False
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate_entity, ATTR_TEMPERATURE: service_value},
                blocking=True,
                context=service_context,
            )
        except Exception:
            try:
                self._pending_commands.remove(command)
            except ValueError:
                pass
            LOGGER.exception("Failed to set temperature on %s", climate_entity)
            self.last_action = "service_error"
            self._notify()
            return False

        self.last_set = float(value)
        self.last_target_trv = float(value)
        self.last_change = self.hass.loop.time()
        self.change_count = self.storage.increment_counter(
            self.entry.entry_id, "change_count"
        )
        await self.storage.async_save()
        if normal_control:
            self._stable_last_set = None
        return True

    def _update_statistics(
        self,
        now: float,
        room_temperature: float,
        error: float,
        deadband: float,
        *,
        fresh_room_sample: bool,
    ) -> None:
        if not fresh_room_sample:
            return
        if (
            self._last_stat_room_temperature is not None
            and self._last_stat_room_time is not None
        ):
            elapsed = now - self._last_stat_room_time
            if elapsed >= 30:
                raw_trend = (
                    (room_temperature - self._last_stat_room_temperature)
                    / elapsed
                    * 3600.0
                )
                self.temperature_trend = (
                    raw_trend
                    if self.temperature_trend is None
                    else 0.35 * raw_trend + 0.65 * self.temperature_trend
                )
                self._last_stat_room_temperature = room_temperature
                self._last_stat_room_time = now
        else:
            self._last_stat_room_temperature = room_temperature
            self._last_stat_room_time = now

        comfort_sample = 100.0 if abs(error) <= max(deadband, 0.3) else 0.0
        absolute_error = abs(error)
        if self._statistics_updated_at is None:
            self.mean_absolute_error = absolute_error
            self.comfort_score = comfort_sample
        else:
            elapsed = max(0.0, now - self._statistics_updated_at)
            alpha = 1.0 - exp(-elapsed / STATISTICS_TIME_CONSTANT_SECONDS)
            self.mean_absolute_error = (
                absolute_error
                if self.mean_absolute_error is None
                else self.mean_absolute_error
                + alpha * (absolute_error - self.mean_absolute_error)
            )
            self.comfort_score = (
                comfort_sample
                if self.comfort_score is None
                else self.comfort_score + alpha * (comfort_sample - self.comfort_score)
            )
        self._statistics_updated_at = now

    def _update_control_output(
        self, mode: str, setpoint: float | None, minimum: float, maximum: float
    ) -> None:
        if setpoint is None or maximum <= minimum:
            self.control_output = None
            return
        fraction = (setpoint - minimum) / (maximum - minimum)
        if mode == "cool":
            fraction = 1.0 - fraction
        self.control_output = max(0.0, min(100.0, fraction * 100.0))

    # ---------------------------------------------------------------------
    # Main control pass
    # ---------------------------------------------------------------------
    async def _async_control(self, force: bool, reasons: tuple[str, ...]) -> None:
        climate_entity = self.entry.data[CONF_CLIMATE]
        room_entity = self.entry.data[CONF_ROOM_SENSOR]
        climate = self.hass.states.get(climate_entity)
        room = self.hass.states.get(room_entity)
        now = self.hass.loop.time()
        window_setback = self._window_setback(now)
        self._window_setback_active = window_setback
        if (
            climate is None
            or room is None
            or climate.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            or room.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        ):
            self.last_action = "skipped_unavailable_entities"
            self._notify()
            return

        room_unit = str(
            room.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            or self._system_temperature_unit()
        )
        room_temperature = to_celsius(room.state, room_unit)
        if room_temperature is None:
            self.last_action = "skipped_invalid_room_temp"
            self._notify()
            return

        minimum, maximum, device_step = self._device_limits(climate)
        device_target = to_celsius(
            climate.attributes.get(ATTR_TEMPERATURE),
            self._system_temperature_unit(),
        )
        previous_device_target = self._last_seen_device_target
        if self.last_set is None and device_target is not None:
            # Bumpless upgrade/start: adopt the confirmed device state first.
            self.last_set = device_target
            self.last_confirmed_setpoint = device_target

        preset = self.get_preset()
        self.mode = preset
        settings = self._preset_settings(preset)
        target = float(settings["target"])
        target_delta = (
            0.0 if self._last_room_target is None else target - self._last_room_target
        )
        target_changed = self._last_room_target is not None and abs(target_delta) > 1e-9
        self._last_room_target = target

        deadband = max(0.0, self._number(CONF_DEADBAND, DEFAULT_DEADBAND))
        error = target - room_temperature
        self.last_error = error
        room_updated = getattr(room, "last_updated", None)
        fresh_room_sample = room_updated != self._last_room_state_updated
        self._last_room_state_updated = room_updated
        self._update_statistics(
            now,
            room_temperature,
            error,
            deadband,
            fresh_room_sample=fresh_room_sample,
        )

        if target_changed:
            self._reset_dynamic_state(rebase=True)
            self._block_learning_for_settle()

        boost_active = self.boost_active and now < self.boost_until
        if self.boost_active and not boost_active:
            self._cancel_boost(mark_rebase=True)

        hvac_mode = self.get_hvac_mode()
        physical_mode = _mode_value(climate.state)
        stored_hvac_mode = self.storage.get_hvac_mode(self.entry.entry_id)
        if stored_hvac_mode not in self.available_hvac_modes():
            # Initialize only after the physical entity has a valid state.
            # Persisting a fallback during startup could turn a late-loading
            # thermostat off. Fresh entries use their explicit preset mode;
            # migrated ``keep`` entries adopt the physical mode bumplessly.
            configured_mode = str(settings.get(CONF_HVAC_MODE, PRESET_HVAC_KEEP))
            initial_mode = (
                configured_mode
                if configured_mode != PRESET_HVAC_KEEP
                and configured_mode in self.available_hvac_modes()
                else physical_mode
            )
            if initial_mode not in self.available_hvac_modes():
                initial_mode = next(
                    (mode for mode in self.available_hvac_modes() if mode != "off"),
                    "off",
                )
            if physical_mode != initial_mode and not await self._set_hvac_mode(
                initial_mode, persist=False
            ):
                return
            self.storage.set_hvac_mode(self.entry.entry_id, initial_mode)
            await self.storage.async_save()
            hvac_mode = initial_mode
            physical_mode = initial_mode
        # Virtual OFF is authoritative and stops every regulation/learning path.
        if hvac_mode == "off":
            if physical_mode != "off" and not await self._set_hvac_mode(
                "off", persist=False
            ):
                return
            self.pause_active = True
            self._clear_manual_candidate()
            self._reset_dynamic_state(rebase=False)
            self.last_action = "hvac_off"
            self.last_target_trv = device_target
            self.control_output = 0.0
            self._notify()
            return

        pause_on_hvac_off = bool(self.opt(CONF_PAUSE_ON_HVAC_OFF))
        self.pause_active = bool(settings.get("pause", False))
        if physical_mode == "off" and pause_on_hvac_off:
            self.pause_active = True
        if self.pause_active:
            self._clear_manual_candidate()
            self._reset_dynamic_state(rebase=False)
            self.last_action = "paused"
            self.last_target_trv = device_target
            self.control_output = None
            self._notify()
            return

        if physical_mode != hvac_mode and not await self._set_hvac_mode(
            hvac_mode, persist=False
        ):
            return

        if hvac_mode in PASSIVE_HVAC_MODES or hvac_mode not in REGULATED_HVAC_MODES:
            # AUTO/DRY/FAN_ONLY belong to the physical device. Do not adopt
            # targets, apply overrides or learn while that device owns control.
            self._clear_manual_candidate()
            self._last_seen_device_target = device_target
            self.last_confirmed_setpoint = device_target
            self.last_action = "passive_mode"
            self.last_target_trv = device_target
            self.control_output = None
            self._reset_dynamic_state(rebase=False)
            self._notify()
            return

        # Detect device-target changes only after off/pause policy is known.
        if device_target is not None:
            changed = previous_device_target is not None and abs(
                device_target - previous_device_target
            ) >= max(0.01, device_step / 2.0)
            echo = self._is_command_echo(
                device_target,
                device_step,
                now,
                self._last_climate_context_id,
                self._last_climate_context_parent_id,
            )
            transition = self._is_command_transition(
                device_target,
                previous_device_target,
                device_step,
                now,
                self._last_climate_context_id,
                self._last_climate_context_user_id,
                self._last_climate_context_parent_id,
            )
            self.last_confirmed_setpoint = device_target
            self._last_seen_device_target = device_target
            if changed and (echo or transition):
                self._clear_manual_candidate()
                LOGGER.debug(
                    "Manual sync classification for %s: self echo %.3f (%s)",
                    climate_entity,
                    device_target,
                    reasons,
                )
            elif changed and not window_setback and not boost_active:
                if bool(self.opt(CONF_MANUAL_TARGET_SYNC)):
                    if self._manual_pending_device_target is None:
                        self._manual_anchor_device_target = previous_device_target
                    self._manual_pending_device_target = device_target
                    delay = max(
                        0,
                        min(
                            self._integer(
                                CONF_MANUAL_DELAY_SEC, DEFAULT_MANUAL_DELAY_SEC
                            ),
                            3600,
                        ),
                    )
                    self._manual_hold_until = now + delay
                    self._schedule_manual_delay(delay)
                    LOGGER.info(
                        "Manual target candidate for %s: %.3f (anchor %.3f, delay %ss)",
                        climate_entity,
                        device_target,
                        self._manual_anchor_device_target,
                        delay,
                    )
                    self.last_action = "manual_hold"
                    self.last_target_trv = device_target
                    self._notify()
                    if delay > 0:
                        return
                else:
                    # Manual sync disabled means restoring controller authority.
                    force = True
                    self._rebase_required = True
        else:
            self._last_seen_device_target = None

        if window_setback or boost_active:
            self._clear_manual_candidate()

        manual_sync = bool(self.opt(CONF_MANUAL_TARGET_SYNC))
        if not manual_sync:
            self._clear_manual_candidate()
        elif self._manual_pending_device_target is not None:
            if now < self._manual_hold_until:
                self.last_action = "manual_hold"
                self.last_target_trv = device_target
                self._notify()
                return
            anchor = self._manual_anchor_device_target
            observed = self._manual_pending_device_target
            if anchor is not None:
                target_minimum, target_maximum = self._target_limits(climate)
                new_target = manual_target_from_delta(
                    current_target=target,
                    observed_device_target=observed,
                    anchor_device_target=anchor,
                    minimum=target_minimum,
                    maximum=target_maximum,
                    step=device_step,
                )
                self._clear_manual_candidate()
                if abs(new_target - target) >= 1e-9:
                    self._set_preset_target_unlocked(new_target, preset)
                    self.manual_change_count = self.storage.increment_counter(
                        self.entry.entry_id, "manual_change_count"
                    )
                    await self.storage.async_save()
                    self.last_action = "manual_target_sync"
                    LOGGER.info(
                        "Accepted manual target for %s: room %.3f -> %.3f from device delta %.3f",
                        climate_entity,
                        target,
                        new_target,
                        observed - anchor,
                    )
                    self._reset_dynamic_state(rebase=True)
                    self._control_requested = True
                    self._notify()
                    # Never continue with the stale target/error from this pass.
                    return

        # Windows and boost are overrides; neither may influence learning.
        if window_setback:
            self._override_was_active = True
            override = maximum if hvac_mode == "cool" else minimum
            self.last_target_trv = override
            needs_command = device_target is None or not command_matches(
                device_target, override, device_step
            )
            if needs_command and not await self._command_temperature(
                override, normal_control=False
            ):
                return
            self._update_control_output(hvac_mode, override, minimum, maximum)
            self.last_action = "window_open"
            self._reset_dynamic_state(rebase=False)
            self._notify()
            return

        if boost_active:
            self._override_was_active = True
            if hvac_mode == "cool":
                override = minimum
            else:
                override = maximum
            self.last_target_trv = override
            needs_command = device_target is None or not command_matches(
                device_target, override, device_step
            )
            if needs_command and not await self._command_temperature(
                override, normal_control=False
            ):
                return
            self._update_control_output(hvac_mode, override, minimum, maximum)
            self.last_action = "boost"
            self._reset_dynamic_state(rebase=False)
            self._notify()
            return

        if self._override_was_active:
            self._override_was_active = False
            self._rebase_required = True
            force = True

        offset = self.storage.get_offset(self.entry.entry_id, hvac_mode)
        maximum_step = max(0.01, self._number(CONF_STEP_MAX, DEFAULT_STEP_MAX))
        gain = max(0.0, self._number(CONF_CONTROL_GAIN, DEFAULT_CONTROL_GAIN))

        if abs(error) <= deadband:
            baseline = max(minimum, min(maximum, target + offset))
            result = calculate_setpoint(
                room_temperature=room_temperature,
                room_target=target,
                offset=offset,
                gain=0.0,
                maximum_correction=maximum_step,
                maximum_step=maximum_step,
                device_step=device_step,
                minimum=minimum,
                maximum=maximum,
                # A rebase restores a known safe baseline in one command. A
                # slew limit here could strand a boost/window intermediate
                # forever once the controller re-enters the deadband.
                reference_setpoint=None,
                target_delta=0.0,
            )
            baseline = result.setpoint
            must_rebase = target_changed or self._rebase_required
            if must_rebase and (
                device_target is None
                or not command_matches(device_target, baseline, device_step)
            ):
                # Keep the flag until the physical state confirms the target;
                # this also retries failed or silently dropped commands.
                if not await self._command_temperature(baseline, normal_control=True):
                    return
                self.last_action = "deadband_rebase"
                self.last_target_trv = baseline
                self._stable_since = None
                self._notify()
                return
            if must_rebase:
                self._rebase_required = False

            stable_setpoint = (
                device_target if device_target is not None else self.last_set
            )
            if self._stable_since is None:
                self._stable_since = now
                self._stable_target = target
                self._stable_last_set = stable_setpoint
                self.last_action = (
                    "deadband_init" if previous_device_target is None else "hold"
                )
            elif (
                self._stable_target != target
                or self._stable_last_set != stable_setpoint
            ):
                self._stable_since = now
                self._stable_target = target
                self._stable_last_set = stable_setpoint
                self.last_action = "hold"
            elif (
                bool(self.opt(CONF_ENABLE_LEARNING))
                and stable_setpoint is not None
                and now >= self._learning_block_until
                and now - self._stable_since >= STABLE_LEARN_SECONDS
            ):
                implied_offset = max(
                    -MAX_OFFSET, min(MAX_OFFSET, stable_setpoint - target)
                )
                new_offset = offset + STABLE_LEARN_ALPHA * (implied_offset - offset)
                if abs(new_offset - offset) > 1e-6:
                    self.storage.set_offset(self.entry.entry_id, new_offset, hvac_mode)
                    await self.storage.async_save()
                self._stable_since = now
                self.last_action = "stable_learn"
            else:
                self.last_action = "hold"
            self.last_target_trv = stable_setpoint
            self.last_correction = 0.0
            self._update_control_output(hvac_mode, stable_setpoint, minimum, maximum)
            self._notify()
            return

        self._stable_since = None
        self._stable_target = None
        self._stable_last_set = None

        result = calculate_setpoint(
            room_temperature=room_temperature,
            room_target=target,
            offset=offset,
            gain=gain,
            maximum_correction=max(maximum_step, 2.0 * maximum_step),
            maximum_step=maximum_step,
            device_step=device_step,
            minimum=minimum,
            maximum=maximum,
            reference_setpoint=device_target,
            target_delta=target_delta,
        )

        cooldown = max(0.0, self._number(CONF_COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC))
        cooldown_active = (
            not force and self.last_change > 0.0 and now - self.last_change < cooldown
        )

        enable_learning = bool(
            self.opt(CONF_ENABLE_LEARNING)
            if self.opt(CONF_ENABLE_LEARNING) is not None
            else DEFAULT_ENABLE_LEARNING
        )
        if (
            enable_learning
            and fresh_room_sample
            and now >= self._learning_block_until
            and not result.saturated
            and not cooldown_active
        ):
            if self._last_learning_time is None:
                self._last_learning_time = now
            else:
                elapsed = max(0.0, now - self._last_learning_time)
                interval = float(self._interval_seconds or DEFAULT_INTERVAL_SEC)
                scale = min(1.0, elapsed / max(1.0, interval))
                if scale > 0:
                    learn_rate = max(
                        0.0, self._number(CONF_LEARN_RATE, DEFAULT_LEARN_RATE)
                    )
                    new_offset = max(
                        -MAX_OFFSET,
                        min(MAX_OFFSET, offset + learn_rate * error * scale),
                    )
                    if abs(new_offset - offset) > 1e-6:
                        offset = new_offset
                        self.storage.set_offset(self.entry.entry_id, offset, hvac_mode)
                        await self.storage.async_save()
                        result = calculate_setpoint(
                            room_temperature=room_temperature,
                            room_target=target,
                            offset=offset,
                            gain=gain,
                            maximum_correction=2.0 * maximum_step,
                            maximum_step=maximum_step,
                            device_step=device_step,
                            minimum=minimum,
                            maximum=maximum,
                            reference_setpoint=device_target,
                            target_delta=target_delta,
                        )
                    self._last_learning_time = now

        setpoint = result.setpoint
        action_after_command = "set_temperature"

        # Retain the existing adaptive radiator over-temperature protection,
        # but limit it, apply it only in heat mode, and keep it out of learning.
        stuck_enabled = bool(
            self.opt(CONF_STUCK_ENABLE)
            if self.opt(CONF_STUCK_ENABLE) is not None
            else DEFAULT_STUCK_ENABLE
        )
        if stuck_enabled and hvac_mode == "heat" and error < -deadband:
            stuck_seconds = max(
                300,
                min(
                    self._integer(CONF_STUCK_SECONDS, DEFAULT_STUCK_SECONDS),
                    24 * 3600,
                ),
            )
            minimum_drop = max(
                0.0, self._number(CONF_STUCK_MIN_DROP, DEFAULT_STUCK_MIN_DROP)
            )
            reduction = max(
                device_step, self._number(CONF_STUCK_STEP, DEFAULT_STUCK_STEP)
            )
            if not self._stuck_active:
                self._stuck_active = True
                self._stuck_ref_temp = room_temperature
                self._stuck_ref_time = now
            elif (
                self._stuck_ref_time is not None
                and now - self._stuck_ref_time >= stuck_seconds
            ):
                reference = (
                    self._stuck_ref_temp
                    if self._stuck_ref_temp is not None
                    else room_temperature
                )
                if room_temperature >= reference - minimum_drop:
                    self._stuck_bias = min(
                        maximum - minimum, self._stuck_bias + reduction
                    )
                    action_after_command = "stuck_overtemp_down"
                self._stuck_ref_temp = room_temperature
                self._stuck_ref_time = now
            if self._stuck_bias > 0:
                biased = max(minimum, setpoint - self._stuck_bias)
                setpoint = calculate_setpoint(
                    room_temperature=0,
                    room_target=biased,
                    offset=0,
                    gain=0,
                    maximum_correction=0,
                    maximum_step=maximum - minimum,
                    device_step=device_step,
                    minimum=minimum,
                    maximum=maximum,
                    reference_setpoint=None,
                    target_delta=0,
                ).setpoint
        else:
            self._stuck_active = False
            self._stuck_ref_temp = None
            self._stuck_ref_time = None
            self._stuck_bias = 0.0

        self.last_target_trv = setpoint
        self.last_correction = result.correction
        self._update_control_output(hvac_mode, setpoint, minimum, maximum)

        if device_target is not None and command_matches(
            device_target, setpoint, device_step
        ):
            self.last_action = "skipped_no_change"
            self._notify()
            return

        if cooldown_active:
            self.last_action = "cooldown"
            self._notify()
            return

        if await self._command_temperature(setpoint, normal_control=True):
            self.last_action = action_after_command
            LOGGER.info(
                "Control %s: room=%.2f target=%.2f error=%.2f offset=%.2f correction=%.2f device=%.2f reasons=%s",
                climate_entity,
                room_temperature,
                target,
                error,
                offset,
                result.correction,
                setpoint,
                reasons,
            )
        self._notify()
