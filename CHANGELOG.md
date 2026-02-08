# Changelog

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
