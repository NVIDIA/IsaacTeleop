# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# CMake function to generate C++ headers from FlatBuffer schema files.
#
# Usage:
#   generate_flatbuffer_headers(
#     OUT_VAR                    # Output variable name for generated headers list.
#     INPUT_DIR                  # Directory containing .fbs files.
#     OUTPUT_DIR                 # Output directory for generated headers.
#   )
#
# Example:
#   generate_flatbuffer_headers(
#     GENERATED_HEADERS
#     ${CMAKE_CURRENT_SOURCE_DIR}/schemas
#     ${CMAKE_CURRENT_BINARY_DIR}/generated
#   )

function(generate_flatbuffer_headers OUT_VAR INPUT_DIR OUTPUT_DIR)
  # Ensure flatc is available from FetchContent.
  if(NOT TARGET flatc)
    message(FATAL_ERROR "flatc target not found. Make sure FlatBuffers is fetched via FetchContent before calling this function.")
  endif()

  # Use generator expression to get flatc executable path at build time.
  set(FLATC_EXECUTABLE $<TARGET_FILE:flatc>)

  # Find all .fbs files in input directory.
  file(GLOB FBS_FILES RELATIVE ${INPUT_DIR} CONFIGURE_DEPENDS "${INPUT_DIR}/*.fbs")
  if(NOT FBS_FILES)
    message(FATAL_ERROR "No .fbs files found in ${INPUT_DIR}")
    set(${OUT_VAR} "" PARENT_SCOPE)
    return()
  endif()

  set(GENERATED_HEADER_LIST "")

  foreach(SCHEMA_FILE IN LISTS FBS_FILES)
    get_filename_component(SCHEMA_NAME ${SCHEMA_FILE} NAME_WE)
    set(OUT_HEADER "${OUTPUT_DIR}/${SCHEMA_NAME}_generated.h")
    set(OUT_BFBS_HEADER "${OUTPUT_DIR}/${SCHEMA_NAME}_bfbs_generated.h")

    add_custom_command(
      OUTPUT ${OUT_HEADER} ${OUT_BFBS_HEADER}
      COMMAND ${CMAKE_COMMAND} -E make_directory ${OUTPUT_DIR}
      COMMAND ${FLATC_EXECUTABLE}
              --cpp
              --cpp-ptr-type std::shared_ptr
              --gen-object-api
              --gen-mutable
              --schema
              --bfbs-gen-embed
              --reflect-names
              --reflect-types
              -I ${INPUT_DIR}
              -o ${OUTPUT_DIR}
              ${INPUT_DIR}/${SCHEMA_FILE}
      DEPENDS ${INPUT_DIR}/${SCHEMA_FILE} flatc
      COMMENT "Generating FlatBuffers C++ for ${SCHEMA_FILE}"
      VERBATIM
    )

    list(APPEND GENERATED_HEADER_LIST ${OUT_HEADER} ${OUT_BFBS_HEADER})
  endforeach()

  set(${OUT_VAR} ${GENERATED_HEADER_LIST} PARENT_SCOPE)
endfunction()
