from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers.event import async_track_time_interval, async_call_later, async_track_state_change_event
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import *

STABLE_LEARN_SECONDS = 900  # 15 minutes within deadband
STABLE_LEARN_ALPHA = 0.25     # move offset 25% towards implied value per stable window

LOGGER = logging.getLogger(__name__)

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _round_step(v, step):
    if step <= 0:
        return v
    return round(v / step) * step

def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None

def _normalize_entity_list(value):
    """Normalize selector values to a list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            if v is None:
                continue
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, dict) and 'entity_id' in v:
                out.append(v['entity_id'])
        return [x for x in out if x]
    return []

class SmartOffsetController:
    def __init__(self, hass, entry, storage):
        self.hass = hass
        self.entry = entry
        self.storage = storage
        self.unsub = None

        self.last_set = None
        self.last_change = 0.0
        self.last_action = "init"
        self.last_error = None
        self.last_target_trv = None
        self.change_count = 0

        self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0
        self.window_is_open = False
        self._last_room_target = None
        self._unsub_window = None
        self._window_entities = tuple()
        self._force_next_control = False
        self._stuck_active = False
        self._stuck_ref_temp = None
        self._stuck_ref_time = None
        self._stuck_bias = 0.0

    def opt(self, key):
        if key in self.entry.options:
            return self.entry.options[key]
        if key in self.entry.data:
            return self.entry.data[key]
        return DEFAULTS.get(key)

    def _notify(self):
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")



    def _ensure_window_listener(self, window_entities: list[str] | None):
        # Subscribe to window sensor changes so the controller reacts immediately (no need to wait for next interval)
        entities = tuple([e for e in _normalize_entity_list(window_entities) if e])
        if entities == self._window_entities:
            return

        # Unsubscribe old listener
        if self._unsub_window:
            try:
                self._unsub_window()
            except Exception:
                pass
            self._unsub_window = None

        self._window_entities = entities

        if not entities:
            return

        def _compute_open() -> bool:
            for ent in entities:
                st = self.hass.states.get(ent)
                if st is None:
                    continue
                if str(st.state).lower() in ("on", "open", "true", "1"):
                    return True
            return False

        async def _on_window_change(event):
            # Update window state immediately and trigger control once
            is_open = _compute_open()
            if is_open != self.window_is_open:
                self.window_is_open = is_open
            await self.trigger_once(force=True)
            self._notify()

        self._unsub_window = async_track_state_change_event(self.hass, list(entities), _on_window_change)

    def _cancel_boost(self):
        if self._boost_unsub:
            try:
                self._boost_unsub()
            except Exception:
                pass
            self._boost_unsub = None
        self.boost_active = False
        self.boost_until = 0.0

    async def reset_offset(self):
        # Reset learned offset to 0 and persist it
        self.storage.set_offset(self.entry.entry_id, 0.0)
        await self.storage.async_save()
        self.last_action = "reset_offset"
        # Apply new baseline immediately
        await self.trigger_once(force=True)
        self._notify()

    async def start_boost(self):
        duration = int(self.opt(CONF_BOOST_DURATION_SEC) or DEFAULT_BOOST_DURATION_SEC)
        duration = max(30, min(duration, 3600))
        self._cancel_boost()
        self.boost_active = True
        self.boost_until = self.hass.loop.time() + float(duration)

        async def _end(_):
            self._cancel_boost()
            await self.trigger_once(force=True)
            self._notify()

        self._boost_unsub = async_call_later(self.hass, float(duration), _end)
        await self.trigger_once(force=True)
        self._notify()

    async def async_start(self):
        interval = int(self.opt(CONF_INTERVAL_SEC) or DEFAULT_INTERVAL_SEC)
        self.unsub = async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=interval)
        )
        await self._tick(None)

    async def async_stop(self):
        self._cancel_boost()
        if self.unsub:
            self.unsub()
            self.unsub = None

    async def trigger_once(self, force: bool = False):
        if force:
            self._force_next_control = True
        await self._tick(None)

    async def _tick(self, _):
        climate_entity = self.entry.data[CONF_CLIMATE]
        room_sensor = self.entry.data[CONF_ROOM_SENSOR]
        window_entities = _normalize_entity_list(self.opt(CONF_WINDOW_SENSORS))
        # backward compatible: old single key
        old_window = self.opt(CONF_WINDOW_SENSOR)
        if old_window and old_window not in window_entities:
            window_entities = list(window_entities) + [old_window]
        self._ensure_window_listener(list(window_entities))

        climate = self.hass.states.get(climate_entity)
        room = self.hass.states.get(room_sensor)
        if not climate or not room:
            self.last_action = "skipped_unavailable_entities"
            self._notify()
            return

        t_room = _to_float(room.state)
        if t_room is None:
            self.last_action = "skipped_invalid_room_temp"
            self._notify()
            return

        t_target = float(self.opt(CONF_ROOM_TARGET) or DEFAULTS[CONF_ROOM_TARGET])
        # Detect target changes: when user changes the virtual target, rebase TRV even if we end up in deadband
        target_changed = (self._last_room_target is not None and abs(t_target - self._last_room_target) > 1e-9)
        self._last_room_target = t_target
        stuck_enable = bool(self.opt(CONF_STUCK_ENABLE))
        stuck_seconds = int(self.opt(CONF_STUCK_SECONDS) or DEFAULT_STUCK_SECONDS)
        stuck_min_drop = float(self.opt(CONF_STUCK_MIN_DROP) or DEFAULT_STUCK_MIN_DROP)
        stuck_step = float(self.opt(CONF_STUCK_STEP) or DEFAULT_STUCK_STEP)
        stuck_seconds = max(300, min(stuck_seconds, 24 * 3600))
        stuck_min_drop = max(0.0, min(stuck_min_drop, 5.0))
        stuck_step = max(0.05, min(stuck_step, 5.0))
        deadband = float(self.opt(CONF_DEADBAND) or DEFAULT_DEADBAND)
        step_max = float(self.opt(CONF_STEP_MAX) or DEFAULT_STEP_MAX)
        step_min = float(self.opt(CONF_STEP_MIN) or DEFAULT_STEP_MIN)
        learn_rate = float(self.opt(CONF_LEARN_RATE) or DEFAULT_LEARN_RATE)
        trv_min = float(self.opt(CONF_TRV_MIN) or DEFAULT_TRV_MIN)
        trv_max = float(self.opt(CONF_TRV_MAX) or DEFAULT_TRV_MAX)
        cooldown = float(self.opt(CONF_COOLDOWN_SEC) or DEFAULT_COOLDOWN_SEC)
        enable_learning = bool(self.opt(CONF_ENABLE_LEARNING))

        # Window handling (optional)
        window_open = False
        if window_entities:
            for _we in window_entities:
                w_state = self.hass.states.get(_we)
                if not w_state:
                    continue
                if str(w_state.state).lower() in ("on", "open", "true", "1"):
                    window_open = True
                    break

        if window_open != self.window_is_open:
            self.window_is_open = window_open

        e = t_target - t_room
        self.last_error = e
        # reset stability tracking when we are outside the deadband
        if abs(e) > float(deadband):
            self._stable_since = None
            self._stable_target = None
            self._stable_last_set = None

        # Highest priority: window open => set TRV to minimum and pause learning
        if window_open:
            self._cancel_boost()
            t_trv = _clamp(float(trv_min), float(trv_min), float(trv_max))
            self.last_target_trv = t_trv
            now_mono = self.hass.loop.time()
            if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": climate_entity, ATTR_TEMPERATURE: t_trv},
                    blocking=False,
                )
                self.last_set = t_trv
                self.last_change = now_mono
                self.change_count += 1
                self._force_next_control = False
            self.last_action = "window_open"
            self._stuck_bias = 0.0
            self._stable_since = None
            self._stable_target = None
            self._stable_last_set = None
            self._notify()
            return

        # Next priority: boost active => set TRV to max for boost duration
        if self.boost_active and (self.hass.loop.time() < self.boost_until):
            # reset stability/learning during boost so we never learn a boost setpoint
            self._stable_since = None
            self._stable_target = None
            self._stable_last_set = None
            self._stuck_bias = 0.0
            t_trv = _clamp(float(trv_max), float(trv_min), float(trv_max))
            self.last_target_trv = t_trv
            now_mono = self.hass.loop.time()
            if self.last_set is None or abs(t_trv - self.last_set) >= (step_min - 1e-9):
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": climate_entity, ATTR_TEMPERATURE: t_trv},
                    blocking=False,
                )
                self.last_set = t_trv
                self.last_change = now_mono
                self.change_count += 1
                self._force_next_control = False
            self.last_action = "boost"
            self._notify()
            return

        if abs(e) <= deadband:
            # If the user changed the target, we must not keep an old (possibly very high) TRV setpoint.
            # Rebase to a learned baseline (target + learned offset), even inside deadband.
            if target_changed:
                baseline = float(t_target) + float(self.storage.get_offset(self.entry.entry_id))
                baseline = _clamp(baseline, float(trv_min), float(trv_max))
                baseline = _round_step(baseline, step_min)
                self.last_target_trv = baseline
                now_mono = self.hass.loop.time()
                if self.last_set is None or abs(baseline - self.last_set) >= (step_min - 1e-9):
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {"entity_id": climate_entity, ATTR_TEMPERATURE: baseline},
                        blocking=False,
                    )
                    self.last_set = baseline
                    self.last_change = now_mono
                    self.change_count += 1
                    self._force_next_control = False
                # reset stability tracking on explicit target change
                self._stable_since = None
                self._stable_target = None
                self._stable_last_set = None
                self.last_action = "deadband_rebase"
                self._notify()
                return

                        # baseline init when last_set is None: ensure we set a sensible TRV value at least once
            if self.last_set is None:
                baseline = float(t_target) + float(self.storage.get_offset(self.entry.entry_id))
                baseline = _clamp(baseline, float(trv_min), float(trv_max))
                baseline = _round_step(baseline, step_min)
                now_mono = self.hass.loop.time()
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": climate_entity, ATTR_TEMPERATURE: baseline},
                    blocking=False,
                )
                self.last_set = baseline
                self.last_change = now_mono
                self.change_count += 1
                self._force_next_control = False
                self.last_action = "deadband_init"
                self.last_target_trv = baseline
                self._notify()
                return

# Hold the current TRV setpoint while we are inside the deadband.
            # This prevents "jumping back" to a computed baseline after we finally reached the target.
            now_mono = self.hass.loop.time()
            if self._stable_since is None or self._stable_target != float(t_target) or self._stable_last_set != self.last_set:
                self._stable_since = now_mono
                self._stable_target = float(t_target)
                self._stable_last_set = self.last_set
            else:
                # If we stayed within the deadband for long enough, convert the current successful TRV setpoint
                # into the learned offset so it remains stable in the future.
                if enable_learning and self.last_set is not None and (now_mono - float(self._stable_since) >= STABLE_LEARN_SECONDS):
                    implied_offset = float(self.last_set) - float(t_target)
                    implied_offset = _clamp(implied_offset, -10.0, 10.0)
                    current_offset = float(self.storage.get_offset(self.entry.entry_id))
                    new_offset = current_offset + STABLE_LEARN_ALPHA * (implied_offset - current_offset)
                    if abs(new_offset - current_offset) > 1e-6:
                        self.storage.set_offset(self.entry.entry_id, new_offset)
                        await self.storage.async_save()
                    # once learned, drop any temporary over-temp bias
                    self._stuck_bias = 0.0
                    # restart stability window so learning happens at most once per window
                    self._stable_since = now_mono
                    self._stable_target = float(t_target)
                    self._stable_last_set = self.last_set
                    self.last_action = "stable_learn"
                    self.last_target_trv = self.last_set
                    self._notify()
                    return

            self.last_action = "hold"
            self.last_target_trv = self.last_set
            self._notify()
            return

        offset = self.storage.get_offset(self.entry.entry_id)

        if enable_learning and e > deadband:
            new_offset = _clamp(offset + learn_rate * e, -10.0, 10.0)
            if abs(new_offset - offset) > 1e-6:
                offset = new_offset
                self.storage.set_offset(self.entry.entry_id, offset)
                await self.storage.async_save()

        correction = _clamp(0.5 * e, -step_max, step_max)

        t_trv = _round_step(t_target + offset + correction, step_min)
        # apply persistent over-temp bias (built up by adaptive correction)
        if stuck_enable and (not window_open) and (not (self.boost_active and (self.hass.loop.time() < self.boost_until))):
            if e < -deadband and self._stuck_bias > 0:
                t_trv = _round_step(_clamp(float(t_trv) - float(self._stuck_bias), float(trv_min), float(trv_max)), step_min)
            elif e >= -deadband:
                self._stuck_bias = 0.0
        # Persistent over-temperature detection (cooling not happening)
        now_mono = self.hass.loop.time()
        if stuck_enable and (not window_open) and (not (self.boost_active and (self.hass.loop.time() < self.boost_until))):
            if e < -deadband:
                if not self._stuck_active:
                    self._stuck_active = True
                    self._stuck_ref_temp = float(t_room)
                    self._stuck_ref_time = float(now_mono)
                else:
                    if self._stuck_ref_time is not None and (now_mono - float(self._stuck_ref_time) >= float(stuck_seconds)):
                        ref_temp = float(self._stuck_ref_temp) if self._stuck_ref_temp is not None else float(t_room)
                        # If the room did not cool down by at least stuck_min_drop, push TRV down
                        if float(t_room) >= (ref_temp - float(stuck_min_drop)):
                            self._stuck_bias = float(self._stuck_bias) + float(stuck_step)
                            t_trv = _round_step(_clamp(float(t_trv) - float(stuck_step), float(trv_min), float(trv_max)), step_min)
                            self.last_action = "stuck_overtemp_down"
                        # reset reference window
                        self._stuck_ref_temp = float(t_room)
                        self._stuck_ref_time = float(now_mono)
            else:
                # not too warm anymore -> reset
                self._stuck_active = False
                self._stuck_ref_temp = None
                self._stuck_ref_time = None
                self._stuck_bias = 0.0

        t_trv = _clamp(t_trv, trv_min, trv_max)
        self.last_target_trv = t_trv

        now_mono = self.hass.loop.time()
        if self.last_set is not None:
            if abs(t_trv - self.last_set) < (step_min - 1e-9):
                self.last_action = "skipped_no_change"
                self._notify()
                return
            if (now_mono - self.last_change) < cooldown and abs(e) < 1.0 and not self._force_next_control:
                self.last_action = "cooldown"
                self._notify()
                return

        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": climate_entity, ATTR_TEMPERATURE: t_trv},
            blocking=False,
        )

        self.last_set = t_trv
        self._force_next_control = False
        self.last_change = now_mono
        self.change_count += 1
        self._force_next_control = False
        self.last_action = "set_temperature"
        LOGGER.info(
            "set_temperature: entity=%s room=%.2f target=%.2f error=%.2f offset=%.2f correction=%.2f trv=%.2f",
            climate_entity, t_room, t_target, e, offset, correction, t_trv
        )
        self._notify()
