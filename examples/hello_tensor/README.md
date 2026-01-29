<!--
SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Hello Tensor

Demo example that demonstrates pushing and reading DLPack tensor data via the OpenXR runtime using the TensorIO library.

## Overview

This example contains two binaries:
- **hello_tensor_pusher** - Pushes DLPack tensor data (4x4 float32 matrix) into the OpenXR runtime
- **hello_tensor_reader** - Reads tensor data from the OpenXR runtime

Together they demonstrate the full tensor push/read workflow using the `TensorPusher` and `TensorReader` classes from the `tensorio` library.

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

### TensorIO Library

This example uses the reusable `tensorio` library located at `src/core/tensorio/`:

- **TensorPusher** - Creates a tensor collection and pushes data samples
- **TensorReader** - Discovers tensor collections and reads data samples
- **TensorCollectionConfig** - Configuration for creating tensor collections
- **TensorSpec** - Specification for individual tensors within a collection
- **DlpackInfo** - DLPack metadata (shape, strides, dtype)

### Usage Example

**Pusher:**
```cpp
#include <tensorio/tensor_pusher.hpp>
#include <tensorio/tensor_types.hpp>

// Configure a 4x4 float32 tensor
TensorCollectionConfig config;
config.identifier = "my_tensors";
config.localized_name = "My Tensor Demo";

TensorSpec spec;
spec.identifier = "matrix";
spec.data_type = XR_TENSOR_DATA_TYPE_DLPACK_NV;
spec.data_type_size = 16 * sizeof(float);

DlpackInfo dlpack;
dlpack.dtype = DlpackInfo::dtype_float32();
dlpack.ndim = 2;
dlpack.shape[0] = 4;
dlpack.shape[1] = 4;
spec.dlpack_info = dlpack;

config.tensors.push_back(spec);
config.total_sample_size = 16 * sizeof(float);

auto pusher = TensorPusher::create(session->get_handles(), config);

// Push data
float data[16] = { /* values */ };
pusher->push(data);
```

**Reader:**
```cpp
#include <tensorio/tensor_reader.hpp>
#include <tensorio/tensor_types.hpp>

auto reader = TensorReader::create(session->get_handles());

// Wait for collection
while (reader->find_collection("my_tensors") < 0) {
    reader->update_list_if_needed();
    std::this_thread::sleep_for(100ms);
}

int index = reader->find_collection("my_tensors");
auto samples = reader->read_samples(index, 0);

for (const auto& sample : samples) {
    const float* data = reinterpret_cast<const float*>(sample.data.data());
    // Process data...
}
```

## Data Format

The pusher sends a 4x4 float32 matrix (16 floats, 64 bytes) with the following properties:

- **Data Type**: DLPack (float32)
- **Shape**: [4, 4]
- **Strides**: [16, 4] bytes (row-major)
- **Total Size**: 64 bytes

## DLPack Dtype Codes

| Type    | Code | Bits | DType Value |
|---------|------|------|-------------|
| Float32 | 2    | 32   | 544         |
| Float64 | 2    | 64   | 576         |
| Int32   | 0    | 32   | 32          |
| Int64   | 0    | 64   | 64          |

Formula: `(code << 8) | bits`

Helper methods in `DlpackInfo`:
- `DlpackInfo::dtype_float32()` returns 544
- `DlpackInfo::dtype_float64()` returns 576
- `DlpackInfo::dtype_int32()` returns 32
- `DlpackInfo::dtype_int64()` returns 64

## Dependencies

- `oxr::oxr_core` - OpenXR session management
- `tensorio::tensorio_core` - TensorIO library for pushing and reading tensors
- `OpenXR::openxr_loader` - OpenXR loader
