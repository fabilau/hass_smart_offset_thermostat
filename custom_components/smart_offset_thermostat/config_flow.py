from __future__ import annotations
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector, EntitySelectorConfig,
    NumberSelector, NumberSelectorConfig, NumberSelectorMode,
    BooleanSelector,
)

from .const import (
    DOMAIN,
    CONF_CLIMATE, CONF_ROOM_SENSOR, CONF_ROOM_TARGET,
    CONF_INTERVAL_SEC, CONF_DEADBAND, CONF_STEP_MAX, CONF_STEP_MIN,
    CONF_LEARN_RATE, CONF_TRV_MIN, CONF_TRV_MAX, CONF_COOLDOWN_SEC,
    CONF_ENABLE_LEARNING,
    CONF_WINDOW_SENSOR, CONF_WINDOW_SENSORS, CONF_BOOST_DURATION_SEC,
    CONF_STUCK_ENABLE, CONF_STUCK_SECONDS, CONF_STUCK_MIN_DROP, CONF_STUCK_STEP,
    DEFAULT_INTERVAL_SEC, DEFAULT_DEADBAND, DEFAULT_STEP_MAX, DEFAULT_STEP_MIN,
    DEFAULT_LEARN_RATE, DEFAULT_TRV_MIN, DEFAULT_TRV_MAX, DEFAULT_COOLDOWN_SEC,
    DEFAULT_ENABLE_LEARNING,
    DEFAULT_BOOST_DURATION_SEC,
    DEFAULT_STUCK_ENABLE, DEFAULT_STUCK_SECONDS, DEFAULT_STUCK_MIN_DROP, DEFAULT_STUCK_STEP
)

class SmartOffsetThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            title = f"{user_input[CONF_CLIMATE]} ↔ {user_input[CONF_ROOM_SENSOR]}"
            return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_CLIMATE): EntitySelector(EntitySelectorConfig(domain="climate")),
            vol.Required(CONF_ROOM_SENSOR): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(CONF_WINDOW_SENSORS): EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True)),
            vol.Required(CONF_ROOM_TARGET, default=22.0): NumberSelector(
                NumberSelectorConfig(min=5.0, max=30.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmartOffsetThermostatOptionsFlow(config_entry)

class SmartOffsetThermostatOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        super().__init__()
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        # Backward compatible: accept old single window_sensor_entity and new window_sensor_entities (list)
        window_defaults = opts.get(CONF_WINDOW_SENSORS)
        if window_defaults is None:
            old = opts.get(CONF_WINDOW_SENSOR)
            window_defaults = [old] if old else []
        elif isinstance(window_defaults, str):
            window_defaults = [window_defaults]

        schema = vol.Schema({
            vol.Optional(CONF_WINDOW_SENSORS, default=window_defaults): EntitySelector(EntitySelectorConfig(domain="binary_sensor", multiple=True)),
            vol.Optional(CONF_INTERVAL_SEC, default=opts.get(CONF_INTERVAL_SEC, DEFAULT_INTERVAL_SEC)): NumberSelector(
                NumberSelectorConfig(min=60, max=1800, step=10, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(CONF_DEADBAND, default=opts.get(CONF_DEADBAND, DEFAULT_DEADBAND)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_STEP_MAX, default=opts.get(CONF_STEP_MAX, DEFAULT_STEP_MAX)): NumberSelector(
                NumberSelectorConfig(min=0.5, max=3.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_STEP_MIN, default=opts.get(CONF_STEP_MIN, DEFAULT_STEP_MIN)): NumberSelector(
                NumberSelectorConfig(min=0.1, max=1.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_LEARN_RATE, default=opts.get(CONF_LEARN_RATE, DEFAULT_LEARN_RATE)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=0.2, step=0.01, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_TRV_MIN, default=opts.get(CONF_TRV_MIN, DEFAULT_TRV_MIN)): NumberSelector(
                NumberSelectorConfig(min=5.0, max=20.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_TRV_MAX, default=opts.get(CONF_TRV_MAX, DEFAULT_TRV_MAX)): NumberSelector(
                NumberSelectorConfig(min=20.0, max=35.0, step=0.5, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_COOLDOWN_SEC, default=opts.get(CONF_COOLDOWN_SEC, DEFAULT_COOLDOWN_SEC)): NumberSelector(
                NumberSelectorConfig(min=0, max=3600, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(CONF_BOOST_DURATION_SEC, default=opts.get(CONF_BOOST_DURATION_SEC, DEFAULT_BOOST_DURATION_SEC)): NumberSelector(
                NumberSelectorConfig(min=30, max=3600, step=30, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(CONF_ENABLE_LEARNING, default=opts.get(CONF_ENABLE_LEARNING, DEFAULT_ENABLE_LEARNING)): BooleanSelector(),
            vol.Optional(CONF_STUCK_ENABLE, default=opts.get(CONF_STUCK_ENABLE, DEFAULT_STUCK_ENABLE)): BooleanSelector(),
            vol.Optional(CONF_STUCK_SECONDS, default=opts.get(CONF_STUCK_SECONDS, DEFAULT_STUCK_SECONDS)): NumberSelector(
                NumberSelectorConfig(min=300, max=7200, step=60, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
            ),
            vol.Optional(CONF_STUCK_MIN_DROP, default=opts.get(CONF_STUCK_MIN_DROP, DEFAULT_STUCK_MIN_DROP)): NumberSelector(
                NumberSelectorConfig(min=0.0, max=1.0, step=0.05, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_STUCK_STEP, default=opts.get(CONF_STUCK_STEP, DEFAULT_STUCK_STEP)): NumberSelector(
                NumberSelectorConfig(min=0.1, max=2.0, step=0.1, mode=NumberSelectorMode.BOX, unit_of_measurement="°C")
            ),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
