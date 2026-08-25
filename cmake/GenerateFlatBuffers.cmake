# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# CMake function to generate C++ headers and binary schemas from FlatBuffer schema files.
#
# Each schema yields three outputs from a single flatc invocation:
#   <name>_generated.h       # C++ accessors.
#   <name>_bfbs_generated.h  # The binary schema as an embedded byte array.
#   <name>.bfbs              # The same bytes as a file, for the golden comparison in
#                            # tests/cpp/core/schema/test_schema_conform.cpp.
#
# Usage:
#   generate_flatbuffer_headers(
#     OUT_VAR                    # Output variable name for generated headers list.
#     INPUT_DIR                  # Directory containing .fbs files.
#     OUTPUT_DIR                 # Output directory for generated headers.
#     BFBS_OUT_VAR               # Output variable name for the generated .bfbs list.
#   )
#
# Example:
#   generate_flatbuffer_headers(
#     GENERATED_HEADERS
#     ${CMAKE_CURRENT_SOURCE_DIR}/schemas
#     ${CMAKE_CURRENT_BINARY_DIR}/generated
#     GENERATED_BFBS
#   )

function(generate_flatbuffer_headers OUT_VAR INPUT_DIR OUTPUT_DIR BFBS_OUT_VAR)
  # Ensure flatc is available from FetchContent.
  if(NOT TARGET flatc)
    message(FATAL_ERROR "flatc target not found. Make sure FlatBuffers is fetched via FetchContent before calling this function.")
  endif()

  # Use generator expression to get flatc executable path at build time.
  set(FLATC_EXECUTABLE $<TARGET_FILE:flatc>)

  # Find all .fbs files in input directory.
  file(GLOB FBS_FILES CONFIGURE_DEPENDS "${INPUT_DIR}/*.fbs")
  if(NOT FBS_FILES)
    message(FATAL_ERROR "No .fbs files found in ${INPUT_DIR}")
  endif()

  set(GENERATED_HEADER_LIST "")
  set(GENERATED_BFBS_LIST "")

  foreach(SCHEMA_FILE IN LISTS FBS_FILES)
    get_filename_component(SCHEMA_NAME ${SCHEMA_FILE} NAME_WE)
    set(OUT_HEADER "${OUTPUT_DIR}/${SCHEMA_NAME}_generated.h")
    set(OUT_BFBS_HEADER "${OUTPUT_DIR}/${SCHEMA_NAME}_bfbs_generated.h")
    set(OUT_BFBS "${OUTPUT_DIR}/${SCHEMA_NAME}.bfbs")

    add_custom_command(
      OUTPUT ${OUT_HEADER} ${OUT_BFBS_HEADER} ${OUT_BFBS}
      COMMAND ${CMAKE_COMMAND} -E make_directory ${OUTPUT_DIR}
      COMMAND ${FLATC_EXECUTABLE}
              --cpp
              --cpp-ptr-type std::shared_ptr
              --gen-object-api
              --gen-mutable
              --schema
              --bfbs-gen-embed
              # Mini-reflect type tables with field names. Supersedes --reflect-types, which
              # sets the same flatc option to a names-less value.
              --reflect-names
              # RecordT::GetFullyQualifiedName(), which is the name a recording's MCAP Schema
              # record carries. Deriving it from the .fbs is what keeps the writer that
              # declares it and the reader that matches it from being able to disagree.
              --gen-name-strings
              # Write the binary schema as a file too. flatc runs every enabled generator
              # over one parse, so this costs nothing beyond the write.
              -b
              -I ${INPUT_DIR}
              -o ${OUTPUT_DIR}
              ${SCHEMA_FILE}
      # These schemas `include` one another, and flatc does not report those edges to the
      # build system, so every output depends on the whole set. Depend on this file too:
      # the flatc flags live here, and generators that compare timestamps rather than
      # command lines would otherwise keep stale headers after a flag change.
      DEPENDS ${FBS_FILES} flatc ${CMAKE_CURRENT_FUNCTION_LIST_FILE}
      COMMENT "Generating FlatBuffers C++ and binary schema for ${SCHEMA_NAME}.fbs"
      VERBATIM
    )

    list(APPEND GENERATED_HEADER_LIST ${OUT_HEADER} ${OUT_BFBS_HEADER})
    list(APPEND GENERATED_BFBS_LIST ${OUT_BFBS})
  endforeach()

  set(${OUT_VAR} ${GENERATED_HEADER_LIST} PARENT_SCOPE)
  set(${BFBS_OUT_VAR} ${GENERATED_BFBS_LIST} PARENT_SCOPE)
endfunction()
