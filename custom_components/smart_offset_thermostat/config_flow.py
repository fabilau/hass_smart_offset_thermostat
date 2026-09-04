"""Config and options flows for Smart Offset Thermostat."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
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
    CONF_RECOVERY_DEVICE_ID,
    CONF_RECOVERY_FINGERPRINT,
    CONF_RECOVERY_SOURCE_ENTRY_ID,
    CONF_REGISTRY_IDENTITY,
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
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
    DEFAULT_BOOST_DURATION_SEC,
    DEFAULT_CONTROL_GAIN,
    DEFAULT_COOLDOWN_SEC,
    DEFAULT_DEADBAND,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_INTERVAL_SEC,
    DEFAULT_LEARN_RATE,
    DEFAULT_MANUAL_DELAY_SEC,
    DEFAULT_MANUAL_TARGET_SYNC,
    DEFAULT_PAUSE_ON_HVAC_OFF,
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
    DEFAULTS,
    DOMAIN,
    PRESET_HVAC_KEEP,
    PRESET_HVAC_MODES,
    REGULATED_HVAC_MODES,
    default_presets,
    entry_registry_identity,
)
from .control import normalize_entity_ids
from .recovery import OrphanedRegistryGroup, find_orphaned_registry_groups
from .temperature import (
    delta_from_celsius,
    delta_to_celsius,
    from_celsius,
    to_celsius,
)

CONF_PRESET_ID = "preset_id"
CONF_DELETE_PRESET = "delete_preset"
CONF_RECOVERY_CANDIDATE = "recovery_candidate"

_PRESET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_CONFIGURED_HVAC_MODES = frozenset(PRESET_HVAC_MODES) - {PRESET_HVAC_KEEP}


def _temperature_unit(hass: HomeAssistant) -> str:
    """Return Home Assistant's configured display temperature unit."""
    unit = getattr(
        getattr(getattr(hass, "config", None), "units", None),
        "temperature_unit",
        UnitOfTemperature.CELSIUS,
    )
    return str(unit or UnitOfTemperature.CELSIUS)


def _temperature_form_value(
    hass: HomeAssistant, value: Any, *, difference: bool = False
) -> float:
    """Convert a canonical setting to a clean value for a form."""
    unit = _temperature_unit(hass)
    converted = (
        delta_from_celsius(value, unit) if difference else from_celsius(value, unit)
    )
    if converted is None:
        raise ValueError("Invalid canonical temperature setting")
    return round(converted, 6)


def _temperature_canonical_value(
    hass: HomeAssistant, value: Any, *, difference: bool = False
) -> float:
    """Convert a submitted form temperature to canonical Celsius."""
    unit = _temperature_unit(hass)
    converted = delta_to_celsius(value, unit) if difference else to_celsius(value, unit)
    if converted is None:
        raise ValueError("Invalid submitted temperature setting")
    return round(converted, 6)


def _canonical_temperature_updates(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    *,
    absolute_keys: tuple[str, ...] = (),
    difference_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return form values with temperature fields normalized to Celsius."""
    updates = dict(user_input)
    for key in absolute_keys:
        if key in updates:
            updates[key] = _temperature_canonical_value(hass, updates[key])
    for key in difference_keys:
        if key in updates:
            updates[key] = _temperature_canonical_value(
                hass, updates[key], difference=True
            )
    return updates


def _temperature_selector(
    hass: HomeAssistant,
    *,
    default_min: float = 5.0,
    default_max: float = 35.0,
    step: float = 0.5,
    difference: bool = False,
) -> NumberSelector:
    """Create a temperature selector with converted bounds and step size."""
    return NumberSelector(
        NumberSelectorConfig(
            min=_temperature_form_value(hass, default_min, difference=difference),
            max=_temperature_form_value(hass, default_max, difference=difference),
            step=_temperature_form_value(hass, step, difference=True),
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=_temperature_unit(hass),
        )
    )


def _supported_hvac_modes(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return safe, ordered HVAC choices exposed by a physical climate entity."""
    state = hass.states.get(entity_id)
    if state is None:
        return []

    raw_modes = state.attributes.get("hvac_modes")
    if isinstance(raw_modes, str):
        raw_modes = [raw_modes]
    elif not isinstance(raw_modes, (list, tuple)):
        raw_modes = []

    candidates = [*raw_modes, state.state]
    modes: list[str] = []
    for value in candidates:
        mode = str(value).lower()
        if mode in _CONFIGURED_HVAC_MODES and mode not in modes:
            modes.append(mode)

    try:
        features = int(state.attributes.get("supported_features", 0))
    except (TypeError, ValueError):
        features = 0
    if features & ClimateEntityFeature.TURN_OFF and "off" not in modes:
        modes.insert(0, "off")

    return modes


def _default_hvac_mode(hass: HomeAssistant, entity_id: str) -> str:
    """Choose a useful initial HVAC mode from the physical thermostat."""
    modes = _supported_hvac_modes(hass, entity_id)
    state = hass.states.get(entity_id)
    if state is not None and state.state in REGULATED_HVAC_MODES:
        return str(state.state)
    if "heat" in modes:
        return "heat"
    if "cool" in modes:
        return "cool"
    return modes[0] if modes else "heat"


def _entity_errors(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    *,
    exclude_entry_id: str | None = None,
) -> dict[str, str]:
    """Validate selected source entities without rejecting transient states."""
    errors: dict[str, str] = {}
    climate = hass.states.get(user_input[CONF_CLIMATE])
    if climate is None:
        errors[CONF_CLIMATE] = "entity_not_found"
    else:
        try:
            supported_features = int(climate.attributes.get("supported_features", 0))
        except (TypeError, ValueError):
            supported_features = 0
        modes = _supported_hvac_modes(hass, user_input[CONF_CLIMATE])
        if not (
            supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
        ) or not set(modes).intersection(REGULATED_HVAC_MODES):
            errors[CONF_CLIMATE] = "unsupported_climate"
    if hass.states.get(user_input[CONF_ROOM_SENSOR]) is None:
        errors[CONF_ROOM_SENSOR] = "entity_not_found"
    if any(
        entry.entry_id != exclude_entry_id
        and entry.data.get(CONF_CLIMATE) == user_input[CONF_CLIMATE]
        for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        errors[CONF_CLIMATE] = "already_configured"
    return errors


def _orphaned_registry_groups(
    hass: HomeAssistant,
) -> list[OrphanedRegistryGroup]:
    """Return repair candidates using only public Home Assistant registries."""
    entries = hass.config_entries.async_entries(DOMAIN)
    areas = ar.async_get(hass)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    return find_orphaned_registry_groups(
        entity_registry.entities.values(),
        device_registry.devices.values(),
        (entry.entry_id for entry in entries),
        deleted_entity_entries=getattr(
            entity_registry, "deleted_entities", {}
        ).values(),
        deleted_device_entries=getattr(device_registry, "deleted_devices", {}).values(),
        claimed_registry_identities=(
            entry_registry_identity(entry) for entry in entries
        ),
        area_names={area.id: area.name for area in areas.async_list_areas()},
    )


class SmartOffsetThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup and reconfiguration."""

    VERSION = CONFIG_ENTRY_VERSION
    MINOR_VERSION = CONFIG_ENTRY_MINOR_VERSION

    def __init__(self) -> None:
        """Initialize the two-step setup flow."""
        super().__init__()
        self._setup_data: dict[str, Any] = {}
        self._selected_recovery: OrphanedRegistryGroup | None = None
        self._recovery_candidates: dict[str, OrphanedRegistryGroup] = {}

    def _current_recovery(self) -> OrphanedRegistryGroup | None:
        """Revalidate the selected fingerprint against current registry state."""
        selected = self._selected_recovery
        if selected is None:
            return None
        return next(
            (
                group
                for group in _orphaned_registry_groups(self.hass)
                if group.source_entry_id == selected.source_entry_id
                and group.registry_identity == selected.registry_identity
                and group.device_id == selected.device_id
                and group.fingerprint == selected.fingerprint
            ),
            None,
        )

    async def _async_source_form(
        self,
        *,
        step_id: str,
        user_input: dict[str, Any] | None,
        recovery: OrphanedRegistryGroup | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Render the shared source selector for setup and recovery."""
        if recovery is not None:
            self._selected_recovery = recovery
            recovery = self._current_recovery()
            if recovery is None:
                return self.async_abort(reason="repair_not_available")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _entity_errors(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_CLIMATE])
                self._abort_if_unique_id_configured()
                self._setup_data = dict(user_input)
                if recovery is not None:
                    self._setup_data.update(
                        {
                            CONF_REGISTRY_IDENTITY: recovery.registry_identity,
                            CONF_RECOVERY_SOURCE_ENTRY_ID: recovery.source_entry_id,
                            CONF_RECOVERY_DEVICE_ID: recovery.device_id,
                            CONF_RECOVERY_FINGERPRINT: recovery.fingerprint,
                        }
                    )
                return await self.async_step_comfort()

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIMATE): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_ROOM_SENSOR): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        device_class=SensorDeviceClass.TEMPERATURE,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders=(
                {"room_name": recovery.label} if recovery is not None else None
            ),
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select the physical thermostat and external room sensor."""
        if user_input is None and _orphaned_registry_groups(self.hass):
            return await self.async_step_repair_or_setup()
        return await self._async_source_form(step_id="user", user_input=user_input)

    async def async_step_repair_or_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Offer recovery without blocking creation of a separate thermostat."""
        if not _orphaned_registry_groups(self.hass):
            return await self._async_source_form(step_id="user", user_input=None)
        return self.async_show_menu(
            step_id="repair_or_setup",
            menu_options=["repair_select", "setup_new"],
        )

    async def async_step_setup_new(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Explicitly create a new thermostat while leaving orphans untouched."""
        self._selected_recovery = None
        return await self._async_source_form(step_id="setup_new", user_input=user_input)

    async def async_step_repair_select(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select one friendly-labelled orphaned room for recovery."""
        groups = _orphaned_registry_groups(self.hass)
        if not groups:
            return self.async_abort(reason="repair_not_available")

        if user_input is not None:
            # Resolve the opaque token against the exact mapping that was shown
            # to this flow. Rebuilding positional tokens here could select a
            # different room if another recovery completed while the form was
            # open and shifted the candidate order.
            selected = self._recovery_candidates.get(
                str(user_input.get(CONF_RECOVERY_CANDIDATE, ""))
            )
            if selected is None:
                return self.async_abort(reason="repair_not_available")
            self._selected_recovery = selected
            if self._current_recovery() is None:
                return self.async_abort(reason="repair_not_available")
            return await self.async_step_repair_sources()

        self._recovery_candidates = {
            f"candidate_{index}": group for index, group in enumerate(groups)
        }
        options: list[SelectOptionDict] = [
            {"value": token, "label": group.label}
            for token, group in self._recovery_candidates.items()
        ]
        return self.async_show_form(
            step_id="repair_select",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RECOVERY_CANDIDATE,
                        default=next(iter(self._recovery_candidates)),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_repair_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconnect physical source entities to the selected room."""
        recovery = self._current_recovery()
        if recovery is None:
            return self.async_abort(reason="repair_not_available")
        return await self._async_source_form(
            step_id="repair_sources",
            user_input=user_input,
            recovery=recovery,
        )

    async def async_step_comfort(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure initial comfort settings and optional features."""
        recovery = None
        if self._selected_recovery is not None:
            recovery = self._current_recovery()
            if recovery is None:
                return self.async_abort(reason="repair_not_available")
        climate_entity = self._setup_data[CONF_CLIMATE]
        hvac_modes = _supported_hvac_modes(self.hass, climate_entity)
        default_hvac_mode = _default_hvac_mode(self.hass, climate_entity)

        if user_input is not None:
            settings = _canonical_temperature_updates(
                self.hass,
                user_input,
                absolute_keys=(CONF_ROOM_TARGET,),
            )
            selected_hvac_mode = str(settings.pop(CONF_HVAC_MODE))
            room_target = float(settings[CONF_ROOM_TARGET])
            presets = default_presets(
                room_target,
                selected_hvac_mode,
                ac_capable="cool" in hvac_modes,
            )
            for preset in presets:
                if preset.get(CONF_HVAC_MODE) not in hvac_modes:
                    preset[CONF_HVAC_MODE] = selected_hvac_mode
            data = {
                **self._setup_data,
                **settings,
                CONF_PRESETS: presets,
            }
            climate_state = self.hass.states.get(data[CONF_CLIMATE])
            room_state = self.hass.states.get(data[CONF_ROOM_SENSOR])
            climate_name = (
                climate_state.name if climate_state is not None else data[CONF_CLIMATE]
            )
            room_name = (
                room_state.name if room_state is not None else data[CONF_ROOM_SENSOR]
            )
            return self.async_create_entry(
                title=(
                    recovery.label
                    if recovery is not None
                    else f"{climate_name} ↔ {room_name}"
                ),
                data=data,
                description=("repair_successful" if recovery is not None else None),
                description_placeholders=(
                    {"room_name": recovery.label} if recovery is not None else None
                ),
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ROOM_TARGET,
                    default=_temperature_form_value(self.hass, DEFAULT_ROOM_TARGET),
                ): _temperature_selector(self.hass),
                vol.Required(CONF_HVAC_MODE, default=default_hvac_mode): SelectSelector(
                    SelectSelectorConfig(
                        options=hvac_modes,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="hvac_mode",
                    )
                ),
                vol.Optional(CONF_WINDOW_SENSORS, default=[]): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional(
                    CONF_WINDOW_DELAY_SEC, default=DEFAULT_WINDOW_DELAY_SEC
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_ENABLE_LEARNING, default=DEFAULT_ENABLE_LEARNING
                ): BooleanSelector(),
                vol.Optional(
                    CONF_MANUAL_TARGET_SYNC,
                    default=DEFAULT_MANUAL_TARGET_SYNC,
                ): BooleanSelector(),
                vol.Optional(
                    CONF_PAUSE_ON_HVAC_OFF,
                    default=DEFAULT_PAUSE_ON_HVAC_OFF,
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="comfort", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Allow source entities to be changed without recreating the thermostat."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _entity_errors(
                self.hass,
                user_input,
                exclude_entry_id=entry.entry_id,
            )
            if not errors:
                supported_modes = {
                    PRESET_HVAC_KEEP,
                    *_supported_hvac_modes(self.hass, user_input[CONF_CLIMATE]),
                }
                options = deepcopy(dict(entry.options))
                source_presets = options.get(CONF_PRESETS, entry.data.get(CONF_PRESETS))
                if isinstance(source_presets, list):
                    presets = deepcopy(source_presets)
                    for preset in presets:
                        if not isinstance(preset, dict):
                            continue
                        if preset.get(CONF_HVAC_MODE) not in supported_modes:
                            preset[CONF_HVAC_MODE] = PRESET_HVAC_KEEP
                    options[CONF_PRESETS] = presets
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=user_input[CONF_CLIMATE],
                    data_updates={
                        CONF_CLIMATE: user_input[CONF_CLIMATE],
                        CONF_ROOM_SENSOR: user_input[CONF_ROOM_SENSOR],
                    },
                    options=options,
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CLIMATE, default=entry.data.get(CONF_CLIMATE)
                ): EntitySelector(EntitySelectorConfig(domain="climate")),
                vol.Required(
                    CONF_ROOM_SENSOR, default=entry.data.get(CONF_ROOM_SENSOR)
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        device_class=SensorDeviceClass.TEMPERATURE,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SmartOffsetThermostatOptionsFlow:
        """Return the modern options flow handler."""
        return SmartOffsetThermostatOptionsFlow()


class SmartOffsetThermostatOptionsFlow(config_entries.OptionsFlow):
    """Manage focused groups of controller options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the options navigation menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "presets",
                "window_boost",
                "manual",
                "learning",
                "expert",
            ],
        )

    def _value(self, key: str, fallback: Any | None = None) -> Any:
        """Resolve a value without treating valid falsey values as missing."""
        if key in self.config_entry.options:
            return self.config_entry.options[key]
        if key in self.config_entry.data:
            return self.config_entry.data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return fallback

    def _merged_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge one partial form without discarding unrelated settings."""
        options = deepcopy(dict(self.config_entry.options))
        options.update(updates)
        return options

    def _window_entities(self) -> list[str]:
        """Return normalized plural window entities from options or data."""
        value = self._value(CONF_WINDOW_SENSORS)
        if value is None:
            value = self._value(CONF_WINDOW_SENSOR)
        return normalize_entity_ids(value)

    def _presets(self) -> list[dict[str, Any]]:
        """Return a fresh preset list, including compatibility fallbacks."""
        value = self._value(CONF_PRESETS)
        if not isinstance(value, list) or not value:
            value = self._value(CONF_MODES)
        if isinstance(value, list) and value:
            normalized = [
                deepcopy(item)
                for item in value
                if isinstance(item, dict) and item.get("id")
            ]
            if normalized:
                return normalized

        try:
            target = float(self._value(CONF_ROOM_TARGET, DEFAULT_ROOM_TARGET))
        except (TypeError, ValueError):
            target = DEFAULT_ROOM_TARGET
        climate_entity = str(self.config_entry.data.get(CONF_CLIMATE, ""))
        modes = _supported_hvac_modes(self.hass, climate_entity)
        return default_presets(
            target,
            _default_hvac_mode(self.hass, climate_entity),
            ac_capable="cool" in modes,
        )

    async def async_step_presets(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Choose whether to create or edit a preset."""
        return self.async_show_menu(
            step_id="presets", menu_options=["preset_new", "preset_select"]
        )

    async def async_step_preset_select(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select an existing preset for editing."""
        preset_ids = list(
            dict.fromkeys(
                str(item.get("id")) for item in self._presets() if item.get("id")
            )
        )
        if user_input is not None:
            self._editing_preset_id = str(user_input[CONF_PRESET_ID])
            return await self.async_step_preset_edit()

        return self.async_show_form(
            step_id="preset_select",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PRESET_ID, default=preset_ids[0]): SelectSelector(
                        SelectSelectorConfig(
                            options=preset_ids,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_preset_new(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create a new preset using the same safe editor."""
        return await self._async_preset_form(
            step_id="preset_new", original_id=None, user_input=user_input
        )

    async def async_step_preset_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit or delete the selected preset."""
        original_id = getattr(self, "_editing_preset_id", None)
        if original_id is None:
            return await self.async_step_presets()
        return await self._async_preset_form(
            step_id="preset_edit",
            original_id=original_id,
            user_input=user_input,
        )

    async def _async_preset_form(
        self,
        *,
        step_id: str,
        original_id: str | None,
        user_input: dict[str, Any] | None,
    ) -> config_entries.ConfigFlowResult:
        """Render and process the create/edit preset form."""
        presets = self._presets()
        current = next(
            (item for item in presets if str(item.get("id")) == original_id),
            {},
        )
        errors: dict[str, str] = {}
        form_values = dict(current)

        if user_input is not None:
            form_values.update(user_input)
            if original_id is not None and user_input.get(CONF_DELETE_PRESET):
                if len(presets) <= 1:
                    errors["base"] = "last_preset"
                else:
                    updated = [
                        item for item in presets if str(item.get("id")) != original_id
                    ]
                    return self.async_create_entry(
                        title="",
                        data=self._merged_options({CONF_PRESETS: updated}),
                    )
            else:
                preset_id = str(user_input[CONF_PRESET_ID]).strip()
                other_ids = {
                    str(item.get("id"))
                    for item in presets
                    if str(item.get("id")) != original_id
                }
                if not _PRESET_ID_PATTERN.fullmatch(preset_id):
                    errors[CONF_PRESET_ID] = "invalid_preset_id"
                elif preset_id in other_ids:
                    errors[CONF_PRESET_ID] = "duplicate_preset"
                else:
                    target = _temperature_canonical_value(
                        self.hass, user_input[CONF_ROOM_TARGET]
                    )
                    new_item = deepcopy(current)
                    new_item.update(
                        {
                            "id": preset_id,
                            "target": target,
                            "pause": bool(user_input["pause"]),
                            CONF_HVAC_MODE: str(user_input[CONF_HVAC_MODE]),
                        }
                    )
                    if original_id is None:
                        updated = [*presets, new_item]
                    else:
                        updated = [
                            new_item if str(item.get("id")) == original_id else item
                            for item in presets
                        ]
                    return self.async_create_entry(
                        title="",
                        data=self._merged_options({CONF_PRESETS: updated}),
                    )

        climate_entity = str(self.config_entry.data.get(CONF_CLIMATE, ""))
        hvac_modes = [
            PRESET_HVAC_KEEP,
            *_supported_hvac_modes(self.hass, climate_entity),
        ]
        current_hvac_mode = str(
            form_values.get(
                CONF_HVAC_MODE,
                _default_hvac_mode(self.hass, climate_entity),
            )
        )
        if current_hvac_mode not in hvac_modes:
            hvac_modes.append(current_hvac_mode)

        if user_input is not None and CONF_ROOM_TARGET in user_input:
            target_default = float(user_input[CONF_ROOM_TARGET])
        else:
            try:
                target = float(
                    form_values.get(
                        CONF_ROOM_TARGET,
                        form_values.get(
                            "target",
                            self._value(CONF_ROOM_TARGET, DEFAULT_ROOM_TARGET),
                        ),
                    )
                )
            except (TypeError, ValueError):
                target = DEFAULT_ROOM_TARGET
            target_default = _temperature_form_value(self.hass, target)

        fields: dict[Any, Any] = {
            vol.Required(
                CONF_PRESET_ID,
                default=str(form_values.get(CONF_PRESET_ID, form_values.get("id", ""))),
            ): TextSelector(TextSelectorConfig()),
            vol.Required(
                CONF_ROOM_TARGET, default=target_default
            ): _temperature_selector(self.hass),
            vol.Required(
                "pause", default=bool(form_values.get("pause", False))
            ): BooleanSelector(),
            vol.Required(CONF_HVAC_MODE, default=current_hvac_mode): SelectSelector(
                SelectSelectorConfig(
                    options=hvac_modes,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="hvac_mode",
                )
            ),
        }
        if original_id is not None:
            fields[vol.Optional(CONF_DELETE_PRESET, default=False)] = BooleanSelector()

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"preset_id": original_id or ""},
        )

    async def async_step_window_boost(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure window protection and boost."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data=self._merged_options(user_input)
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WINDOW_SENSORS, default=self._window_entities()
                ): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", multiple=True)
                ),
                vol.Optional(
                    CONF_WINDOW_DELAY_SEC,
                    default=self._value(
                        CONF_WINDOW_DELAY_SEC, DEFAULT_WINDOW_DELAY_SEC
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_BOOST_DURATION_SEC,
                    default=self._value(
                        CONF_BOOST_DURATION_SEC, DEFAULT_BOOST_DURATION_SEC
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=30,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="window_boost", data_schema=schema)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure manual thermostat interaction."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data=self._merged_options(user_input)
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MANUAL_TARGET_SYNC,
                    default=self._value(
                        CONF_MANUAL_TARGET_SYNC, DEFAULT_MANUAL_TARGET_SYNC
                    ),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_MANUAL_DELAY_SEC,
                    default=self._value(
                        CONF_MANUAL_DELAY_SEC, DEFAULT_MANUAL_DELAY_SEC
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_PAUSE_ON_HVAC_OFF,
                    default=self._value(
                        CONF_PAUSE_ON_HVAC_OFF, DEFAULT_PAUSE_ON_HVAC_OFF
                    ),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema)

    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure learning and adaptive over-temperature correction."""
        if user_input is not None:
            updates = _canonical_temperature_updates(
                self.hass,
                user_input,
                difference_keys=(CONF_STUCK_MIN_DROP, CONF_STUCK_STEP),
            )
            return self.async_create_entry(title="", data=self._merged_options(updates))

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_LEARNING,
                    default=self._value(CONF_ENABLE_LEARNING, DEFAULT_ENABLE_LEARNING),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_LEARN_RATE,
                    default=self._value(CONF_LEARN_RATE, DEFAULT_LEARN_RATE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=0.2,
                        step=0.01,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_STUCK_ENABLE,
                    default=self._value(CONF_STUCK_ENABLE, DEFAULT_STUCK_ENABLE),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_STUCK_SECONDS,
                    default=self._value(CONF_STUCK_SECONDS, DEFAULT_STUCK_SECONDS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=300,
                        max=7200,
                        step=60,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_STUCK_MIN_DROP,
                    default=_temperature_form_value(
                        self.hass,
                        self._value(CONF_STUCK_MIN_DROP, DEFAULT_STUCK_MIN_DROP),
                        difference=True,
                    ),
                ): _temperature_selector(
                    self.hass,
                    default_min=0.0,
                    default_max=1.0,
                    step=0.05,
                    difference=True,
                ),
                vol.Optional(
                    CONF_STUCK_STEP,
                    default=_temperature_form_value(
                        self.hass,
                        self._value(CONF_STUCK_STEP, DEFAULT_STUCK_STEP),
                        difference=True,
                    ),
                ): _temperature_selector(
                    self.hass,
                    default_min=0.1,
                    default_max=2.0,
                    step=0.1,
                    difference=True,
                ),
            }
        )
        return self.async_show_form(step_id="learning", data_schema=schema)

    async def async_step_expert(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure advanced controller parameters with cross-field validation."""
        errors: dict[str, str] = {}
        if user_input is not None:
            updates = _canonical_temperature_updates(
                self.hass,
                user_input,
                absolute_keys=(CONF_TRV_MIN, CONF_TRV_MAX),
                difference_keys=(CONF_DEADBAND, CONF_STEP_MAX, CONF_STEP_MIN),
            )
            if float(updates[CONF_TRV_MIN]) >= float(updates[CONF_TRV_MAX]):
                errors["base"] = "min_max"
            elif float(updates[CONF_STEP_MIN]) > float(updates[CONF_STEP_MAX]):
                errors["base"] = "step_order"
            else:
                return self.async_create_entry(
                    title="", data=self._merged_options(updates)
                )

        def form_value(
            key: str,
            default: Any,
            *,
            temperature: bool = False,
            difference: bool = False,
        ) -> Any:
            if user_input is not None and key in user_input:
                return user_input[key]
            value = self._value(key, default)
            if temperature or difference:
                return _temperature_form_value(self.hass, value, difference=difference)
            return value

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_INTERVAL_SEC,
                    default=form_value(CONF_INTERVAL_SEC, DEFAULT_INTERVAL_SEC),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=1800,
                        step=10,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(
                    CONF_DEADBAND,
                    default=form_value(
                        CONF_DEADBAND, DEFAULT_DEADBAND, difference=True
                    ),
                ): _temperature_selector(
                    self.hass,
                    default_min=0.0,
                    default_max=1.0,
                    step=0.1,
                    difference=True,
                ),
                vol.Optional(
                    CONF_CONTROL_GAIN,
                    default=form_value(CONF_CONTROL_GAIN, DEFAULT_CONTROL_GAIN),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=2.0,
                        step=0.05,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_STEP_MAX,
                    default=form_value(
                        CONF_STEP_MAX, DEFAULT_STEP_MAX, difference=True
                    ),
                ): _temperature_selector(
                    self.hass,
                    default_min=0.1,
                    default_max=3.0,
                    step=0.1,
                    difference=True,
                ),
                vol.Optional(
                    CONF_STEP_MIN,
                    default=form_value(
                        CONF_STEP_MIN, DEFAULT_STEP_MIN, difference=True
                    ),
                ): _temperature_selector(
                    self.hass,
                    default_min=0.1,
                    default_max=1.0,
                    step=0.1,
                    difference=True,
                ),
                vol.Optional(
                    CONF_TRV_MIN,
                    default=form_value(CONF_TRV_MIN, DEFAULT_TRV_MIN, temperature=True),
                ): _temperature_selector(self.hass, default_min=5.0, default_max=25.0),
                vol.Optional(
                    CONF_TRV_MAX,
                    default=form_value(CONF_TRV_MAX, DEFAULT_TRV_MAX, temperature=True),
                ): _temperature_selector(self.hass, default_min=10.0, default_max=35.0),
                vol.Optional(
                    CONF_COOLDOWN_SEC,
                    default=form_value(CONF_COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=3600,
                        step=30,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="expert", data_schema=schema, errors=errors)
