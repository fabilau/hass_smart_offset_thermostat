# Changelog

## v2.0.5

- Fixed window status updates after a window is closed.

## v2.0.4

### Reliable repair of the 2.0 UI regression

- Added schema 3.5 so installations that reached schema 3.4 without restoring their existing entities receive one final targeted repair pass.
- Corrected the interaction with Home Assistant's **disable newly added entities** preference: existing rows marked `disabled_by=integration` by the faulty 2.0.0/2.0.1 defaults are repaired once, while direct user- and config-entry-disable choices remain untouched and future new entities still follow the preference.
- Added real Home Assistant coverage for the still-visible, disabled registry state shown by affected installations and for an exact v2.0.1 upgrade fixture.

## v2.0.3

### Guided recovery for missing rooms

- Added a guided **Restore an existing room** path to the normal integration setup. It detects strictly validated Smart Offset Thermostat entities whose config entry was lost and reconnects them to the selected physical thermostat and room sensor.
- Preserved existing entity IDs, registry IDs, unique IDs, device IDs, areas, custom names, icons, labels and dashboard or automation references during recovery.
- Copied learned offsets, the saved preset choice and counters to the recovered config entry without overwriting conflicting data. A retained checkpoint makes interrupted recovery and sudden power loss safe to resume; it is removed on an intentional uninstall.
- Added a permanent registry identity so a restored room can be recovered again after a later config-entry loss without creating duplicate entities.
- Re-enabled only entities disabled by the 2.0.0/2.0.1 regression. Explicit user disable choices remain untouched.
- Added the one-shot schema 3.4 repair so installations that briefly received an incomplete 3.3 migration are repaired safely on their next update as well.
- Added strict stale-flow, shared-device, duplicate-identity and storage-conflict checks before registry changes begin.
- Validated eight simultaneous room recoveries with 216 registry entities and all six platforms on Home Assistant 2025.12.5 and 2026.2.3, including reload and a complete second-recovery cycle.
- Made Setup and every temperature option follow Home Assistant's configured Celsius or Fahrenheit unit while retaining backward-compatible stored values.
- Completed the modern setup, options, entity and state text in every bundled language.
- Added a two-version Home Assistant test matrix for restart recovery and migrations, alongside deterministic controller regression tests.
- Reworked the README into a concise, benefit-led user guide with a dedicated recovery walkthrough.

## v2.0.2

### Entity recovery

- Restored the pre-2.0 enabled-by-default behaviour for the legacy preset control and all diagnostic/statistics entities.
- Added config-entry schema 3.3 to re-enable entities that 2.0.0/2.0.1 had marked `disabled_by=integration`, so they immediately provide states again after the upgrade.
- Kept every explicit user, device and config-entry disable decision intact. The Home Assistant preference to disable newly added entities is also respected.
- Kept config-entry IDs, device IDs, entity IDs, areas and existing settings unchanged during the repair.

## v2.0.1

### Upgrade recovery

- Added config-entry schema 3.2 to recover existing devices whose required thermostat or room-sensor reference was left in Options by a partial/intermediate upgrade.
- Added a defensive startup repair for already-current entries so their original `entry_id`, device and entity registry links are reused instead of requiring a fresh setup.
- Backfilled the physical thermostat as the config-entry unique ID for legacy entries when it is safe to do so, preventing accidental duplicate setups.
- Prevented old repaired entries and manually created replacement entries from controlling the same physical thermostat at the same time; the older original entry keeps ownership of its established entities.
- Added regression coverage for misplaced source entities, stale option duplicates and idempotent 3.2 migration.

## v2.0.0 — 2026-08-02

### Native climate and user interface

- Rebuilt the primary entity as a native Home Assistant climate control with target temperature, presets, HVAC action and supported physical HVAC modes.
- Added Heat/Cool regulation, physical mode discovery, passive Auto/Dry/Fan-only handling and per-preset HVAC selection.
- Added authoritative Off/On control. Off is forwarded to the physical climate entity and stops regulation, learning, manual synchronisation and Boost; On restores the last non-Off mode where supported.
- Replaced the JSON Modes editor with a visual preset manager for creating, editing, renaming and deleting presets. The legacy select remains enabled and compatible with existing automations.
- Reworked setup into a short two-step flow, added source-entity reconfiguration, and grouped Options into Presets, Windows & Boost, Manual control, Learning and Expert pages.

### Control, safety and observability

- Reworked setpoint calculation into bounded, device-step-aware control logic with target-change rebasing, slew limiting, Heat/Cool direction handling and deterministic tests.
- Changed manual physical-thermostat synchronisation to apply the observed setpoint delta once after a confirmation delay. Controller commands, acknowledgements and intermediate transitions are classified as echoes to prevent feedback loops.
- Hardened window and Boost overrides so they cannot contaminate learning, added delayed multi-window handling and immediate safe rebasing when an override ends.
- Added signed and absolute error, mean absolute error, comfort score, temperature trend, normalised control output, confirmed setpoint, applied correction and manual-change count sensors.
- Added Window open, Boost running, Control active and Controller problem binary sensors, plus downloadable integration diagnostics.
- Centralised all 22 Last decision enum values and completed entity/state translations in every bundled locale.
- Initialised and consistently reset stable-learning state, including `_stable_since`, `_stable_target`, and `_stable_last_set`.

### Safe migrations

- Added idempotent config-entry migration to schema 3.1 while preserving unknown keys. Schema 3.2 in v2.0.1 additionally repairs partially migrated source-entity references.
- Converted legacy Modes, individual mode settings and active Mode state to native presets without losing targets, pause behaviour or the learned offset.
- Preserved legacy implicit Away/Summer defaults when no mode configuration had ever been saved.
- Migrated single-window configuration to the multi-window format while retaining the previous delay behaviour.
- Versioned persisted runtime data, preserved counters, and adopted the current physical HVAC mode on first start to avoid an unexpected heat/cool transition.
- Kept existing legacy Mode select entities usable for automation compatibility.

### GitHub issues addressed

- [#4 — Automatic AC Mode Selection Based on Season and Setpoint](https://github.com/fabilau/hass_smart_offset_thermostat/issues/4): added physical HVAC discovery, per-preset mode selection, seasonal presets and Heat/Cool-aware regulation; Auto, Dry and Fan-only remain device-controlled on compatible devices.
- [#10 — Little cosmetic issue due to CORB](https://github.com/fabilau/hass_smart_offset_thermostat/issues/10): removed the externally loaded License Shields badge from the README and replaced it with a normal local license link.
- [#14 — object has no attribute `_stable_since`](https://github.com/fabilau/hass_smart_offset_thermostat/issues/14): stable-learning fields are now initialised in the controller constructor and reset consistently.
- [#15 — `deadband_init` missing from Last decision options](https://github.com/fabilau/hass_smart_offset_thermostat/issues/15): all runtime decisions now come from one complete enum list shared by the sensor and translations.
- [#16 — Manual thermostat change sync feedback loop](https://github.com/fabilau/hass_smart_offset_thermostat/issues/16): added echo/transition tracking, delayed candidate confirmation and one-time delta-based target adoption.
- [#17 — Turn Smart Offset Thermostat off](https://github.com/fabilau/hass_smart_offset_thermostat/issues/17): added native Off/On and forwarded Off to the underlying climate entity using its supported service path.
- [#18 — Transform mode in preset](https://github.com/fabilau/hass_smart_offset_thermostat/issues/18): promoted Modes to native climate presets and added a form-based preset editor while preserving the legacy select bridge.

## v1.1.33
- Added configurable window-open delay before setback
- Migration: existing entries default to 0s delay (no behavior change)


## v1.1.32
- Added configurable modes list (JSON) with add/remove support
- Mode select updates immediately after saving options


## v1.1.31
- Added mode select with per-mode target temperature and pause control (replaces pause entities)
- Post-start refresh to avoid unknown states after restart


## v1.1.30
- Added pause controls to stop learning and setpoint changes when HVAC is off or a pause entity is active


## v1.1.29
- Added russian language support


## v1.1.28
- Fix: multiple window sensors now normalized so all selected sensors trigger
- Fix: window close triggers forced update (cooldown no longer blocks forced control)


## v1.1.27
- Migration: automatically convert legacy window_sensor_entity to window_sensor_entities (multi window sensors)


## v1.1.22
- Fix: when starting inside deadband and last_set is unknown, initialize TRV setpoint to baseline


## v1.1.21
- Fix: prevent learning/hold from being influenced by boost mode
- Minor: stability reset uses computed deadband value


## v1.1.20
- Fix: removed stray 't_trv = _clamp' line that broke setpoint computation
- Fix: stability tracking no longer reset each tick (hold/stable learn works)


## v1.1.19
- Fix: hold-in-deadband no longer resets every tick
- Fix: persistent over-temperature correction now uses real time-window detection (no immediate revert)


## v1.1.18
- Fix: indentation error in window sensor branch (startup)


## v1.1.17
- Added 'hold in deadband' to prevent reverting after reaching target
- Added stability-based learning: convert successful TRV setpoint into learned offset


## v1.1.16
- Fix: syntax error in controller caused by escaped quotes


## v1.1.15
- Fix: adaptive over-temp correction now persists via bias so it doesn't revert on next tick


## v1.1.14
- README: added support/donation section
- Author renamed to fabilau


## v1.1.12
- Added HACS metadata (hacs.json) and improved README for HACS installation


## v1.1.11
- Fix: remaining indentation error in controller (_force_next_control reset)


## v1.1.10
- Fix: indentation error in controller (startup)


## v1.1.9
- Fix: adaptive over-temp correction now works reliably (force flag is no longer cleared too early)


## v1.1.8
- Added adaptive over-temp correction: if room stays too warm, reduce TRV further over time (configurable)


## v1.1.7
- Fix: window open/close now bypasses cooldown so TRV returns immediately after closing


## v1.1.6
- Added button: reset learned offset
- Fix: use persisted offset for baseline computation


## v1.1.5
- Fix: window sensor changes are now handled immediately via state listener (no reload needed)


## v1.1.4
- Fix: On target change, rebase TRV setpoint to learned baseline even inside deadband


## v1.1.3
- Added sensors: window status, boost active/remaining, control paused


## v1.1.2
- Window sensor is now configurable in Options (editable after setup)
- Migration: existing entries copy the window sensor from initial setup into options


## v1.1.1
- Added additional translations (en/fr/es/it/nl/pl/pt/pt-BR/sv/no)
- Added MDI icons for entities (integration logo still requires HA brands)


## v1.1.0
- Added Boost switch (max heat for configurable duration)
- Added optional window sensor: open => set TRV to minimum


## v1.0.9
- Added full documentation (README DE/EN, Changelog)

## v1.0.8
- Icons, logos, HACS metadata
