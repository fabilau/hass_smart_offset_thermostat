<p align="center">
  <img src="docs/assets/logo.png" alt="Smart Offset Thermostat logo" width="160">
</p>

# 🌡️ Smart Offset Thermostat

<p align="center">
  <strong>Comfortable rooms—even when your thermostat measures in the wrong place.</strong>
</p>

Smart radiator thermostats often sit right next to the heat source. That can make the temperature on the display look perfect while the rest of the room still feels too cold—or already too warm.

Smart Offset Thermostat combines your existing thermostat with a separate room-temperature sensor. You choose how warm or cool the room should feel, and it takes care of the rest directly in Home Assistant.

<p align="center">
  <a href="#installation"><strong>Install Smart Offset Thermostat</strong></a>
  ·
  <a href="https://github.com/fabilau/hass_smart_offset_thermostat/issues">Get help</a>
</p>

## ✨ Why you'll love it

- 🎯 **The temperature that really matters:** comfort is based on the room, not the warm spot beside the radiator.
- 🧠 **Gets better over time:** automatic learning adapts to the way your room heats and cools.
- 🏠 **Feels at home in Home Assistant:** temperature, mode and presets are available in one familiar thermostat card.
- 🚪 **Saves energy when windows are open:** connect one or more window or door sensors.
- 🚀 **Warms up quickly when you need it:** Boost gives the room an extra push and stops automatically.
- 🎛️ **Keeps the real knob useful:** manual changes on the physical thermostat can be adopted automatically.
- 📊 **Makes comfort visible:** clear insights show temperature trends, comfort and recent activity.
- ✨ **Easy from the start:** everything is set up with friendly forms—no YAML or JSON editing.

## 🏡 Everything you need for smarter comfort

Smart Offset Thermostat is designed to quietly fit into everyday life. Set your preferred room temperature from the regular Home Assistant thermostat card and let it handle the physical thermostat for you.

Choose a preset when you leave home, pause control for summer, switch between supported heating and cooling modes, or turn everything off with a single tap. You can change the settings whenever your routine changes.

### 🪟 Fresh air without wasted energy

Connect one or more window or door sensors. When one stays open, Smart Offset Thermostat automatically reduces energy use. Normal comfort control returns when everything is closed again.

### 🚀 Boost when you need it

Start Boost from Home Assistant for a quick burst of heating or cooling. It ends automatically after your chosen time and gently returns to normal comfort control.

### 🎛️ Keep using the physical thermostat

Prefer turning a real knob sometimes? Enable manual-change synchronisation and an adjustment on the physical thermostat can also update your desired room temperature—without the two controls fighting each other.

### 📊 Understand your room at a glance

Built-in insights help you see more than a single temperature value:

- how close the room is to your chosen temperature;
- how consistently it stays inside your comfort range;
- whether the temperature is rising or falling;
- when the thermostat last made an adjustment;
- whether a window, Boost or pause is currently affecting the room.

Add these insights to your dashboards and history views to discover what feels best in your home.

## ✅ What you need

- Home Assistant
- A thermostat already connected to Home Assistant
- A separate room-temperature sensor
- Optional window or door sensors for open-window protection

It works with many brands. The available heating, cooling and Off controls depend on what your physical thermostat supports in Home Assistant.

## 🔄 Updating normally

Regular updates keep your existing settings and learned values automatically. As with every important Home Assistant update, creating a backup first is a good idea.

<a id="installation"></a>

## 📦 Installation

### HACS (recommended)

1. Open **HACS → Integrations → Custom repositories**.
2. Add `https://github.com/fabilau/hass_smart_offset_thermostat` as an **Integration** repository.
3. Install **Smart Offset Thermostat**.
4. Restart Home Assistant and add the integration from **Settings → Devices & services**.

<details>
<summary><strong>Manual installation</strong></summary>

<br>

Copy `custom_components/smart_offset_thermostat` into your Home Assistant `config/custom_components/` folder, restart Home Assistant, and add the integration from **Settings → Devices & services**.

</details>

## 🍎 HomeKit

Want thermostat control in the Apple Home app? Share Smart Offset Thermostat through Home Assistant's HomeKit Bridge. The controls shown there depend on what HomeKit and your physical thermostat support.

## ❤️ Support the project

Questions, ideas and bug reports are welcome in [GitHub Issues](https://github.com/fabilau/hass_smart_offset_thermostat/issues).

If Smart Offset Thermostat makes your home more comfortable and you would like to support its continued development, you can [leave a donation](https://revolut.me/fabilrzs). Thank you! 🙏

## 📄 License

Smart Offset Thermostat is available under the [PolyForm Noncommercial License 1.0.0](LICENSE) for non-commercial use.
