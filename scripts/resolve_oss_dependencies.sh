#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "${1:-.}" && pwd)"
output_dir="${OSS_REPORT_DIR:-${repo_root}/oss-report}"
resolution_dir="${output_dir}/resolution"
mkdir -p "${resolution_dir}"

python3 "${repo_root}/scripts/collect_oss_dependencies.py" \
  --repo-root "${repo_root}" \
  --output "${output_dir}/dependency-inventory.json" \
  --summary "${output_dir}/dependency-inventory.md" \
  --resolution-input-dir "${resolution_dir}/inputs"

uv pip compile \
  --python-version 3.11 \
  --universal \
  --no-header \
  --output-file "${resolution_dir}/python-requirements.lock" \
  "${resolution_dir}/inputs/python-requirements.in"

while IFS= read -r package_json; do
  npm install \
    --prefix "$(dirname "${package_json}")" \
    --package-lock-only \
    --ignore-scripts \
    --no-audit \
    --no-fund
done < <(find "${resolution_dir}/inputs/npm" -name package.json -print | sort)

if [[ -z "${VCPKG_ROOT:-}" || ! -f "${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" ]]; then
  echo "VCPKG_ROOT must point to a bootstrapped vcpkg checkout." >&2
  exit 2
fi

cmake_build_dir="${resolution_dir}/cmake-max"
cmake_trace="${resolution_dir}/cmake-trace.jsonl"
cmake \
  --trace-expand \
  --trace-format=json-v1 \
  --trace-redirect="${cmake_trace}" \
  -S "${repo_root}" \
  -B "${cmake_build_dir}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake" \
  -DISAAC_TELEOP_PYTHON_VERSION=3.11 \
  -DBUILD_EXAMPLES=ON \
  -DBUILD_PLUGINS=ON \
  -DBUILD_PLUGIN_OAK_CAMERA=ON \
  -DBUILD_TESTING=ON \
  -DBUILD_VIZ=ON \
  -DBUNDLE_ROBOTIC_GROUNDING=OFF \
  -DENABLE_CLANG_FORMAT_CHECK=OFF \
  -DENABLE_CLOUDXR_BUNDLE_CHECK=OFF

vcpkg_status="${cmake_build_dir}/vcpkg_installed/vcpkg/status"
if [[ ! -s "${vcpkg_status}" ]]; then
  echo "Configured max-dependency profile did not produce vcpkg status metadata." >&2
  exit 2
fi
vcpkg_status_evidence="${resolution_dir}/vcpkg-status"
cp "${vcpkg_status}" "${vcpkg_status_evidence}"

trivy fs \
  --no-progress \
  --skip-dirs "${output_dir}" \
  --format cyclonedx \
  --output "${resolution_dir}/trivy-source.cdx.json" \
  "${repo_root}"

python3 "${repo_root}/scripts/audit_oss_dependency_coverage.py" \
  --repo-root "${repo_root}" \
  --inventory "${output_dir}/dependency-inventory.json" \
  --resolution-inputs "${resolution_dir}/inputs/resolution-inputs.json" \
  --python-lock "${resolution_dir}/python-requirements.lock" \
  --npm-root "${resolution_dir}/inputs/npm" \
  --cmake-trace "${cmake_trace}" \
  --cmake-build-dir "${cmake_build_dir}" \
  --vcpkg-status "${vcpkg_status_evidence}" \
  --base-sbom "${resolution_dir}/trivy-source.cdx.json" \
  --output-sbom "${output_dir}/bom.cdx.json" \
  --output-report "${output_dir}/dependency-coverage.json" \
  --output-summary "${output_dir}/dependency-coverage.md" \
  --fail-on-gaps

# The audit has already captured the expanded trace, exact fetched commits, and
# vcpkg status. Keep those compact records, not the generated build tree.
rm -rf "${cmake_build_dir}"
