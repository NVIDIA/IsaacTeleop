# OpenXR Tracking API - Architecture

## Design Overview

Modular architecture where independent trackers share a single OpenXR session.

```
User Application
    ↓
Creates Trackers (HandTracker, HeadTracker, etc.)
    ↓
Adds to OpenXRManager
    ↓
Manager.initialize()
    ├─> Collects extensions from each tracker
    ├─> Creates single OpenXR session
    └─> Initializes all trackers
    ↓
Loop: Manager.update()
    ├─> Updates timestamp (clock_gettime)
    └─> Updates all trackers
    ↓
Access data from each tracker
```

## Core Components

### ITracker Interface

Base interface all trackers implement:

```cpp
class ITracker {
    virtual std::vector<std::string> get_required_extensions() const = 0;
    virtual bool initialize(XrInstance, XrSession, XrSpace) = 0;
    virtual bool update(XrTime time) = 0;
    virtual bool is_initialized() const = 0;
    virtual std::string get_name() const = 0;
};
```

**Key principle:** Each tracker declares its own OpenXR extension requirements.

### OpenXRManager

Coordinates trackers and manages the OpenXR session:
- Collects extensions from all added trackers
- Creates single OpenXR session with all extensions
- Initializes each tracker with session details
- Updates all trackers in sync

### Individual Trackers

**HandTracker**
- Extensions: `XR_EXT_hand_tracking`
- Data: 26 joints × 2 hands
- Self-contained hand tracking logic

**HeadTracker**
- Extensions: None (core OpenXR)
- Data: HMD pose (position + orientation)
- Self-contained head tracking logic

## Extension Management

Extensions are automatically collected:

```
HandTracker.get_required_extensions() → ["XR_EXT_hand_tracking"]
HeadTracker.get_required_extensions() → []

Manager combines:
  - XR_MND_headless (always)
  - XR_EXTX_overlay (always)
  - XR_KHR_convert_timespec_time (always)
  - XR_EXT_hand_tracking (from HandTracker)
  
→ Session created with all extensions
```

## Headless Mode

**Extensions used:**
- `XR_MND_headless` - Headless operation
- `XR_EXTX_overlay` - Overlay session (non-primary)
- `XR_KHR_convert_timespec_time` - Timestamp without frame loop

**Key:** `XrSessionCreateInfoOverlayEXTX` struct enables session without graphics binding.

**Timestamp:** `clock_gettime(CLOCK_MONOTONIC)` → `xrConvertTimespecTimeToTimeKHR()` → valid XrTime

## Adding New Trackers

To add a new tracker type (e.g., controllers):

1. **Create tracker class:**
```cpp
class ControllerTracker : public ITracker {
    std::vector<std::string> get_required_extensions() const override {
        return {"XR_KHR_simple_controller"};
    }
    
    bool initialize(XrInstance inst, XrSession sess, XrSpace space) override {
        // Create action set, bind actions, etc.
    }
    
    bool update(XrTime time) override {
        // Query controller state
    }
    
    const ControllerData& get_controller(int index) const;
};
```

2. **Use it:**
```python
controller = oxr_tracking.ControllerTracker()
manager.add_tracker(controller)  # Extension auto-enabled!
```

**No changes to OpenXRManager or OpenXRSession needed.**

## File Organization

```
src/core/
├── include/
│   ├── oxr_tracker.hpp       # ITracker base
│   ├── oxr_manager.hpp       # Manager
│   ├── oxr_session.hpp       # Session
│   ├── oxr_handtracker.hpp   # Hand tracker
│   └── oxr_headtracker.hpp   # Head tracker
└── implementations
    ├── oxr_manager.cpp
    ├── oxr_session.cpp
    ├── oxr_handtracker.cpp
    └── oxr_headtracker.cpp
```

## Benefits

**Modularity:** Each tracker is independent and self-contained  
**Extensibility:** Add new trackers without modifying core  
**Efficiency:** Single session shared by all trackers  
**Testability:** Test each tracker independently  
**Maintainability:** Clear separation of concerns  

## Dependencies

**Required:**
- OpenXR loader (libopenxr)
- C standard library (time.h)

**NOT Required:**
- EGL, OpenGL, Vulkan, X11 (zero graphics dependencies!)

