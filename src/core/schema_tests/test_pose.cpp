// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Pose FlatBuffer message.

// Include generated FlatBuffer headers.
#include <schema/pose_generated.h>
#include <schema/tensor_generated.h>
#include <schema/tensor_utils.h>

#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_approx.hpp>
#include <flatbuffers/flatbuffers.h>

TEST_CASE("PoseT native type can be serialized to FlatBuffer", "[pose][native]") {
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create PoseT using native object API.
    auto pose = std::make_unique<core::PoseT>();
    pose->position = core::make_cpu_tensor({1.0f, 2.0f, 3.0f});
    pose->orientation = core::make_cpu_tensor({1.0f, 0.0f, 0.0f, 0.0f});

    // Serialize PoseT to FlatBuffer.
    auto offset = core::CreatePose(builder, pose.get());
    builder.Finish(offset);

    // Deserialize and verify.
    auto parsed_pose = core::GetPose(builder.GetBufferPointer());
    REQUIRE(parsed_pose != nullptr);
    REQUIRE(parsed_pose->position() != nullptr);
    REQUIRE(parsed_pose->orientation() != nullptr);

    // Verify position tensor shape and values.
    CHECK(parsed_pose->position()->shape()->size() == 1);
    CHECK(parsed_pose->position()->shape()->Get(0) == 3);
    const float* pos_data = reinterpret_cast<const float*>(
        parsed_pose->position()->data()->data());
    CHECK(pos_data[0] == 1.0f);
    CHECK(pos_data[1] == 2.0f);
    CHECK(pos_data[2] == 3.0f);

    // Verify orientation tensor shape and values.
    CHECK(parsed_pose->orientation()->shape()->size() == 1);
    CHECK(parsed_pose->orientation()->shape()->Get(0) == 4);
    const float* orient_data = reinterpret_cast<const float*>(
        parsed_pose->orientation()->data()->data());
    CHECK(orient_data[0] == 1.0f);  // w
    CHECK(orient_data[1] == 0.0f);  // x
    CHECK(orient_data[2] == 0.0f);  // y
    CHECK(orient_data[3] == 0.0f);  // z
}

TEST_CASE("PoseT can store non-zero position values", "[pose][native]") {
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create PoseT with non-zero position using native object API.
    auto pose = std::make_unique<core::PoseT>();
    pose->position = core::make_cpu_tensor({1.5f, 2.5f, 3.5f});
    pose->orientation = core::make_cpu_tensor({1.0f, 0.0f, 0.0f, 0.0f});

    // Serialize and deserialize.
    auto offset = core::CreatePose(builder, pose.get());
    builder.Finish(offset);

    auto parsed_pose = core::GetPose(builder.GetBufferPointer());
    REQUIRE(parsed_pose != nullptr);
    REQUIRE(parsed_pose->position() != nullptr);

    // Verify position data values.
    const float* floats = reinterpret_cast<const float*>(
        parsed_pose->position()->data()->data());

    CHECK(floats[0] == 1.5f);
    CHECK(floats[1] == 2.5f);
    CHECK(floats[2] == 3.5f);
}

TEST_CASE("PoseT can store rotation quaternion", "[pose][native]") {
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create PoseT with 90-degree rotation around Z axis using native object API.
    auto pose = std::make_unique<core::PoseT>();
    pose->position = core::make_cpu_tensor({0.0f, 0.0f, 0.0f});
    pose->orientation = core::make_cpu_tensor({0.7071068f, 0.0f, 0.0f, 0.7071068f});

    // Serialize and deserialize.
    auto offset = core::CreatePose(builder, pose.get());
    builder.Finish(offset);

    auto parsed_pose = core::GetPose(builder.GetBufferPointer());
    REQUIRE(parsed_pose != nullptr);
    REQUIRE(parsed_pose->orientation() != nullptr);

    // Verify orientation data values.
    const float* floats = reinterpret_cast<const float*>(
        parsed_pose->orientation()->data()->data());

    CHECK(floats[0] == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(floats[1] == Catch::Approx(0.0f));
    CHECK(floats[2] == Catch::Approx(0.0f));
    CHECK(floats[3] == Catch::Approx(0.7071068f).epsilon(0.0001));
}

TEST_CASE("Pose table can be created with position and orientation", "[pose][table]") {
    flatbuffers::FlatBufferBuilder builder(1024);

    SECTION("Create pose with identity orientation at origin") {
        // Create position tensor data (x=0, y=0, z=0)
        std::vector<uint8_t> position_data(3 * sizeof(float), 0);
        std::vector<int64_t> position_shape = {3};
        std::vector<int64_t> position_strides = {sizeof(float)};

        auto position_data_vec = builder.CreateVector(position_data);
        auto position_shape_vec = builder.CreateVector(position_shape);
        auto position_strides_vec = builder.CreateVector(position_strides);

        core::DLDataType position_dtype(core::DLDataTypeCode_kDLFloat, 32, 1);
        core::DLDevice position_device(core::DLDeviceType_kDLCPU, 0);

        auto position = core::CreateTensor(
            builder,
            position_data_vec,
            position_shape_vec,
            &position_dtype,
            &position_device,
            1,  // ndim
            position_strides_vec
        );

        // Create orientation tensor data (w=1, x=0, y=0, z=0) - identity quaternion
        std::vector<uint8_t> orientation_data(4 * sizeof(float), 0);
        float* orientation_floats = reinterpret_cast<float*>(orientation_data.data());
        orientation_floats[0] = 1.0f;  // w = 1 for identity quaternion

        std::vector<int64_t> orientation_shape = {4};
        std::vector<int64_t> orientation_strides = {sizeof(float)};

        auto orientation_data_vec = builder.CreateVector(orientation_data);
        auto orientation_shape_vec = builder.CreateVector(orientation_shape);
        auto orientation_strides_vec = builder.CreateVector(orientation_strides);

        core::DLDataType orientation_dtype(core::DLDataTypeCode_kDLFloat, 32, 1);
        core::DLDevice orientation_device(core::DLDeviceType_kDLCPU, 0);

        auto orientation = core::CreateTensor(
            builder,
            orientation_data_vec,
            orientation_shape_vec,
            &orientation_dtype,
            &orientation_device,
            1,  // ndim
            orientation_strides_vec
        );

        // Create the Pose
        auto pose = core::CreatePose(builder, position, orientation);
        builder.Finish(pose);

        // Verify the pose
        auto parsed_pose = core::GetPose(builder.GetBufferPointer());

        REQUIRE(parsed_pose != nullptr);
        REQUIRE(parsed_pose->position() != nullptr);
        REQUIRE(parsed_pose->orientation() != nullptr);

        // Verify position tensor
        CHECK(parsed_pose->position()->shape()->size() == 1);
        CHECK(parsed_pose->position()->shape()->Get(0) == 3);
        CHECK(parsed_pose->position()->dtype()->code() == core::DLDataTypeCode_kDLFloat);
        CHECK(parsed_pose->position()->dtype()->bits() == 32);

        // Verify orientation tensor
        CHECK(parsed_pose->orientation()->shape()->size() == 1);
        CHECK(parsed_pose->orientation()->shape()->Get(0) == 4);
        CHECK(parsed_pose->orientation()->dtype()->code() == core::DLDataTypeCode_kDLFloat);
        CHECK(parsed_pose->orientation()->dtype()->bits() == 32);
    }
}

TEST_CASE("Pose table supports different tensor devices", "[pose][table]") {
    flatbuffers::FlatBufferBuilder builder(1024);

    SECTION("CUDA device tensors") {
        std::vector<uint8_t> position_data(3 * sizeof(float), 0);
        std::vector<int64_t> shape = {3};
        std::vector<int64_t> strides = {sizeof(float)};

        auto data_vec = builder.CreateVector(position_data);
        auto shape_vec = builder.CreateVector(shape);
        auto strides_vec = builder.CreateVector(strides);

        core::DLDataType dtype(core::DLDataTypeCode_kDLFloat, 32, 1);
        core::DLDevice cuda_device(core::DLDeviceType_kDLCUDA, 0);

        auto position = core::CreateTensor(
            builder, data_vec, shape_vec, &dtype, &cuda_device, 1, strides_vec
        );

        std::vector<uint8_t> orientation_data(4 * sizeof(float), 0);
        std::vector<int64_t> orientation_shape = {4};

        auto orientation_data_vec = builder.CreateVector(orientation_data);
        auto orientation_shape_vec = builder.CreateVector(orientation_shape);
        auto orientation_strides_vec = builder.CreateVector(strides);

        auto orientation = core::CreateTensor(
            builder, orientation_data_vec, orientation_shape_vec,
            &dtype, &cuda_device, 1, orientation_strides_vec
        );

        auto pose = core::CreatePose(builder, position, orientation);
        builder.Finish(pose);

        auto parsed_pose = core::GetPose(builder.GetBufferPointer());
        REQUIRE(parsed_pose != nullptr);
        REQUIRE(parsed_pose->position() != nullptr);

        CHECK(parsed_pose->position()->device()->device_type() == core::DLDeviceType_kDLCUDA);
        CHECK(parsed_pose->position()->device()->device_id() == 0);
    }
}

