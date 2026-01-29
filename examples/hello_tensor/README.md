<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Hello Tensor

Demo example that demonstrates pushing and reading DLPack tensor data via the OpenXR runtime using the Generic Tensor Collection interface.

## Overview

This example contains two binaries:
- **hello_tensor_pusher** - Pushes DLPack tensor data (4x4 float32 matrix) into the OpenXR runtime
- **hello_tensor_reader** - Reads tensor data from the OpenXR runtime

Together they demonstrate the full tensor push/read workflow using the `XR_NVX1_push_tensor` and `XR_NVX1_tensor_data` extensions.

## Quick Start

### Build

```bash
cd TeleopCore

cmake -B build -DBUILD_EXAMPLES=ON
cmake --build build --parallel
cmake --install build
```

### Run

Run pusher and reader simultaneously in separate terminals:

```bash
# Terminal 1: Start pusher
./install/examples/hello_tensor/hello_tensor_pusher

# Terminal 2: Start reader
./install/examples/hello_tensor/hello_tensor_reader
```

The reader will discover the tensor collection created by the pusher and print received samples. Both exit automatically after 100 samples, or press Ctrl+C to exit early.

## Architecture

### Components

**HelloTensorPlugin** (pusher) - Main plugin class that:
- Creates an OpenXR session
- Initializes push tensor extension functions
- Creates a DLPack tensor collection
- Runs a worker thread that pushes sample data

**HelloTensorReader** (reader) - Standalone application that:
- Creates an OpenXR session
- Discovers available tensor collections by identifier
- Polls for new samples and prints received data

### Data Format

The pusher sends a 4x4 float32 matrix (16 floats, 64 bytes) with the following properties:

- **Data Type**: DLPack (float32)
- **Shape**: [4, 4]
- **Strides**: [16, 4] bytes (row-major)
- **Total Size**: 64 bytes

### Push Tensor API

The pusher uses three extension functions:

1. `xrCreatePushTensorCollectionNV` - Creates a tensor collection handle
2. `xrPushTensorCollectionDataNV` - Pushes tensor data with timestamp
3. `xrDestroyPushTensorCollectionNV` - Cleans up the collection

### Tensor Data API

The reader uses these extension functions:

1. `xrCreateTensorListNV` - Creates a tensor list for discovering collections
2. `xrGetTensorListPropertiesNV` - Gets the number of available collections
3. `xrGetTensorCollectionPropertiesNV` - Gets collection metadata (identifier, etc.)
4. `xrGetTensorPropertiesNV` - Gets individual tensor properties within a collection
5. `xrGetTensorDataNV` - Retrieves tensor data samples
6. `xrGetTensorListLatestGenerationNV` - Checks if the list has changed
7. `xrUpdateTensorListNV` - Updates the cached list
8. `xrDestroyTensorListNV` - Cleans up the tensor list

## Implementation Details

### DLPack Tensor Creation

```cpp
XrPushTensorDlpackCreateInfoNV dlpackInfo{XR_TYPE_PUSH_TENSOR_DLPACK_CREATE_INFO_NV};
dlpackInfo.data.versionMajor = 1;
dlpackInfo.data.versionMinor = 0;
dlpackInfo.data.dtype = (2 << 8) | 32;  // float32: code=2, bits=32
dlpackInfo.data.ndim = 2;
dlpackInfo.data.shape[0] = 4;
dlpackInfo.data.shape[1] = 4;
dlpackInfo.data.strides[0] = 4 * sizeof(float);
dlpackInfo.data.strides[1] = sizeof(float);
dlpackInfo.data.byte_offset = 0;

XrPushTensorCreateInfoNV tensorInfo{XR_TYPE_PUSH_TENSOR_CREATE_INFO_NV};
tensorInfo.next = &dlpackInfo;
tensorInfo.properties.dataType = XR_TENSOR_DATA_TYPE_DLPACK_NV;
tensorInfo.properties.dataTypeSize = 4 * 4 * sizeof(float);
```

### Pushing Data

```cpp
float data[16] = { /* matrix values */ };
XrPushTensorCollectionDataNV tensorData{XR_TYPE_PUSH_TENSOR_COLLECTION_DATA_NV};
tensorData.timestamp = xr_time;
tensorData.rawDeviceTimestamp = device_ns;
tensorData.buffer = reinterpret_cast<const uint8_t*>(data);
tensorData.bufferSize = sizeof(data);
xrPushTensorCollectionDataNV(pushTensorCollection, &tensorData);
```

### Reading Data

```cpp
XrTensorDataRetrievalInfoNV retrievalInfo{XR_TYPE_TENSOR_DATA_RETRIEVAL_INFO_NV};
retrievalInfo.tensorCollectionIndex = collectionIndex;
retrievalInfo.startSampleIndex = lastSampleIndex + 1;

XrTensorDataNV tensorData{XR_TYPE_TENSOR_DATA_NV};
tensorData.metadataArray = metadata.data();
tensorData.metadataCapacity = MAX_SAMPLES;
tensorData.buffer = dataBuffer.data();
tensorData.bufferCapacity = bufferSize;

xrGetTensorDataNV(tensorList, &retrievalInfo, &tensorData);
```

## DLPack Dtype Codes

| Type    | Code | Bits | DType Value |
|---------|------|------|-------------|
| Float32 | 2    | 32   | 544         |
| Float64 | 2    | 64   | 576         |
| Int32   | 0    | 32   | 32          |
| Int64   | 0    | 64   | 64          |

Formula: `(code << 8) | bits`

## Dependencies

- `oxr::oxr_core` - OpenXR session management
- `oxr::oxr_utils` - OpenXR utilities
- `OpenXR::openxr_loader` - OpenXR loader
- `Teleop::openxr_extensions` - Push tensor and tensor data extension headers
