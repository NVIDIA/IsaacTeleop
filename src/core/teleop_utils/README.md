# TeleopUtils - High-Level Teleop Session API

TeleopUtils provides a declarative, configuration-based API for setting up complete teleop pipelines. It eliminates boilerplate code and makes examples more readable by focusing on **what** you want to do rather than **how** to set it up.

## Overview

The main component is `TeleopSession`, which manages the complete lifecycle of a teleop session:

1. ✅ Creates and configures trackers (head, hands, controllers)
2. ✅ Sets up OpenXR session with required extensions
3. ✅ Initializes and manages plugins
4. ✅ Builds XRIO session
5. ✅ Configures retargeting engine and compute graph
6. ✅ Runs main loop with automatic updates
7. ✅ Handles cleanup via RAII

## Quick Start

Here's a minimal example:

```python
from teleopcore.teleop_utils import (
    TeleopSession,
    TeleopSessionConfig,
    TrackerConfig,
    TrackerType,
    RetargetingConfig,
    InputBinding,
)
from teleopcore.retargeting_engine.retargeters import GripperRetargeter

# Configure trackers
trackers = [
    TrackerConfig(TrackerType.HEAD),
    TrackerConfig(TrackerType.HAND),
    TrackerConfig(TrackerType.CONTROLLER),
]

# Configure retargeters
# Input nodes will be auto-created from trackers!
retargeters = [
    RetargetingConfig(
        retargeter=GripperRetargeter(name="gripper"),
        name="gripper",
        input_bindings=[
            InputBinding("hands", 0),       # left hand (auto-created)
            InputBinding("hands", 1),       # right hand (auto-created)
            InputBinding("controllers", 0), # left controller (auto-created)
            InputBinding("controllers", 1), # right controller (auto-created)
        ]
    )
]

# Create session config
config = TeleopSessionConfig(
    app_name="MyTeleopApp",
    trackers=trackers,
    # inputs={} - Leave empty to auto-create from trackers!
    retargeters=retargeters,
    loop_duration=10.0,  # 10 seconds
)

# Run!
session = TeleopSession(config)
session.run(callback=my_callback)
```

## Configuration Classes

### TeleopSessionConfig

The main configuration object:

```python
@dataclass
class TeleopSessionConfig:
    app_name: str                           # OpenXR application name
    trackers: List[TrackerConfig]           # Which trackers to use
    plugins: List[PluginConfig]             # Which plugins to load
    inputs: Dict[str, Any]                  # Input nodes (name -> instance)
    retargeters: List[RetargetingConfig]    # Retargeter configurations
    loop_duration: Optional[float] = None   # How long to run (None = infinite)
    update_rate: float = 60.0               # Target FPS
    print_interval: float = 0.5             # Status print interval
    verbose: bool = True                    # Print progress info
```

### TrackerConfig

Configure which trackers to use:

```python
TrackerConfig(
    tracker_type=TrackerType.HAND,  # HEAD, HAND, or CONTROLLER
    enabled=True
)
```

### PluginConfig

Configure plugins with auto-stop support:

```python
PluginConfig(
    plugin_name="controller_synthetic_hands",
    plugin_root_id="synthetic_hands",
    search_paths=[Path("/path/to/plugins")],
    auto_stop_time=10.0,  # Optional: stop plugin after 10s
    enabled=True
)
```

### RetargetingConfig

Configure the retargeting graph:

```python
RetargetingConfig(
    retargeter=GripperRetargeter(name="gripper", ...),
    name="gripper",
    input_bindings=[
        InputBinding("hands", 0),       # hands input, output 0
        InputBinding("controllers", 1), # controllers input, output 1
    ]
)
```

## Callbacks

Provide a callback function to process outputs each frame:

```python
def my_callback(session: TeleopSession):
    # Access retargeter outputs
    outputs = session.get_retargeter_outputs("gripper")
    left_gripper = outputs[0].get_by_index(0)
    right_gripper = outputs[1].get_by_index(0)
    
    # Access tracker data
    hand_tracker = session.get_tracker(TrackerType.HAND)
    left_hand = hand_tracker.get_left_hand()
    
    # Get elapsed time and frame count
    elapsed = session.get_elapsed_time()
    frame = session.frame_count
    
    print(f"[{elapsed:.1f}s] Frame {frame}: L={left_gripper:.2f}, R={right_gripper:.2f}")
```

## API Reference

### TeleopSession

#### Methods

- `run(callback=None) -> int`: Run the complete session lifecycle
- `get_tracker(tracker_type: TrackerType) -> Any`: Get a tracker instance
- `get_retargeter_outputs(name: str) -> TensorCollection`: Get retargeter outputs
- `get_elapsed_time() -> float`: Get elapsed time since loop started

#### Properties

- `frame_count: int`: Current frame number
- `start_time: float`: Loop start time
- `last_print_time: float`: Last status print time
- `config: TeleopSessionConfig`: The configuration object

## Examples

### Complete Examples

1. **Simplified Gripper Example**: `examples/oxr/python/gripper_retargeting_example_simple.py`
   - Shows the minimal configuration approach (~145 lines vs 338 lines!)
   - Demonstrates auto-creation of input nodes from trackers
   - Compare to the verbose `gripper_retargeting_example.py`

### Before vs After

**Before (verbose, ~338 lines):**
```python
# Create trackers
head_tracker = xrio.HeadTracker()
hand_tracker = xrio.HandTracker()
controller_tracker = xrio.ControllerTracker()

# Build XRIO session
builder = xrio.XrioSessionBuilder()
builder.add_tracker(head_tracker)
# ... many more lines ...

# Create OpenXR session
oxr_session = oxr.OpenXRSession.create(...)
# ... error handling ...

# Initialize plugin
plugin_manager = pm.PluginManager([...])
# ... discovery, validation ...
plugin_context = plugin_manager.start(...)

# Setup retargeting
hands_input = HandsInput(...)
executor = RetargeterExecutor()
executor.bind(...)
executor.compile()

# Main loop
while True:
    xrio_session.update()
    executor.execute()
    # ... output handling ...
    # ... plugin management ...
    # ... error handling ...
```

**After (declarative, ~145 lines with comments and UI):**
```python
# Configuration
config = TeleopSessionConfig(
    app_name="MyApp",
    trackers=[TrackerConfig(TrackerType.HAND), TrackerConfig(TrackerType.CONTROLLER)],
    plugins=[PluginConfig(...)],
    # inputs auto-created from trackers!
    retargeters=[
        RetargetingConfig(
            retargeter=GripperRetargeter(...),
            name="gripper",
            input_bindings=[
                InputBinding("hands", 0),       # auto-created
                InputBinding("controllers", 0), # auto-created
            ]
        )
    ],
    loop_duration=20.0,
)

# Run!
def callback(session):
    outputs = session.get_retargeter_outputs("gripper")
    # ... use outputs ...

session = TeleopSession(config)
session.run(callback=callback)
```

## Benefits

1. **Reduced Boilerplate**: ~57% reduction in code length (338→145 lines)
2. **Declarative**: Focus on configuration, not implementation
3. **Auto-Creation**: Input nodes automatically created from trackers
4. **Self-Documenting**: Configuration structure makes intent clear
5. **Error Handling**: Automatic error handling and cleanup
6. **Plugin Management**: Built-in plugin lifecycle management
7. **Flexible**: Callback-based output handling
8. **Maintainable**: Changes to setup logic happen in one place

## Advanced Features

### Auto-Creation of Input Nodes

By default, if you leave `inputs={}` empty in the config, TeleopSession will automatically create standard input nodes from your configured trackers:

- `TrackerType.HAND` → `HandsInput` named "hands"
- `TrackerType.CONTROLLER` → `ControllersInput` named "controllers"  
- `TrackerType.HEAD` → `HeadInput` named "head"

This eliminates the need to manually create input nodes in most cases!

```python
# Auto-creation (recommended)
config = TeleopSessionConfig(
    trackers=[TrackerConfig(TrackerType.HAND)],
    # inputs auto-created!
    retargeters=[
        RetargetingConfig(
            retargeter=...,
            input_bindings=[InputBinding("hands", 0)]  # "hands" auto-created
        )
    ]
)

# Manual creation (for custom input nodes)
from teleopcore.retargeting_engine.xrio import HandsInput
import teleopcore.xrio as xrio

hand_tracker = xrio.HandTracker()
config = TeleopSessionConfig(
    trackers=[TrackerConfig(TrackerType.HAND)],
    inputs={"custom_hands": HandsInput(hand_tracker, name="custom_hands")},
    retargeters=[...]
)
```

### Multiple Retargeters

```python
retargeters = [
    RetargetingConfig(
        retargeter=GripperRetargeter(name="gripper"),
        name="gripper",
        input_bindings=[...]
    ),
    RetargetingConfig(
        retargeter=HandPoseRetargeter(name="hand_pose"),
        name="hand_pose",
        input_bindings=[...]
    ),
]
```

### Plugin Auto-Stop

Useful for testing fallback behaviors:

```python
PluginConfig(
    plugin_name="synthetic_hands",
    plugin_root_id="syn_hands",
    search_paths=[...],
    auto_stop_time=10.0,  # Stop after 10 seconds
)
```

### Conditional Plugins

```python
plugins = []
if use_synthetic_hands:
    plugins.append(PluginConfig(...))
```

### Custom Update Rates

```python
config = TeleopSessionConfig(
    ...,
    update_rate=90.0,  # 90 FPS for high-performance systems
)
```

## License

SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0

