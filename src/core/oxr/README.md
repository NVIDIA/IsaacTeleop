# OpenXR Tracking API

Modular OpenXR tracking system for TeleopCore with hand and head tracking in true headless mode.

## Location

This module is part of TeleopCore at: `src/core/oxr/`

## Quick Start

```bash
# From TeleopCore root
cmake -B build
cmake --build build
cmake --install build

# Run examples
cd install/examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
```

## Python API

### Basic Usage

```python
import sys
sys.path.insert(0, 'build/python')
import oxr_tracking

# Create trackers
hand_tracker = oxr_tracking.HandTracker()
head_tracker = oxr_tracking.HeadTracker()

# Create manager and add trackers
manager = oxr_tracking.OpenXRManager()
manager.add_tracker(hand_tracker)
manager.add_tracker(head_tracker)

# Initialize
manager.initialize("MyApp")

# Main loop
while True:
    manager.update()
    
    # Access hand data
    left = hand_tracker.get_left_hand()
    right = hand_tracker.get_right_hand()
    
    # Access head data
    head = head_tracker.get_head()
    
    if left.is_active:
        wrist = left.get_joint(oxr_tracking.JOINT_WRIST)
        print(f"Wrist: {wrist.position}")
    
    if head.is_valid:
        print(f"Head: {head.position}")
```

### Query Required Extensions

Useful when creating external OpenXR sessions:

```python
mgr = oxr_tracking.OpenXRManager()
mgr.add_tracker(hand_tracker)
mgr.add_tracker(head_tracker)

# Query extensions BEFORE initialize
extensions = mgr.get_required_extensions()
# Returns: ['XR_MND_headless', 'XR_EXTX_overlay', 
#           'XR_KHR_convert_timespec_time', 'XR_EXT_hand_tracking']

# Use these extensions to create your own OpenXR instance
# Then pass to manager.initialize(app_name, inst, sess, space)
```

### Session Sharing (Advanced)

Share one OpenXR session across multiple managers (C++ recommended):

```cpp
// Manager 1 owns the session
manager1.initialize("Owner");

// Get handles
XrInstance inst = manager1.get_instance();
XrSession sess = manager1.get_session();
XrSpace space = manager1.get_space();

// Manager 2 reuses session
manager2.initialize("Shared", inst, sess, space);

// Both work together
manager1.update();  // Owner polls events
manager2.update();  // Just updates trackers

// Cleanup: external first, owner last
manager2.shutdown();
manager1.shutdown();
```

See `tests/test_session_sharing.py` and `examples/session_sharing_example.cpp` for complete examples.

## API Reference

### OpenXRManager

Main coordinator for trackers and session.

```python
manager = OpenXRManager()
manager.add_tracker(tracker)                    # Add tracker before init
manager.get_required_extensions() -> List[str]  # Query extensions
manager.initialize(app_name, inst=None, sess=None, space=None) -> bool
manager.update() -> bool                        # Update all trackers
manager.get_instance() -> int                   # Get instance handle
manager.get_session() -> int                    # Get session handle
manager.get_space() -> int                      # Get space handle
manager.shutdown()
manager.is_initialized() -> bool
```

### HandTracker

Tracks both hands with 26 joints each.

```python
tracker = HandTracker()

# After manager.update()
left = tracker.get_left_hand() -> HandData
right = tracker.get_right_hand() -> HandData

HandTracker.get_joint_name(index: int) -> str
```

**HandData:**
```python
hand.is_active: bool
hand.timestamp: int
hand.get_joint(index: int) -> JointPose
hand.num_joints: int  # Always 26
```

**JointPose:**
```python
joint.position: np.ndarray[3]      # [x, y, z] meters
joint.orientation: np.ndarray[4]   # [x, y, z, w] quaternion
joint.radius: float
joint.is_valid: bool
```

**Joint Constants:**
```python
JOINT_WRIST = 1
JOINT_THUMB_TIP = 5
JOINT_INDEX_TIP = 10
```

### HeadTracker

Tracks HMD pose.

```python
tracker = HeadTracker()

# After manager.update()
head = tracker.get_head() -> HeadPose
```

**HeadPose:**
```python
head.position: np.ndarray[3]      # [x, y, z] meters
head.orientation: np.ndarray[4]   # [x, y, z, w] quaternion
head.is_valid: bool
head.timestamp: int
```

## Building

Build from TeleopCore root:

```bash
# From TeleopCore root
cmake -B build
cmake --build build
cmake --install build
```

This builds (with sensible defaults):
- C++ static library: `build/src/core/oxr/cpp/liboxr_tracking_core.a`
- Python wheel: `build/wheels/oxr_tracking-1.0.0-*.whl`
- C++ examples: `build/examples/oxr/cpp/`
- Install location: `install/`

## Running Examples

All examples are in `examples/oxr/`. See `examples/oxr/README.md` for details.

```bash
# Python examples (from install directory)
cd install/examples/oxr/python
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
uv run test_modular.py
uv run test_extensions.py
uv run test_session_sharing.py

# C++ example (from build directory)
export XR_RUNTIME_JSON=/path/to/cloudxr/openxr_cloudxr-dev.json
./build/examples/oxr/cpp/oxr_session_sharing
```

## TeleopCore Integration

From TeleopCore root directory:

```python
import sys
import os

# Add OpenXR tracking module to path
sys.path.insert(0, 'src/core/oxr/build/python')
import oxr_tracking

class VRInput:
    def __init__(self):
        self.hand = oxr_tracking.HandTracker()
        self.head = oxr_tracking.HeadTracker()
        
        self.mgr = oxr_tracking.OpenXRManager()
        self.mgr.add_tracker(self.hand)
        self.mgr.add_tracker(self.head)
        self.mgr.initialize("TeleopCore")
    
    def update(self):
        self.mgr.update()
        return {
            'left_hand': self.hand.get_left_hand(),
            'right_hand': self.hand.get_right_hand(),
            'head': self.head.get_head()
        }

# Usage
vr = VRInput()
while teleop_running:
    data = vr.update()
    # Use data for robot control
```

## Extensibility

See `ARCHITECTURE.md` for details on adding new tracker types.

## Requirements

- CMake 3.20+
- C++17 compiler
- OpenXR loader
- Python 3.11+
- NumPy

## Documentation

- `README.md` - This file (API usage)
- `ARCHITECTURE.md` - Design and extensibility
