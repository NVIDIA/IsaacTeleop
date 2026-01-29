# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hunter package configuration for DepthAI dependencies.
# Derived from depthai-core v2.29.0 cmake/Hunter/config.cmake
# https://github.com/luxonis/depthai-core

hunter_config(
    nlohmann_json
    VERSION "3.9.1"
)

hunter_config(
    XLink
    VERSION "luxonis-2021.4.2-master"
    URL "https://github.com/luxonis/XLink/archive/2b517e1cb1ca77bea17679f9fdeb739812431174.tar.gz"
    SHA1 "fa7eeb46abeb97626dad923b7733899198284587"
    CMAKE_ARGS
        XLINK_ENABLE_LIBUSB=${DEPTHAI_ENABLE_LIBUSB}
)

hunter_config(
    BZip2
    VERSION "1.0.8-p0"
)

hunter_config(
    spdlog
    VERSION "1.8.2"
    URL "https://github.com/gabime/spdlog/archive/v1.8.2.tar.gz"
    SHA1 "4437f350ca7fa89a0cd8faca1198afb36823f775"
    CMAKE_ARGS
        SPDLOG_BUILD_EXAMPLE=OFF
        SPDLOG_FMT_EXTERNAL=OFF
        CMAKE_CXX_VISIBILITY_PRESET=hidden
        CMAKE_C_VISIBILITY_PRESET=hidden
)

# libarchive, luxonis fork
hunter_config(
    libarchive-luxonis
    VERSION "hunter-3.5.2"
    URL "https://github.com/luxonis/libarchive/archive/45baa3a3e57104519e1165bcd5ac29c3bd8c9f3a.tar.gz"
    SHA1 "ca5cd0f1c31b9c187d7119cb1aa7467f8c231d29"
    CMAKE_ARGS
        ENABLE_ACL=OFF
        ENABLE_BZip2=OFF
        ENABLE_CAT=OFF
        ENABLE_CAT_SHARED=OFF
        ENABLE_CNG=OFF
        ENABLE_COVERAGE=OFF
        ENABLE_CPIO=OFF
        ENABLE_CPIO_SHARED=OFF
        ENABLE_EXPAT=OFF
        ENABLE_ICONV=OFF
        ENABLE_INSTALL=ON
        ENABLE_LIBB2=OFF
        ENABLE_LIBXML2=OFF
        ENABLE_LZ4=OFF
        ENABLE_LZMA=ON
        ENABLE_LZO=OFF
        ENABLE_LibGCC=OFF
        ENABLE_MBEDTLS=OFF
        ENABLE_NETTLE=OFF
        ENABLE_OPENSSL=OFF
        ENABLE_PCREPOSIX=OFF
        ENABLE_SAFESEH=AUTO
        ENABLE_TAR=OFF
        ENABLE_TAR_SHARED=OFF
        ENABLE_TEST=OFF
        ENABLE_WERROR=OFF
        ENABLE_XATTR=OFF
        ENABLE_ZLIB=OFF
        ENABLE_ZSTD=OFF
)

# Luxonis FP16 fork which doesn't use git cloning for its dependencies
hunter_config(
    FP16
    VERSION "luxonis-0.0.0"
    URL "https://github.com/luxonis/FP16/archive/c911175d2717e562976e606c6e5f799bf40cf94e.tar.gz"
    SHA1 "40e9723c87c2fe21781132c0f2f8b90338500e32"
    CMAKE_ARGS
        FP16_BUILD_BENCHMARKS=OFF
        FP16_BUILD_TESTS=OFF
)

# Backward - Stacktrace printer
hunter_config(
    Backward
    VERSION "1.6"
    URL "https://github.com/bombela/backward-cpp/archive/refs/tags/v1.6.tar.gz"
    SHA1 "4ecb711eabfd15bc88ff9dd9342907fc5da46b62"
    CMAKE_ARGS
        BACKWARD_TESTS=OFF
)

# libnop - Serialization
hunter_config(
    libnop
    VERSION "1.0-ec8f75a"
    URL "https://github.com/luxonis/libnop/archive/ab842f51dc2eb13916dc98417c2186b78320ed10.tar.gz"
    SHA1 "32f40f084615ba7940ce9d29f05f3294371aabeb"
)

# Specific Catch2 version
hunter_config(
    Catch2
    VERSION "3.4.0"
    URL "https://github.com/catchorg/Catch2/archive/refs/tags/v3.4.0.tar.gz"
    SHA1 "4c308576c856a43dc88949a8f64ef90ebf94ae1b"
)

# ZLib - Luxonis fix for alias on imported target for old CMake versions
hunter_config(
    ZLIB
    VERSION "1.2.11-p2"
    URL "https://github.com/luxonis/zlib/archive/refs/tags/v1.2.11-p2.tar.gz"
    SHA1 "fb8b6486183b13a86040f793a939b128f6d27095"
)

# TMP, could be read from XLink
# libusb without udev
hunter_config(
    libusb-luxonis
    VERSION "1.0.24-cmake"
    URL "https://github.com/luxonis/libusb/archive/b7e4548958325b18feb73977163ad44398099534.tar.gz"
    SHA1 "2d79573d57628fe56d2868d2f6ce756d40906cf4"
    CMAKE_ARGS
        WITH_UDEV=OFF
        # Build shared libs by default to not cause licensing issues
        BUILD_SHARED_LIBS=ON
)

hunter_config(
    CURL
    VERSION "7.88.1-p0-custom"
    URL "https://github.com/cpp-pm/curl/archive/25d45e89d140d6ab27103cd7f8f6d7d6cf548d47.tar.gz"
    SHA1 "db96d87e078e529a90dfb74de8d360a785c053aa"
    CMAKE_ARGS
        BUILD_CURL_TESTS=OFF
        BUILD_CURL_EXE=OFF
        CURL_USE_SCHANNEL=${DEPTHAI_CURL_USE_SCHANNEL}
        CURL_USE_OPENSSL=${DEPTHAI_CURL_USE_OPENSSL} # Override hunter flags - no OpenSSL needed on Windows
        BUILD_STATIC_CURL=ON
        BUILD_SHARED_LIBS=OFF
        BUILD_STATIC_LIBS=ON
)

# A hunterized and patched version of cpr- see https://github.com/luxonis/cpr/pull/1
hunter_config(
    cpr
    VERSION "1.4.0"
    URL "https://github.com/luxonis/cpr/archive/50a1321738554e0152b0a6f1b0ca24e4fdecff5c.tar.gz"
    SHA1 "2e2ba9920ed99c19887592ca89d9be5ffce4722b"
)

hunter_config(
    ghc_filesystem
    VERSION "1.5.14-luxonis"
    URL "https://github.com/luxonis/filesystem/archive/d29630953f3526b61842d937764f012503a79ec3.tar.gz"
    SHA1 "1cee5c95b53e014710970c920230ad1d3f3b5055"
    CMAKE_ARGS
        GHC_FILESYSTEM_BUILD_EXAMPLES=OFF
        GHC_FILESYSTEM_BUILD_TESTING=OFF
)
