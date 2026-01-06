# Smart Offset Thermostat

[![HACS](https://img.shields.io/badge/HACS-Custom-blue.svg)](#installation)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/License-PolyForm%20Noncommercial-blue.svg)](LICENSE)

**Smart Offset Thermostat** is a Home Assistant integration that creates a virtual thermostat which learns and compensates the temperature offset of physical radiator thermostats using an external room temperature sensor.

It is designed for setups where the built-in thermostat sensor is inaccurate (e.g. behind curtains, in niches, near windows or radiators).

---

## ✨ Key Features

- 📏 Learns thermostat temperature offset automatically
- 🌡️ Uses an external temperature sensor for accurate room temperature
- 🎯 Virtual climate entity (usable in dashboards and HomeKit)
- 🧠 Adaptive learning without aggressive oscillation
- 🪟 Window sensor support (automatic setback)
- 🚀 Boost mode (temporary full heating)
- ♻️ Reset learned offset at any time
- 🧊 Adaptive over-temperature correction
- ⚙️ Fully configurable via UI (no YAML required)

---

## 🧠 How It Works

1. Select:
   - a physical thermostat
   - an external room temperature sensor
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

## 🪟 Window Sensor

- Window open → thermostat set to minimum
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
- Boost duration

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
