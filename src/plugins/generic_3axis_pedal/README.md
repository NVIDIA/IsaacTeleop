# Generic 3-Axis Pedal Plugin

Reads a 3-axis joystick from `/dev/input/js*` and pushes `Generic3AxisPedalOutput` via OpenXR. Use with `Generic3AxisPedalTracker` or `pedal_printer` with the same `collection_id`.

## Usage

```bash
./generic_3axis_pedal_plugin [device_path] [collection_id]
```

- **device_path**: Default `/dev/input/js0`.
- **collection_id**: Default `generic_3axis_pedal`. Match this when creating `Generic3AxisPedalTracker`.

## Axis mapping

- Axis 0 → `left_pedal`, 1 → `right_pedal`, 2 → `rudder` (normalized [-1, 1]).

Linux only.
