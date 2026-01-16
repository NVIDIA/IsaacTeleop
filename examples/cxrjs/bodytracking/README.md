# WebXR Body Tracking Testbed

A simple testbed application demonstrating the WebXR Body Tracking API for rendering articulated body skeletons in VR.

## Overview

This application demonstrates body tracking capabilities by:
1. Requesting a WebXR session with body-tracking features
2. Reading body joint poses each frame from the XR device
3. Rendering joints as cubes and bones as cylinders
4. Displaying a mirrored skeleton facing the user

## Supported Skeleton Formats

This testbed supports two body tracking skeleton formats:

### 1. Standard WebXR Body Tracking

The standard format as defined by the [WebXR Body Tracking Module - Level 1](https://immersive-web.github.io/body-tracking/) specification from the W3C Immersive Web Community Group.

- **Feature descriptor**: `"body-tracking"`
- **Frame attribute**: `frame.body`
- **Joint count**: 84 joints (full body including detailed hand and foot joints)
- **Access**: Iterates via `for (const [jointName, jointSpace] of frame.body)`

### 2. Pico Body Tracking (Proposed)

A simplified 24-joint skeleton format based on the OpenXR [XR_BD_body_tracking](https://registry.khronos.org/OpenXR/specs/1.1/html/xrspec.html#XR_BD_body_tracking) extension, designed for Pico devices.

- **Feature descriptor**: `"body-tracking-pico"`
- **Frame attribute**: `frame.bodyPico`
- **Joint count**: 24 joints (body skeleton without individual finger joints)
- **Access**: Iterates via `for (const [jointName, jointSpace] of frame.bodyPico)`

> ⚠️ ***THE PICO BODY TRACKING PROPOSAL IS A PRELIMINARY DRAFT FOR INTERNAL DISCUSSION ONLY. IT IS NOT READY FOR PUBLIC RELEASE OR SUBMISSION TO W3C.***

The Pico format proposal can be found in the [`w3c_proposal/`](./w3c_proposal/) directory.

## Joint Comparison

| Body Part | Standard Format | Pico Format |
|-----------|-----------------|-------------|
| Torso | hips, spine-lower/middle/upper, chest | pelvis, spine-1/2/3 |
| Head/Neck | neck, head | neck, head |
| Arms | shoulder, scapula, arm-upper/lower, wrist-twist | collar, shoulder, elbow, wrist, hand |
| Hands | 25 joints per hand (palm, wrist, all fingers) | Single hand joint |
| Legs | upper-leg, lower-leg, ankle-twist, ankle, subtalar, transverse, ball | hip, knee, ankle, foot |

## Usage

### Running the Testbed

1. Serve the files using a local web server (HTTPS required for WebXR)
2. Open in a WebXR-compatible browser
3. Click "Enter VR" to start the body tracking session

### Preview Mode

When not in VR, the application displays both skeleton formats side by side:
- **Left**: Standard WebXR body tracking skeleton
- **Right**: Pico body tracking skeleton (24 joints)

Each skeleton also has a mirrored copy rendered facing the viewer.

## Code Structure

- **`app.js`** - Main application with WebGL rendering and body tracking logic
  - `BODY_JOINTS` / `BONE_CONNECTIONS` - Standard skeleton definition
  - `BODY_JOINTS_PICO` / `BONE_CONNECTIONS_PICO` - Pico skeleton definition
  - `detectSkeletonFormat()` - Auto-detects which format is being used
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

