"""Pure control helpers for Smart Offset Thermostat.

This module deliberately has no Home Assistant imports.  Keeping preset
normalization and setpoint arithmetic pure makes the safety-critical edge
cases cheap to test and lets the controller concentrate on orchestration.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

if __package__:
    from .const import DEFAULT_ROOM_TARGET, PRESET_HVAC_MODES, default_presets
else:  # Allow this HA-independent module to be tested without importing package __init__.
    from const import DEFAULT_ROOM_TARGET, PRESET_HVAC_MODES, default_presets


_FLOAT_EPSILON = 1e-9
_COMMAND_EPSILON = 1e-6
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off", "disabled", "none", "null"})


@dataclass(frozen=True, slots=True)
class SetpointResult:
    """Result of a pure setpoint calculation."""

    error: float
    correction: float
    desired: float
    setpoint: float
    saturated: bool


def _finite_float(value: Any, *, name: str) -> float:
    """Return *value* as a finite float or raise a useful error."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")  # noqa: TRY004
    try:
        result = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} must be a finite number") from err
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _optional_finite_float(value: Any, fallback: float) -> float:
    """Best-effort float conversion used for user-authored preset data."""
    if isinstance(value, bool):
        return fallback
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if math.isfinite(result) else fallback


def _robust_bool(value: Any, fallback: bool = False) -> bool:
    """Parse common JSON, UI, YAML and legacy representations of booleans."""
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return fallback
        return float(value) != 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
    return fallback


def _valid_hvac_mode(value: Any, fallback: str = "heat") -> str:
    """Normalize an HVAC mode and replace unsupported values."""
    fallback_value = str(fallback).strip().lower()
    if fallback_value not in PRESET_HVAC_MODES:
        fallback_value = "heat"

    if not isinstance(value, str):
        return fallback_value
    normalized = value.strip().lower()
    return normalized if normalized in PRESET_HVAC_MODES else fallback_value


def normalize_entity_ids(value: Any) -> list[str]:
    """Normalize persisted entity-selector values without stringifying mappings."""
    if value is None:
        return []
    if isinstance(value, (str, Mapping)):
        candidates = [value]
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        return []

    normalized: list[str] = []
    for item in candidates:
        entity_id: Any = item
        if isinstance(item, Mapping):
            entity_id = item.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        entity_id = entity_id.strip()
        if entity_id and entity_id not in normalized:
            normalized.append(entity_id)
    return normalized


def normalize_presets(
    value: Any,
    fallback_target: Any,
    default_hvac_mode: str = "heat",
) -> list[dict[str, Any]]:
    """Normalize a list or JSON string of thermostat presets.

    Invalid containers, or containers without a usable preset, return a fresh
    default list. Duplicate IDs keep their first occurrence so later malformed
    data cannot silently replace an already valid preset.
    """
    target_fallback = _optional_finite_float(fallback_target, DEFAULT_ROOM_TARGET)
    hvac_fallback = _valid_hvac_mode(default_hvac_mode)

    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None

    if not isinstance(parsed, list):
        return default_presets(target_fallback, hvac_fallback)

    normalized_presets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in parsed:
        if not isinstance(item, Mapping):
            continue

        raw_id = item.get("id")
        if raw_id is None or isinstance(raw_id, bool):
            continue
        preset_id = str(raw_id).strip()
        if not preset_id or preset_id in seen_ids:
            continue

        normalized_presets.append(
            {
                "id": preset_id,
                "target": _optional_finite_float(item.get("target"), target_fallback),
                "pause": _robust_bool(item.get("pause"), False),
                "hvac_mode": _valid_hvac_mode(item.get("hvac_mode"), hvac_fallback),
            }
        )
        seen_ids.add(preset_id)

    if normalized_presets:
        return normalized_presets
    return default_presets(target_fallback, hvac_fallback)


def _decimal(value: float) -> Decimal:
    """Convert a finite float without importing its binary rounding noise."""
    try:
        return Decimal(str(value))
    except InvalidOperation as err:  # Defensive; callers already validate floats.
        raise ValueError("value must be a finite number") from err


def _round_to_step(value: float, step: float) -> float:
    """Round to the nearest device step, with halves away from zero."""
    if step <= 0.0:
        return value
    units = (_decimal(value) / _decimal(step)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    return float(units * _decimal(step))


def _floor_to_step(value: float, step: float) -> float:
    if step <= 0.0:
        return value
    units = (_decimal(value) / _decimal(step)).to_integral_value(rounding=ROUND_FLOOR)
    return float(units * _decimal(step))


def _ceil_to_step(value: float, step: float) -> float:
    if step <= 0.0:
        return value
    units = (_decimal(value) / _decimal(step)).to_integral_value(rounding=ROUND_CEILING)
    return float(units * _decimal(step))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _validate_bounds(minimum: Any, maximum: Any) -> tuple[float, float]:
    lower = _finite_float(minimum, name="minimum")
    upper = _finite_float(maximum, name="maximum")
    if lower > upper:
        raise ValueError("minimum must not be greater than maximum")
    return lower, upper


def _quantize_within(
    value: float,
    step: float,
    minimum: float,
    maximum: float,
) -> float:
    """Return the closest device-grid value inside an inclusive range."""
    if step <= 0.0:
        return _clamp(value, minimum, maximum)

    grid_minimum = _ceil_to_step(minimum, step)
    grid_maximum = _floor_to_step(maximum, step)
    if grid_minimum > grid_maximum + _FLOAT_EPSILON:
        # No device-grid value exists inside this unusually narrow range.
        return _clamp(value, minimum, maximum)

    rounded = _round_to_step(value, step)
    return _clamp(rounded, grid_minimum, grid_maximum)


def manual_target_from_delta(
    current_target: Any,
    observed_device_target: Any,
    anchor_device_target: Any,
    minimum: Any,
    maximum: Any,
    step: Any,
) -> float:
    """Transfer a physical thermostat adjustment to the virtual room target."""
    lower, upper = _validate_bounds(minimum, maximum)
    current = _finite_float(current_target, name="current_target")
    observed = _finite_float(observed_device_target, name="observed_device_target")
    anchor = _finite_float(anchor_device_target, name="anchor_device_target")
    device_step = abs(_finite_float(step, name="step"))

    requested = current + (observed - anchor)
    return _quantize_within(requested, device_step, lower, upper)


def calculate_setpoint(
    room_temperature: Any,
    room_target: Any,
    offset: Any,
    gain: Any,
    maximum_correction: Any,
    maximum_step: Any,
    device_step: Any,
    minimum: Any,
    maximum: Any,
    reference_setpoint: Any | None = None,
    target_delta: Any = 0,
) -> SetpointResult:
    """Calculate a bounded, quantized and optionally slew-limited setpoint.

    ``target_delta`` shifts the slew reference by an explicit room-target
    change. This lets the feed-forward part follow a deliberate target change
    immediately while still limiting algorithmic corrections relative to the
    previous physical setpoint.
    """
    lower, upper = _validate_bounds(minimum, maximum)
    room = _finite_float(room_temperature, name="room_temperature")
    target = _finite_float(room_target, name="room_target")
    learned_offset = _finite_float(offset, name="offset")
    control_gain = _finite_float(gain, name="gain")
    correction_limit = _finite_float(maximum_correction, name="maximum_correction")
    slew_limit = _finite_float(maximum_step, name="maximum_step")
    step = abs(_finite_float(device_step, name="device_step"))
    explicit_target_delta = _finite_float(target_delta, name="target_delta")

    if correction_limit < 0.0:
        raise ValueError("maximum_correction must not be negative")
    if slew_limit < 0.0:
        raise ValueError("maximum_step must not be negative")

    error = target - room
    correction = _clamp(control_gain * error, -correction_limit, correction_limit)
    desired = target + learned_offset + correction

    candidate = _clamp(desired, lower, upper)
    saturated = abs(candidate - desired) > _FLOAT_EPSILON
    allowed_lower = lower
    allowed_upper = upper

    if reference_setpoint is not None:
        reference = _finite_float(reference_setpoint, name="reference_setpoint")
        shifted_reference = reference + explicit_target_delta
        allowed_lower = max(lower, shifted_reference - slew_limit)
        allowed_upper = min(upper, shifted_reference + slew_limit)

        if allowed_lower <= allowed_upper:
            limited = _clamp(candidate, allowed_lower, allowed_upper)
        else:
            # The shifted reference is outside the configured physical range.
            limited = _clamp(shifted_reference, lower, upper)
            allowed_lower = limited
            allowed_upper = limited
        if abs(limited - candidate) > _FLOAT_EPSILON:
            saturated = True
        candidate = limited

    setpoint = _quantize_within(candidate, step, allowed_lower, allowed_upper)
    setpoint = _clamp(setpoint, lower, upper)

    return SetpointResult(
        error=error,
        correction=correction,
        desired=desired,
        setpoint=setpoint,
        saturated=saturated,
    )


def command_matches(observed: Any, commanded: Any, device_step: Any) -> bool:
    """Return whether an observed target is an acknowledgement of a command.

    The tolerance is just over half a device step. A real full-step manual
    adjustment can therefore never be mistaken for the controller's echo.
    """
    try:
        observed_value = _finite_float(observed, name="observed")
        commanded_value = _finite_float(commanded, name="commanded")
        step = abs(_finite_float(device_step, name="device_step"))
    except ValueError:
        return False

    tolerance = (step / 2.0) + _COMMAND_EPSILON if step > 0.0 else _COMMAND_EPSILON
    return abs(observed_value - commanded_value) < tolerance


__all__ = [
    "SetpointResult",
    "calculate_setpoint",
    "command_matches",
    "manual_target_from_delta",
    "normalize_entity_ids",
    "normalize_presets",
]
