<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# External Skeleton Plugin

Pushes a 14-joint upper-body skeleton (`ExternalSkeletonPose`) onto the OpenXR
runtime via `SchemaPusher`, so any consumer using
`core::ExternalSkeletonTracker` (with the matching `collection_id`) sees the
data with no further glue.

This is the vendor-neutral entry point for **external motion-capture suits**
used for arm-gesture teleop — Rokoko Smartsuit Pro II, Xsens / Movella MVN
(Awinda / Link), Sony mocopi, Noitom Perception Neuron, OptiTrack NatNet,
Vicon DataStream, etc.

## Status

This is a **draft scaffold**. It compiles and runs end-to-end with a synthetic
data source so you can verify the pipeline before wiring real hardware.
Vendor-specific I/O is not implemented — see *Adding a real device* below.

## Usage

```bash
./external_skeleton_plugin [source_kind] [collection_id]
```

- **source_kind**: Currently only `synthetic` is wired up. Drives a slow arm
  wave for visual verification.
- **collection_id**: Default `external_skeleton`. Match this when constructing
  `core::ExternalSkeletonTracker(collection_id)` in the consumer process.

Quick smoke test (in two terminals):

```bash
# Terminal 1 — push synthetic data
./install/plugins/external_skeleton/external_skeleton_plugin synthetic external_skeleton

# Terminal 2 — read it back via DeviceIOSession (use any consumer that
# constructs ExternalSkeletonTracker("external_skeleton")).
```

## Joint layout

`core::ExternalSkeletonJoint` (14 joints, see
`src/core/schema/fbs/external_skeleton.fbs`):

```
ROOT, HIPS, SPINE, CHEST, NECK, HEAD,
LEFT_SHOULDER, LEFT_UPPER_ARM, LEFT_LOWER_ARM, LEFT_HAND,
RIGHT_SHOULDER, RIGHT_UPPER_ARM, RIGHT_LOWER_ARM, RIGHT_HAND
```

Vendor backends should map their native joint hierarchy onto this layout, or
set `BodyJointPose.is_valid = false` on joints they do not provide.

## Adding a real device

The pusher loop in `ExternalSkeletonPlugin::update()` is intentionally
agnostic to where samples come from. Adding a new device means writing one new
class that implements `IExternalSkeletonSource` (in
`external_skeleton_source.hpp`) and registering it in `make_source()` in
`main.cpp`. No other file changes are required.

A sketch for each canonical option:

| Device | Recommended source class | Underlying transport |
|---|---|---|
| **Rokoko Smartsuit Pro II** | `RokokoSkeletonSource` | UDP listener parsing the **Custom Streaming v3 JSON** format (port 14043 by default) |
| **Xsens / Movella MVN** | `MvnSkeletonSource` | Native MVN SDK (C++) callback, or the documented MVN UDP datagram format |
| **Sony mocopi** | `MocopiSkeletonSource` | UDP listener mirroring the Receiver Plugin SDK packet format |
| **Noitom Perception Neuron** | `NoitomSkeletonSource` | `MocapApi` (C/C++) callback or BVH UDP stream from Axis Studio |
| **OptiTrack Motive** | `NatNetSkeletonSource` | `NatNetClient` subscription, mapping `sSkeletonData` joints onto the schema |

For each, the body of `poll()` should:

1. Drain whatever new device data is queued (non-blocking).
2. Map the device's joints onto `ExternalSkeletonJoint` and write into
   `out.joints->mutable_joints()->Mutate(i, BodyJointPose(pose, is_valid))`.
3. Set `out.all_joint_poses_tracked` and `out.source_id`.
4. If the device exposes its own clock, return its timestamp via
   `raw_device_clock_ns`; otherwise leave it at `0` and the plugin will
   substitute the local monotonic clock.

## Out of scope for this draft

- **MCAP replay** — to enable replay, follow the same pattern as
  `replay_full_body_tracker_pico_impl.{hpp,cpp}` and add an entry to
  `replay_deviceio_factory.cpp`.
- **Python bindings** — to expose `ExternalSkeletonTracker` to Python, mirror
  the `FullBodyTrackerPico` block in
  `src/core/deviceio_trackers/python/tracker_bindings.cpp` and add schema
  bindings in `src/core/schema/python/`.
- **Retargeter wiring** — define a retargeting source that reads
  `ExternalSkeletonPoseTrackedT` and produces robot-arm joint targets.
