# Smart Offset Thermostat

[![HACS](https://img.shields.io/badge/HACS-Custom-blue.svg)](#installation)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)

**Smart Offset Thermostat** is a Home Assistant integration that creates a virtual thermostat which learns and compensates the temperature offset of physical radiator thermostats using an external room temperature sensor.

It is designed for setups where the built-in thermostat sensor is inaccurate (e.g. behind curtains, in niches, near windows or radiators).

Smart Offset Thermostat is **manufacturer-agnostic by design**.  
It operates exclusively by adjusting the **target (setpoint) temperature** and continuously learns from the system behavior.  
Because it does **not require direct valve control or vendor-specific APIs**, it works with a wide range of thermostats and heating systems.

This approach ensures **broad compatibility** across different manufacturers, protocols, and hardware generations, as long as the device is exposed as a standard Home Assistant climate entity.

---

## ✨ Key Features

- 📏 Learns thermostat temperature offset automatically
- 🌡️ Uses an external temperature sensor for accurate room temperature
- 🎯 Virtual climate entity (usable in dashboards and HomeKit)
- 🧠 Adaptive learning without aggressive oscillation
- 🪟 Multi Window sensor support (automatic setback)
- 🚀 Boost mode (temporary full heating)
- ♻️ Reset learned offset at any time
- 🧊 Adaptive over-temperature correction
- 🧭 Mode select with per-mode targets and pause control
- ⚙️ Fully configurable via UI (no YAML required)

---

## 🧠 How It Works

1. Select:
   - a physical thermostat
   - an external room temperature sensor
   - a window sensor
   - a desired room temperature

2. The integration compares:
   - thermostat temperature
   - real room temperature

3. It adjusts the thermostat setpoint until the room matches the target and learns the required offset.

---

## 🌡️ Adaptive Over-Temperature Correction

If a room stays too warm for a longer time, the integration gradually reduces the thermostat setpoint further to avoid overheating.

Default values (configurable):
- Evaluation window: 30 minutes
- Required cooling: 0.1 °C
- Reduction step: 0.5 °C

---

## 🪟 Multi Window Sensor

- Define multiple window sensors
- Window open → thermostat set to minimum
- Optional delay before setback (default: 60 seconds)
- Window closed → target restored immediately
- Learning is paused while the window is open

---

## 🚀 Boost Mode

- Temporarily sets the thermostat to maximum temperature
- Automatically returns after the configured duration
- Learning is paused during boost

---

## ♻️ Reset Offset

A button entity resets the learned offset to 0.0 and applies it immediately.

---

## ⚙️ Configuration

All settings are configurable via the Home Assistant UI:
- Learning behavior
- Cooldown & deadband
- Thermostat limits
- Adaptive over-temperature correction
- Window sensor
- Window open delay
- Boost duration
- Mode settings (targets, pause, add/remove)

---

## 🧭 Modes (customizable)

In Options you can edit the `Modes` field as JSON.  
Each mode is an object with:
- `id` (string, used in the Mode select)
- `target` (number)
- `pause` (true/false)

How to use:
- After saving, the Mode select will update; pick the active mode there.
- The current mode’s `target` becomes the room target.
- If `pause` is true, learning and setpoint changes are suspended.
- Remove a mode by deleting it from the JSON list and saving.

Example:
```
[
  {"id": "present", "target": 22.0, "pause": false},
  {"id": "away", "target": 18.0, "pause": true},
  {"id": "guest", "target": 21.0, "pause": false}
]
```

---

## 🏠 HomeKit Support

The integration exposes a proper climate entity and works seamlessly with HomeKit via the Home Assistant HomeKit Bridge.

---

## 📦 Installation

### HACS (Custom Repository)

1. HACS → Integrations
2. Custom repositories
3. Add this GitHub repository
4. Category: Integration
5. Install and restart Home Assistant

### Manual

Copy `custom_components/smart_offset_thermostat` to `config/custom_components/` and restart Home Assistant.

---

---

## ❤️ Support the Project

If you like this project and want to support its further development, you are very welcome to do so.

Your support helps to:
- improve stability and algorithms
- add new features
- maintain compatibility with future Home Assistant versions

👉 **Revolut donation:**  
`https://revolut.me/fabian599`

Thank you for your support! 🙏

## 🧾 License

This project is licensed under the PolyForm Noncommercial License.
You may use, modify and share it for non-commercial purposes.
Commercial use, selling, or offering this software as part of a paid product or service is not permitted.
