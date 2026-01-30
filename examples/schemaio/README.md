<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Schema IO Example

Demo example that demonstrates pushing and reading serialized FlatBuffer data via the OpenXR runtime using the Generic Tensor Collection interface.

## Overview

This example contains two binaries:
- **pedal_pusher** - Serializes and pushes Generic3AxisPedalOutput FlatBuffer data into the OpenXR runtime using `SchemaPusherBase`
- **pedal_printer** - Reads and deserializes Generic3AxisPedalOutput FlatBuffer data from the OpenXR runtime using `Generic3AxisPedalTracker` and `DeviceIOSession`

Together they demonstrate the full tensor push/read workflow using the `XR_NVX1_push_tensor` and `XR_NVX1_tensor_data` extensions with serialized FlatBuffer messages.

**Note**: Both pusher and reader agree on the schema (`Generic3AxisPedalOutput` from `pedals.fbs`), so the schema does not need to be sent over the wire.

## Quick Start

### Build

```bash
cd TeleopCore

cmake -B build -DBUILD_EXAMPLES=ON
cmake --build build --parallel
cmake --install build
```

### Run

Run pusher and printer simultaneously in separate terminals:

```bash
# Terminal 1: Start pusher
./install/examples/schemaio/pedal_pusher

# Terminal 2: Start printer
./install/examples/schemaio/pedal_printer
```

The printer will discover the tensor collection created by the pusher and print received samples. Both exit automatically after 100 samples, or press Ctrl+C to exit early.

## Architecture

### Components

**SchemaPusherBase** (`pusherio` library) - Base class for pushing FlatBuffer schema data:
- Takes externally-provided OpenXR session handles
- Creates a tensor collection with the configured identifier
- Provides `push_buffer()` for subclasses to push serialized FlatBuffer data
- Subclasses implement typed `push()` methods for specific schema types

**SchemaTracker** (`deviceio` library) - Base class for reading FlatBuffer schema data:
- Integrates with the `ITracker` interface for use with `DeviceIOSession`
- Discovers tensor collections by identifier
- Provides `read_buffer()` for subclasses to read raw sample data
- Subclasses implement `update()` to deserialize and store typed data

**Generic3AxisPedalTracker** - Concrete tracker for Generic3AxisPedalOutput messages:
- Extends `SchemaTracker` with Generic3AxisPedalOutput-specific deserialization
- Provides `get_data()` to access the latest `Generic3AxisPedalOutputT`

**DeviceIOSession** - Session manager that:
- Collects required extensions from all trackers
- Creates tracker implementations with OpenXR handles
- Calls `update()`, just like how all the other trackers work
