# WebXR Body Tracking Testbed

A simple testbed application demonstrating the WebXR Body Tracking API for rendering articulated body skeletons in VR.

## Overview

This application demonstrates body tracking capabilities by:
1. Requesting a WebXR session with body-tracking feature
2. Reading body joint poses each frame from the XR device
3. **Deriving a simplified Pico skeleton** from the WebXR skeleton using joint mapping
4. Rendering both skeletons side-by-side as cubes (joints) and cylinders (bones)
5. Displaying duplicated copies of each skeleton facing away from the viewer (at 2m distance)

## Supported Skeleton Formats

This testbed supports two body tracking skeleton formats:

### 1. Standard WebXR Body Tracking

The standard format as defined by the [WebXR Body Tracking Module - Level 1](https://immersive-web.github.io/body-tracking/) specification from the W3C Immersive Web Community Group.

- **Feature descriptor**: `"body-tracking"`
- **Frame attribute**: `frame.body`
- **Joint count**: 83 joints (full body including detailed hand and foot joints)
- **Access**: Iterates via `for (const [jointName, jointSpace] of frame.body)`

### 2. Pico Body Tracking (Derived)

A simplified 24-joint skeleton format based on the OpenXR [XR_BD_body_tracking](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#XR_BD_body_tracking) extension.

- **Joint count**: 24 joints (body skeleton without individual finger joints)
- **Derivation**: Mapped from WebXR joints using `PICO_TO_WEBXR_JOINT_MAP`
- **Purpose**: Demonstrates compatibility layer for devices that use the Pico/ByteDance joint set


## Joint Mapping Strategy

The application uses a mapping table (`PICO_TO_WEBXR_JOINT_MAP`) to convert WebXR joints to Pico joints:

| Pico Joint | Maps to WebXR Joint | Notes |
|-----------|---------------------|-------|
| `pelvis` | `hips` | Root joint |
| `spine1` | `spine-lower` | Lower spine |
| `spine2` | `spine-middle` | Middle spine |
| `spine3` | `spine-upper` | Upper spine |
| `left-shoulder` | `left-arm-upper` | Upper arm position |
| `left-elbow` | `left-arm-lower` | Lower arm/elbow |
| `left-wrist` | `left-hand-wrist` | Wrist joint |
| `left-hand` | `left-hand-palm` | Hand center |
| ... | ... | (And mirrors for right side) |

This approach is based on the implementation in [`cloudxr-js/src/BodyTracking.ts`](https://gitlab.com/nvidia/omniverse/cloud-streaming-kit/cloudxr-js/-/blob/main/src/BodyTracking.ts).

## Joint Comparison

| Body Part | Standard Format | Pico Format |
|-----------|-----------------|-------------|
| Torso | hips, spine-lower/middle/upper, chest | pelvis, spine1/2/3 |
| Head/Neck | neck, head | neck, head |
| Arms | shoulder, scapula, arm-upper/lower, wrist-twist | collar, shoulder, elbow, wrist, hand |
| Hands | 25 joints per hand (palm, wrist, all fingers) | Single hand joint |
| Legs | upper-leg, lower-leg, ankle-twist, ankle, subtalar, transverse, ball | hip, knee, ankle, foot |

## Usage

### Running the Testbed

1. Serve the files using a local web server (HTTPS required for WebXR)
2. Open in a WebXR-compatible browser
3. Click "Enter VR" to start the body tracking session

The application displays both skeleton formats simultaneously for comparison.

### Preview Mode

When not in VR, the application displays both skeleton formats side by side:
- **Left**: Standard WebXR body tracking skeleton (83 joints)
- **Right**: Pico body tracking skeleton (24 joints, derived from WebXR)

Each skeleton also has a duplicate copy rendered 2 meters away, facing away from the viewer (so left/right are preserved, not mirrored).

## Code Structure

- **`app.js`** - Main application with WebGL rendering and body tracking logic
  - `BODY_JOINTS` / `BONE_CONNECTIONS` - Standard WebXR skeleton definition
  - `BODY_JOINTS_PICO` / `BONE_CONNECTIONS_PICO` - Pico skeleton definition
  - `PICO_TO_WEBXR_JOINT_MAP` - Mapping table for conversion
  - `convertWebXRToPico()` - Converts WebXR skeleton to Pico format
  - `drawSkeleton()` - Renders a skeleton with appropriate bone connections

## Color Coding

Joints and bones are color-coded by body part:
- 🟤 **Head/Neck**: Skin tone
- 🔵 **Torso/Spine**: Blue
- 🔴 **Left Arm/Hand**: Red
- 🟢 **Right Arm/Hand**: Green
- 🟠 **Left Leg**: Orange
- 🟣 **Right Leg**: Purple

## References

- [WebXR Body Tracking Module - Level 1](https://immersive-web.github.io/body-tracking/) - W3C Draft Community Group Report
- [WebXR Device API](https://immersive-web.github.io/webxr/) - Core WebXR specification
- [OpenXR XR_BD_body_tracking](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#XR_BD_body_tracking) - OpenXR extension for ByteDance/Pico body tracking
- [cloudxr-js BodyTracking.ts](https://gitlab.com/nvidia/omniverse/cloud-streaming-kit/cloudxr-js/-/blob/main/src/BodyTracking.ts) - Reference implementation
