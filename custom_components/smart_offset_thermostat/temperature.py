"""Temperature conversion helpers.

Configuration, learned offsets and controller arithmetic are stored in Celsius
for backward compatibility. Home Assistant exposes climate state attributes in
the configured system unit, so all boundaries are converted explicitly.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_conversion import TemperatureConverter

CANONICAL_TEMPERATURE_UNIT = UnitOfTemperature.CELSIUS


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (HomeAssistantError, TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def to_celsius(value: Any, unit: str) -> float | None:
    """Convert an absolute temperature to the canonical Celsius unit."""
    numeric = _finite_float(value)
    if numeric is None:
        return None
    try:
        converted = TemperatureConverter.convert(
            numeric, unit, CANONICAL_TEMPERATURE_UNIT
        )
    except (HomeAssistantError, TypeError, ValueError):
        return None
    return converted if isfinite(converted) else None


def from_celsius(value: Any, unit: str) -> float | None:
    """Convert an absolute canonical temperature to *unit*."""
    numeric = _finite_float(value)
    if numeric is None:
        return None
    try:
        converted = TemperatureConverter.convert(
            numeric, CANONICAL_TEMPERATURE_UNIT, unit
        )
    except (HomeAssistantError, TypeError, ValueError):
        return None
    return converted if isfinite(converted) else None


def delta_to_celsius(value: Any, unit: str) -> float | None:
    """Convert a temperature difference without applying an absolute offset."""
    numeric = _finite_float(value)
    if numeric is None:
        return None
    try:
        zero = TemperatureConverter.convert(0.0, unit, CANONICAL_TEMPERATURE_UNIT)
        converted = TemperatureConverter.convert(
            numeric, unit, CANONICAL_TEMPERATURE_UNIT
        )
    except (HomeAssistantError, TypeError, ValueError):
        return None
    result = converted - zero
    return result if isfinite(result) else None


def delta_from_celsius(value: Any, unit: str) -> float | None:
    """Convert a canonical Celsius difference without an absolute offset."""
    numeric = _finite_float(value)
    if numeric is None:
        return None
    try:
        zero = TemperatureConverter.convert(0.0, CANONICAL_TEMPERATURE_UNIT, unit)
        converted = TemperatureConverter.convert(
            numeric, CANONICAL_TEMPERATURE_UNIT, unit
        )
    except (HomeAssistantError, TypeError, ValueError):
        return None
    result = converted - zero
    return result if isfinite(result) else None
