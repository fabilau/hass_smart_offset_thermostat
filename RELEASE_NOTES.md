# v2.0.7

This update prevents unnecessary reheating after ventilation and when a room returns to its temperature tolerance band.

A room that is already warm enough stays at the minimum heating setpoint after a window closes or Boost ends. Heating resumes promptly once the room falls below the lower tolerance boundary, without a slow ramp from the setback temperature. Normal stable regulation within the tolerance band remains available.

Repeated preset, target and HVAC commands no longer discard regulation state. Editing an inactive preset also leaves the active room control unchanged.

During an automatic heating pause, a temperature entered on the physical thermostat becomes the room target directly. Normal manual adjustments continue to shift the room target by the same amount.

Heating offsets no longer increase while fresh measurements already show the room warming. Learning still adapts to persistent underheating and stable operation.

The old delayed overheating correction and its four settings have been replaced by the immediate heating pause. Previously saved settings remain compatible. Learned offsets are preserved; this update does not add another automatic reset.

