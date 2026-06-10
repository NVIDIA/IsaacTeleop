# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# DepthAI vcpkg manifest (OAK camera plugin)
# ==============================================================================
# Download DepthAI's vcpkg.json for the pinned tag and use it as our manifest.
# Must run BEFORE project() so vcpkg picks up the manifest when the toolchain loads.
#
# - libusb: from DepthAI's "usb" feature (enabled below); static, baked into the binary.
# - libarchive xz (DO NOT REMOVE): DepthAI's manifest pins libarchive with
#   default-features:false because it expects its own overlay port to force-add
#   liblzma. We don't use that overlay, so stock libarchive loses xz/lzma. Since
#   the device firmware is *.tar.xz decompressed on a background thread
#   (src/utility/Resources.cpp), no-xz makes the boot HANG after BoardConfig.
#   So we re-enable the compression codecs below (crypto/libxml2 left off to
#   avoid pulling openssl/libxml2 back in).

# Single source of truth for the DepthAI version, also consumed by the
# FetchContent pull in src/plugins/oak/CMakeLists.txt. DEPTHAI_VERSION is for
# human-readable messages only; the build pins the immutable commit below.
set(DEPTHAI_VERSION "3.7.1" CACHE STRING "DepthAI (depthai-core) version (display only)")

# Supply-chain pinning: pin the exact commit (not the mutable tag) that both the
# manifest download and the FetchContent source clone resolve to, and verify the
# downloaded manifest against its known SHA256. To bump DepthAI, update all three
# of DEPTHAI_VERSION / DEPTHAI_COMMIT / DEPTHAI_VCPKG_MANIFEST_SHA256 together:
#   git ls-remote https://github.com/luxonis/depthai-core.git refs/tags/v<VER>^{}
#   curl -sL https://raw.githubusercontent.com/luxonis/depthai-core/<COMMIT>/vcpkg.json | sha256sum
set(DEPTHAI_COMMIT "8d32a1f05deb39c26823d596eb635d2599215b72"
    CACHE STRING "DepthAI (depthai-core) pinned commit SHA")
# SHA256 of the unmodified upstream vcpkg.json at DEPTHAI_COMMIT (checked before
# this module patches in libarchive's lzma feature).
set(DEPTHAI_VCPKG_MANIFEST_SHA256 "719cd72de8b5a819af24b22f5e89d3f7615dc68844615b8d76788cb8ca461954")

# Bump when the patching below changes, to regenerate a cached manifest.
set(_ISAAC_DEPTHAI_MANIFEST_REVISION "2")

function(isaac_teleop_setup_depthai_vcpkg_manifest)
    set(_manifest_dir "${CMAKE_BINARY_DIR}/vcpkg-manifest")
    set(_manifest_file "${_manifest_dir}/vcpkg.json")
    set(_stamp_file "${_manifest_dir}/.depthai-version")
    set(_url "https://raw.githubusercontent.com/luxonis/depthai-core/${DEPTHAI_COMMIT}/vcpkg.json")
    set(_stamp_value "${DEPTHAI_COMMIT}+rev${_ISAAC_DEPTHAI_MANIFEST_REVISION}")

    # Re-download only when missing or the version/revision changed.
    set(_need_download TRUE)
    if(EXISTS "${_manifest_file}" AND EXISTS "${_stamp_file}")
        file(READ "${_stamp_file}" _cached_version)
        string(STRIP "${_cached_version}" _cached_version)
        if(_cached_version STREQUAL "${_stamp_value}")
            set(_need_download FALSE)
        endif()
    endif()

    if(_need_download)
        file(MAKE_DIRECTORY "${_manifest_dir}")
        message(STATUS "Downloading DepthAI vcpkg manifest (v${DEPTHAI_VERSION} @ ${DEPTHAI_COMMIT}): ${_url}")
        file(DOWNLOAD "${_url}" "${_manifest_file}"
            EXPECTED_HASH "SHA256=${DEPTHAI_VCPKG_MANIFEST_SHA256}"
            STATUS _dl_status
            TLS_VERIFY ON)
        list(GET _dl_status 0 _dl_code)
        if(NOT _dl_code EQUAL 0)
            list(GET _dl_status 1 _dl_msg)
            file(REMOVE "${_manifest_file}")
            message(FATAL_ERROR
                "Failed to download/verify DepthAI vcpkg manifest from ${_url}: ${_dl_msg}\n"
                "A hash mismatch means the upstream vcpkg.json changed or the download was "
                "tampered with; if DepthAI was intentionally bumped, update DEPTHAI_COMMIT and "
                "DEPTHAI_VCPKG_MANIFEST_SHA256 in cmake/DepthAIVcpkgManifest.cmake.\n"
                "Configuring the OAK camera plugin needs network access to GitHub. "
                "Either restore connectivity, or disable the plugin with "
                "-DBUILD_PLUGIN_OAK_CAMERA=OFF.")
        endif()

        file(READ "${_manifest_file}" _manifest_content)

        # Re-enable libarchive's compression codecs (see header note). The
        # libarchive object has no nested braces, so [^}]* spans to its closing
        # brace; matching "libarchive" leaves cpp-httplib's entry untouched.
        string(REGEX REPLACE
            "\"name\"[ \t\r\n]*:[ \t\r\n]*\"libarchive\"[^}]*"
            "\"name\": \"libarchive\", \"default-features\": false, \"features\": [\"bzip2\", \"lz4\", \"lzma\", \"zstd\"]"
            _manifest_content "${_manifest_content}")
        file(WRITE "${_manifest_file}" "${_manifest_content}")

        # Verify it still parses and the libarchive xz/lzma feature landed.
        string(JSON _deps_type ERROR_VARIABLE _json_err TYPE "${_manifest_content}" dependencies)
        if(_json_err OR NOT _deps_type STREQUAL "ARRAY")
            file(REMOVE "${_manifest_file}")
            message(FATAL_ERROR
                "Downloaded DepthAI vcpkg manifest from ${_url} is not valid: ${_json_err}")
        endif()
        if(NOT _manifest_content MATCHES "libarchive[^}]*lzma")
            file(REMOVE "${_manifest_file}")
            message(FATAL_ERROR
                "Failed to enable libarchive xz/lzma support in the DepthAI manifest. "
                "Without it the OAK device firmware (.tar.xz) cannot be decompressed "
                "and the device boot hangs. Inspect ${_url} for a changed libarchive entry.")
        endif()

        file(WRITE "${_stamp_file}" "${_stamp_value}\n")
    endif()

    # Point vcpkg at the downloaded manifest and enable the "usb" feature (libusb).
    set(VCPKG_MANIFEST_DIR "${_manifest_dir}" CACHE PATH "vcpkg manifest dir (DepthAI's, auto-downloaded)" FORCE)
    set(VCPKG_MANIFEST_FEATURES "usb" CACHE STRING "DepthAI vcpkg features to enable" FORCE)
    set(VCPKG_MANIFEST_INSTALL ON CACHE BOOL "Run vcpkg install from the DepthAI manifest" FORCE)
    message(STATUS "Using DepthAI vcpkg manifest at ${_manifest_dir}")
endfunction()
