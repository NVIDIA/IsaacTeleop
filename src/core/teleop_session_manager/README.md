# TeleopSessionManager - High-Level Teleop Session API

TeleopSessionManager provides a declarative, configuration-based API for setting up complete teleop pipelines. It eliminates boilerplate code and makes examples more readable by focusing on **what** you want to do rather than **how** to set it up.

## Overview

The main component is `TeleopSession`, which manages the complete lifecycle of a teleop session:

1. ✅ Creates and configures trackers (head, hands, controllers)
2. ✅ Sets up OpenXR session with required extensions
3. ✅ Initializes and manages plugins
4. ✅ Runs retargeting pipeline with automatic updates
5. ✅ Handles cleanup via RAII

## Quick Start

Here's a minimal example:

```python
from isaacteleop.teleop_session_manager import (
    TeleopSession,
    TeleopSessionConfig,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
from isaacteleop.retargeting_engine.examples import GripperRetargeter

# Create source and build pipeline
controllers = ControllersSource(name="controllers")
gripper = GripperRetargeter(name="gripper")
pipeline = gripper.connect({
    "controller_left": controllers.output("controller_left"),
    "controller_right": controllers.output("controller_right")
})

# Configure session
config = TeleopSessionConfig(
    app_name="MyTeleopApp",
    pipeline=pipeline,
    trackers=[], # Auto-discovered
)

# Run!
with TeleopSession(config) as session:
    while True:
        result = session.step()
        # Access outputs
        left = result["gripper_left"][0]
        right = result["gripper_right"][0]
```

## Configuration Classes

### TeleopSessionConfig

The main configuration object:

```python
@dataclass
class TeleopSessionConfig:
    app_name: str                           # OpenXR application name
    pipeline: Any                           # Connected retargeting pipeline
    trackers: List[Any] = []                # Tracker instances (optional)
    plugins: List[PluginConfig] = []        # Plugin configurations (optional)
    verbose: bool = True                    # Print progress info
```

### PluginConfig

Configure plugins:

```python
PluginConfig(
    plugin_name="controller_synthetic_hands",
    plugin_root_id="synthetic_hands",
    search_paths=[Path("/path/to/plugins")],
    enabled=True
)
```

## API Reference

### TeleopSession

#### Methods

- `step() -> Dict[str, TensorGroup]`: Execute one step (updates trackers, executes pipeline)
- `get_elapsed_time() -> float`: Get elapsed time since session started

#### Properties

- `frame_count: int`: Current frame number
- `start_time: float`: Session start time
- `config: TeleopSessionConfig`: The configuration object

## Examples

### Complete Examples

1. **Simplified Gripper Example**: `examples/retargeting/python/gripper_retargeting_simple.py`
   - Shows the minimal configuration approach
   - Demonstrates auto-creation of input sources

### Before vs After

**Before (verbose, manual setup):**
```python
# Create trackers
controller_tracker = deviceio.ControllerTracker()

# Get extensions
required_extensions = deviceio.DeviceIOSession.get_required_extensions([controller_tracker])

# Create OpenXR session
oxr_session = oxr.OpenXRSession.create("MyApp", required_extensions)
oxr_session.__enter__()

# Create DeviceIO session
handles = oxr_session.get_handles()
deviceio_session = deviceio.DeviceIOSession.run([controller_tracker], handles)
deviceio_session.__enter__()

# Setup plugins
plugin_manager = pm.PluginManager([...])
plugin_context = plugin_manager.start(...)

# Setup pipeline
controllers = ControllersSource(name="controllers")
gripper = GripperRetargeter(name="gripper")
pipeline = gripper.connect({...})

# Main loop
while True:
    deviceio_session.update()
    # Manual data injection needed for new sources
    controller_data = controller_tracker.get_controller_data(deviceio_session)
    inputs = {
        "controllers": {
            "deviceio_controller_left": [controller_data.left_controller],
            "deviceio_controller_right": [controller_data.right_controller]
        }
    }
    result = pipeline(inputs)
    # ... error handling, cleanup ...
```

**After (declarative):**
```python
# Configuration
config = TeleopSessionConfig(
    app_name="MyApp",
    trackers=[controller_tracker],
    pipeline=pipeline,
)

# Run!
with TeleopSession(config) as session:
    while True:
        result = session.step()  # Everything handled automatically!
```

## Benefits

1. **Reduced Boilerplate**: ~70% reduction in code length
2. **Declarative**: Focus on configuration, not implementation
3. **Auto-Initialization**: Plugins and sessions all managed automatically
4. **Self-Documenting**: Configuration structure makes intent clear
5. **Error Handling**: Automatic error handling and cleanup
6. **Plugin Management**: Built-in plugin lifecycle management
7. **Maintainable**: Changes to setup logic happen in one place

## Advanced Features

### Custom Update Logic

```python
with TeleopSession(config) as session:
    while True:
        result = session.step()

        # Custom logic
        left_gripper = result["gripper_left"][0]
        if left_gripper > 0.5:
            print("Left gripper activated!")

        # Frame timing
        if session.frame_count % 60 == 0:
            print(f"Running at {60 / session.get_elapsed_time():.1f} FPS")
```

## License

SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0

