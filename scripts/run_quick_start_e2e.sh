#!/usr/bin/env bash
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Exercise the runnable workflow from docs/source/getting_started/quick_start.rst
# on a clean runner environment. CI uses the wheel produced by the current run;
# local developers can omit QUICK_START_E2E_WHEEL_DIR to install from PyPI as the
# guide describes.

set -euo pipefail

ROOT_DIR=$(git rev-parse --show-toplevel)
GUIDE_PATH="docs/source/getting_started/quick_start.rst"
PYTHON_BIN="${QUICK_START_E2E_PYTHON:-python3}"
ARTIFACT_DIR="${QUICK_START_E2E_ARTIFACT_DIR:-${RUNNER_TEMP:-/tmp}/isaacteleop-quick-start-e2e}"
VENV_DIR="${QUICK_START_E2E_VENV_DIR:-${ARTIFACT_DIR}/venv}"
CLOUDXR_INSTALL_DIR="${QUICK_START_E2E_CLOUDXR_INSTALL_DIR:-${ARTIFACT_DIR}/cloudxr}"
WHEEL_DIR="${QUICK_START_E2E_WHEEL_DIR:-${ROOT_DIR}/install/wheels}"
PIP_SPEC="${QUICK_START_E2E_PIP_SPEC:-isaacteleop[cloudxr,retargeters]~=1.0.0}"
PIP_EXTRA_INDEX_URL="${QUICK_START_E2E_PIP_EXTRA_INDEX_URL:-https://pypi.nvidia.com}"
CLOUDXR_READY_TIMEOUT_SEC="${QUICK_START_E2E_CLOUDXR_READY_TIMEOUT_SEC:-180}"
EXAMPLE_TIMEOUT_SEC="${QUICK_START_E2E_EXAMPLE_TIMEOUT_SEC:-75}"
DEFAULT_CLOUDXR_SERVER_PORT=49100
DEFAULT_WSS_PROXY_PORT=48322
RUNTIME_PORT="${QUICK_START_E2E_RUNTIME_PORT:-}"
PROXY_PORT="${QUICK_START_E2E_WSS_PROXY_PORT:-}"

CLOUDXR_LOG="${ARTIFACT_DIR}/cloudxr-server.log"
EXAMPLE_LOG="${ARTIFACT_DIR}/gripper-retargeting-example.log"
SUMMARY_JSON="${ARTIFACT_DIR}/quick-start-e2e-summary.json"

cloudxr_pid=""

log() {
    printf '[quick-start-e2e] %s\n' "$*"
}

fail() {
    log "ERROR: $*"
    write_summary "failed" "$*"
    exit 1
}

cleanup() {
    if [[ -n "${cloudxr_pid}" ]] && kill -0 "${cloudxr_pid}" 2>/dev/null; then
        log "Stopping CloudXR server (pid=${cloudxr_pid})"
        kill "${cloudxr_pid}" 2>/dev/null || true
        wait "${cloudxr_pid}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

json_escape() {
    python3 - "$1" <<'PY'
import json
import sys

print(json.dumps(sys.argv[1]))
PY
}

write_summary() {
    local status="$1"
    local message="$2"
    local gripper_lines="0"
    if [[ -f "${EXAMPLE_LOG}" ]]; then
        gripper_lines=$(grep -Ec 'Right:[[:space:]]*-?[0-9]+([.][0-9]+)?' "${EXAMPLE_LOG}" || true)
    fi

    mkdir -p "${ARTIFACT_DIR}"
    cat > "${SUMMARY_JSON}" <<JSON
{
  "status": $(json_escape "${status}"),
  "message": $(json_escape "${message}"),
  "guide": $(json_escape "${GUIDE_PATH}"),
  "cloudxr_log": $(json_escape "${CLOUDXR_LOG}"),
  "example_log": $(json_escape "${EXAMPLE_LOG}"),
  "cloudxr_server_port": $(json_escape "${NV_CXR_SERVER_PORT:-}"),
  "wss_proxy_port": $(json_escape "${PROXY_PORT:-}"),
  "gripper_output_lines": ${gripper_lines}
}
JSON
}

wait_for_file() {
    local path="$1"
    local timeout="$2"
    local deadline=$((SECONDS + timeout))

    while [[ "${SECONDS}" -lt "${deadline}" ]]; do
        if [[ -f "${path}" ]]; then
            return 0
        fi
        if [[ -n "${cloudxr_pid}" ]] && ! kill -0 "${cloudxr_pid}" 2>/dev/null; then
            return 1
        fi
        sleep 1
    done

    return 1
}

wait_for_log_line() {
    local pattern="$1"
    local timeout="$2"
    local deadline=$((SECONDS + timeout))

    while [[ "${SECONDS}" -lt "${deadline}" ]]; do
        if [[ -f "${CLOUDXR_LOG}" ]] && grep -qE "${pattern}" "${CLOUDXR_LOG}"; then
            return 0
        fi
        if [[ -n "${cloudxr_pid}" ]] && ! kill -0 "${cloudxr_pid}" 2>/dev/null; then
            return 1
        fi
        sleep 1
    done

    return 1
}

assert_clean_log() {
    local label="$1"
    local file="$2"
    if grep -Eiq 'Traceback|RuntimeError|Segmentation fault|Aborted|failed to start|exited unexpectedly' "${file}"; then
        log "===== ${label} ====="
        cat "${file}" || true
        fail "${label} contains a fatal error"
    fi
}

resolve_wheel() {
    shopt -s nullglob
    local wheels=("${WHEEL_DIR}"/isaacteleop-*.whl)
    shopt -u nullglob

    if (( ${#wheels[@]} == 0 )); then
        return 1
    fi
    if (( ${#wheels[@]} > 1 )); then
        printf 'Expected one wheel in %s, found %d\n' "${WHEEL_DIR}" "${#wheels[@]}" >&2
        return 2
    fi

    printf '%s\n' "${wheels[0]}"
}

port_is_available() {
    "${PYTHON_BIN}" - "$1" <<'PY'
import socket
import sys

try:
    port = int(sys.argv[1])
except ValueError:
    raise SystemExit(2) from None

if not 1 <= port <= 65535:
    raise SystemExit(2)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("", port))
    except OSError:
        raise SystemExit(1) from None
PY
}

pick_free_port() {
    "${PYTHON_BIN}" - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("", 0))
    print(sock.getsockname()[1])
PY
}

resolve_port() {
    local requested="$1"
    local default_port="$2"

    if [[ -n "${requested}" ]]; then
        port_is_available "${requested}" || return $?
        printf '%s\n' "${requested}"
        return 0
    fi

    if port_is_available "${default_port}"; then
        printf '%s\n' "${default_port}"
        return 0
    fi

    pick_free_port
}

install_package() {
    local venv_python="${VENV_DIR}/bin/python"
    local wheel=""
    local resolve_rc=0

    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
    "${venv_python}" -m pip install --upgrade pip

    wheel=$(resolve_wheel) || resolve_rc=$?
    if (( resolve_rc == 0 )); then
        local wheel_name
        local wheel_version
        wheel_name=$(basename "${wheel}")
        wheel_version=$(sed -E 's/^isaacteleop-([^-]+)-.*/\1/' <<< "${wheel_name}" | tr '_' '-')
        log "Step 2: installing candidate wheel ${wheel_name} with guide extras"
        "${venv_python}" -m pip install --no-cache-dir "${wheel}"
        "${venv_python}" -m pip install \
            --no-cache-dir \
            --extra-index-url "${PIP_EXTRA_INDEX_URL}" \
            "isaacteleop[cloudxr,retargeters]==${wheel_version}"
    elif (( resolve_rc == 1 )); then
        if [[ "${QUICK_START_E2E_REQUIRE_WHEEL:-0}" == "1" ]]; then
            fail "no isaacteleop wheel found in ${WHEEL_DIR}"
        fi
        log "Step 2: installing from PyPI spec: ${PIP_SPEC}"
        "${venv_python}" -m pip install \
            --no-cache-dir \
            --extra-index-url "${PIP_EXTRA_INDEX_URL}" \
            "${PIP_SPEC}"
    else
        fail "could not resolve a single isaacteleop wheel from ${WHEEL_DIR}"
    fi
}

check_wss_proxy_port() {
    "${VENV_DIR}/bin/python" - "${PROXY_PORT}" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=5.0):
    pass
PY
}

run_example() {
    local env_file="$1"

    log "Step 6: sourcing ${env_file}"
    # shellcheck disable=SC1090
    source "${env_file}"

    log "Step 7: running examples/teleop/python/gripper_retargeting_example_simple.py"
    local example_rc=0
    if command -v timeout >/dev/null 2>&1; then
        timeout "${EXAMPLE_TIMEOUT_SEC}" \
            "${VENV_DIR}/bin/python" "${ROOT_DIR}/examples/teleop/python/gripper_retargeting_example_simple.py" \
            > "${EXAMPLE_LOG}" 2>&1 || example_rc=$?
    else
        "${VENV_DIR}/bin/python" "${ROOT_DIR}/examples/teleop/python/gripper_retargeting_example_simple.py" \
            > "${EXAMPLE_LOG}" 2>&1 || example_rc=$?
    fi

    if (( example_rc != 0 )); then
        log "===== gripper retargeting example log ====="
        cat "${EXAMPLE_LOG}" || true
        fail "gripper example exited with status ${example_rc}"
    fi

    assert_clean_log "gripper retargeting example log" "${EXAMPLE_LOG}"
    grep -q 'Gripper Retargeting' "${EXAMPLE_LOG}" || fail "gripper example did not print its startup banner"

    local gripper_lines
    gripper_lines=$(grep -Ec 'Right:[[:space:]]*-?[0-9]+([.][0-9]+)?' "${EXAMPLE_LOG}" || true)
    if (( gripper_lines < 2 )); then
        log "===== gripper retargeting example log ====="
        cat "${EXAMPLE_LOG}" || true
        fail "expected at least 2 gripper output lines, found ${gripper_lines}"
    fi
}

main() {
    rm -rf "${ARTIFACT_DIR}"
    mkdir -p "${ARTIFACT_DIR}"

    log "Step 1: using checked-out repository at ${ROOT_DIR}"
    test -f "${ROOT_DIR}/${GUIDE_PATH}" || fail "Quick Start guide not found at ${GUIDE_PATH}"
    test -f "${ROOT_DIR}/examples/teleop/python/gripper_retargeting_example_simple.py" || \
        fail "documented gripper example is missing"

    install_package

    RUNTIME_PORT=$(resolve_port "${RUNTIME_PORT}" "${DEFAULT_CLOUDXR_SERVER_PORT}") || \
        fail "requested CloudXR runtime port ${RUNTIME_PORT} is not available"
    PROXY_PORT=$(resolve_port "${PROXY_PORT}" "${DEFAULT_WSS_PROXY_PORT}") || \
        fail "requested WSS proxy port ${PROXY_PORT} is not available"
    while [[ "${PROXY_PORT}" == "${RUNTIME_PORT}" ]]; do
        PROXY_PORT=$(pick_free_port)
    done
    export NV_CXR_SERVER_PORT="${RUNTIME_PORT}"
    export PROXY_PORT
    log "Using CloudXR runtime port ${NV_CXR_SERVER_PORT} and WSS proxy port ${PROXY_PORT}"

    log "Step 3: starting CloudXR server with --accept-eula"
    PYTHONUNBUFFERED=1 "${VENV_DIR}/bin/python" -u -m isaacteleop.cloudxr \
        --cloudxr-install-dir "${CLOUDXR_INSTALL_DIR}" \
        --accept-eula \
        > "${CLOUDXR_LOG}" 2>&1 &
    cloudxr_pid=$!

    local env_file="${CLOUDXR_INSTALL_DIR}/run/cloudxr.env"
    wait_for_file "${env_file}" "${CLOUDXR_READY_TIMEOUT_SEC}" || {
        log "===== CloudXR server log ====="
        cat "${CLOUDXR_LOG}" || true
        fail "CloudXR did not write ${env_file}"
    }
    wait_for_log_line 'CloudXR runtime:.*running' "${CLOUDXR_READY_TIMEOUT_SEC}" || {
        log "===== CloudXR server log ====="
        cat "${CLOUDXR_LOG}" || true
        fail "CloudXR runtime did not report running"
    }
    wait_for_log_line 'CloudXR WSS proxy:.*running' "${CLOUDXR_READY_TIMEOUT_SEC}" || {
        log "===== CloudXR server log ====="
        cat "${CLOUDXR_LOG}" || true
        fail "CloudXR WSS proxy did not report running"
    }
    assert_clean_log "CloudXR server log" "${CLOUDXR_LOG}"

    log "Step 4: firewall allow-list is a machine configuration step; CI validates the local WSS proxy port instead"
    check_wss_proxy_port || fail "WSS proxy port ${PROXY_PORT} is not reachable on localhost"

    log "Step 5: desktop browser/IWER is the documented headset-free client path; this CI baseline does not inspect the website"

    run_example "${env_file}"

    log "Quick Start E2E workflow completed"
    write_summary "passed" "Quick Start workflow reached the documented gripper example and emitted output"
}

main "$@"
