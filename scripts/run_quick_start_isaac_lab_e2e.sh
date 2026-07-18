#!/usr/bin/env bash
#
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Validate the Quick Start "Teleoperation in Isaac Lab" next step against a
# pre-provisioned Isaac Lab checkout. The script installs the candidate
# isaacteleop wheel into that Isaac Lab environment, launches CloudXR with the
# hosted no-headset client path, then runs Isaac Lab's XR teleop app under a
# bounded timeout.

set -euo pipefail

ROOT_DIR=$(git rev-parse --show-toplevel)
GUIDE_PATH="docs/source/getting_started/quick_start.rst"
ISAAC_LAB_ROOT="${QUICK_START_ISAAC_LAB_ROOT:-${ISAAC_LAB_ROOT:-}}"
ARTIFACT_DIR="${QUICK_START_ISAAC_LAB_ARTIFACT_DIR:-${RUNNER_TEMP:-/tmp}/isaacteleop-quick-start-isaac-lab-e2e}"
CLOUDXR_INSTALL_DIR="${QUICK_START_ISAAC_LAB_CLOUDXR_INSTALL_DIR:-${ARTIFACT_DIR}/cloudxr}"
WHEEL_DIR="${QUICK_START_ISAAC_LAB_WHEEL_DIR:-${ROOT_DIR}/install/wheels}"
PIP_EXTRA_INDEX_URL="${QUICK_START_ISAAC_LAB_PIP_EXTRA_INDEX_URL:-https://pypi.nvidia.com}"
CLOUDXR_READY_TIMEOUT_SEC="${QUICK_START_ISAAC_LAB_CLOUDXR_READY_TIMEOUT_SEC:-180}"
CLIENT_PROBE_TIMEOUT_SEC="${QUICK_START_ISAAC_LAB_CLIENT_PROBE_TIMEOUT_SEC:-90}"
ISAAC_LAB_TIMEOUT_SEC="${QUICK_START_ISAAC_LAB_TIMEOUT_SEC:-180}"
DEFAULT_CLOUDXR_SERVER_PORT=49100
DEFAULT_WSS_PROXY_PORT=48322
RUNTIME_PORT="${QUICK_START_ISAAC_LAB_RUNTIME_PORT:-}"
PROXY_PORT="${QUICK_START_ISAAC_LAB_WSS_PROXY_PORT:-}"
TELEOP_CLIENT_CODEC="${TELEOP_CLIENT_CODEC:-h264}"

CLOUDXR_LOG="${ARTIFACT_DIR}/cloudxr-server.log"
CLIENT_PROBE_LOG="${ARTIFACT_DIR}/client-probe.log"
CLIENT_STATE_JSON="${ARTIFACT_DIR}/client-oob-state.json"
ISAAC_LAB_LOG="${ARTIFACT_DIR}/isaac-lab-xr-teleop.log"
SUMMARY_JSON="${ARTIFACT_DIR}/quick-start-isaac-lab-e2e-summary.json"

cloudxr_pid=""

log() {
    printf '[quick-start-isaac-lab-e2e] %s\n' "$*"
}

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
    mkdir -p "${ARTIFACT_DIR}"
    cat > "${SUMMARY_JSON}" <<JSON
{
  "status": $(json_escape "${status}"),
  "message": $(json_escape "${message}"),
  "guide": $(json_escape "${GUIDE_PATH}"),
  "isaac_lab_root": $(json_escape "${ISAAC_LAB_ROOT}"),
  "isaac_lab_task": "IsaacContrib-Stack-Cube-Franka-IK-Abs",
  "cloudxr_log": $(json_escape "${CLOUDXR_LOG}"),
  "client_probe_log": $(json_escape "${CLIENT_PROBE_LOG}"),
  "client_state_json": $(json_escape "${CLIENT_STATE_JSON}"),
  "isaac_lab_log": $(json_escape "${ISAAC_LAB_LOG}"),
  "cloudxr_server_port": $(json_escape "${NV_CXR_SERVER_PORT:-}"),
  "wss_proxy_port": $(json_escape "${PROXY_PORT:-}")
}
JSON
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

require_isaac_lab() {
    if [[ -z "${ISAAC_LAB_ROOT}" ]]; then
        fail "set QUICK_START_ISAAC_LAB_ROOT or ISAAC_LAB_ROOT to a provisioned Isaac Lab checkout"
    fi
    if [[ ! -x "${ISAAC_LAB_ROOT}/isaaclab.sh" ]]; then
        fail "Isaac Lab launcher not found or not executable: ${ISAAC_LAB_ROOT}/isaaclab.sh"
    fi
    if [[ ! -f "${ISAAC_LAB_ROOT}/scripts/environments/teleoperation/teleop_se3_agent.py" ]]; then
        fail "Isaac Lab teleop_se3_agent.py was not found under ${ISAAC_LAB_ROOT}"
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

isaaclab_python() {
    (cd "${ISAAC_LAB_ROOT}" && ./isaaclab.sh -p "$@")
}

install_candidate_wheel() {
    if [[ "${QUICK_START_ISAAC_LAB_SKIP_INSTALL:-0}" == "1" ]]; then
        log "Skipping candidate wheel install because QUICK_START_ISAAC_LAB_SKIP_INSTALL=1"
        return 0
    fi

    local wheel
    local resolve_rc=0
    wheel=$(resolve_wheel) || resolve_rc=$?
    if (( resolve_rc != 0 )); then
        fail "could not resolve exactly one isaacteleop wheel from ${WHEEL_DIR}"
    fi

    local wheel_name
    local wheel_version
    wheel_name=$(basename "${wheel}")
    wheel_version=$(sed -E 's/^isaacteleop-([^-]+)-.*/\1/' <<< "${wheel_name}" | tr '_' '-')

    log "Installing candidate wheel ${wheel_name} into Isaac Lab"
    isaaclab_python -m pip install --no-cache-dir "${wheel}"
    isaaclab_python -m pip install \
        --no-cache-dir \
        --extra-index-url "${PIP_EXTRA_INDEX_URL}" \
        "isaacteleop[cloudxr,retargeters]==${wheel_version}"
}

port_is_available() {
    python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("", port))
    except OSError:
        raise SystemExit(1) from None
PY
}

pick_free_port() {
    python3 - <<'PY'
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

    if [[ "${CI:-}" == "true" ]]; then
        pick_free_port
        return 0
    fi

    if port_is_available "${default_port}"; then
        printf '%s\n' "${default_port}"
        return 0
    fi

    pick_free_port
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
    if [[ ! -s "${file}" ]]; then
        fail "${label} did not produce a log"
    fi
    if grep -Eiq 'Traceback|RuntimeError|Segmentation fault|Aborted|failed to start|exited unexpectedly' "${file}"; then
        log "===== ${label} ====="
        cat "${file}" || true
        fail "${label} contains a fatal error"
    fi
}

run_client_probe() {
    local client_url="https://127.0.0.1:${PROXY_PORT}/client/?oobEnable=1&autoConnect=1&serverIP=127.0.0.1&port=${PROXY_PORT}&headless=true&autoRefreshMode=never&deviceFrameRate=72&codec=${TELEOP_CLIENT_CODEC}"
    local state_url="https://127.0.0.1:${PROXY_PORT}/api/oob/v1/state"
    local probe_rc=0

    log "Connecting hosted desktop/IWER client"
    isaaclab_python "${ROOT_DIR}/scripts/quick_start_client_probe.py" \
        --client-url "${client_url}" \
        --state-url "${state_url}" \
        --timeout "${CLIENT_PROBE_TIMEOUT_SEC}" \
        --summary-json "${CLIENT_STATE_JSON}" \
        > "${CLIENT_PROBE_LOG}" 2>&1 || probe_rc=$?

    if (( probe_rc != 0 )); then
        log "===== client probe log ====="
        cat "${CLIENT_PROBE_LOG}" || true
        fail "desktop/IWER client probe exited with status ${probe_rc}"
    fi
}

run_isaac_lab_teleop() {
    local env_file="$1"
    local app_rc=0

    log "Running Isaac Lab XR teleop app under ${ISAAC_LAB_TIMEOUT_SEC}s timeout"
    (
        set -euo pipefail
        cd "${ISAAC_LAB_ROOT}"
        # shellcheck disable=SC1090
        source "${env_file}"
        timeout "${ISAAC_LAB_TIMEOUT_SEC}" ./isaaclab.sh -p \
            scripts/environments/teleoperation/teleop_se3_agent.py \
            --task IsaacContrib-Stack-Cube-Franka-IK-Abs \
            --viz kit \
            --num_envs 1 \
            --xr
    ) > "${ISAAC_LAB_LOG}" 2>&1 || app_rc=$?

    if (( app_rc != 0 && app_rc != 124 )); then
        log "===== Isaac Lab teleop log ====="
        cat "${ISAAC_LAB_LOG}" || true
        fail "Isaac Lab XR teleop app exited with status ${app_rc}"
    fi

    assert_clean_log "Isaac Lab teleop log" "${ISAAC_LAB_LOG}"
    log "Isaac Lab XR teleop app reached bounded runtime without fatal errors"
}

main() {
    rm -rf "${ARTIFACT_DIR}"
    mkdir -p "${ARTIFACT_DIR}"

    require_isaac_lab
    test -f "${ROOT_DIR}/${GUIDE_PATH}" || fail "Quick Start guide not found at ${GUIDE_PATH}"
    install_candidate_wheel

    RUNTIME_PORT=$(resolve_port "${RUNTIME_PORT}" "${DEFAULT_CLOUDXR_SERVER_PORT}") || \
        fail "requested CloudXR runtime port ${RUNTIME_PORT} is not available"
    PROXY_PORT=$(resolve_port "${PROXY_PORT}" "${DEFAULT_WSS_PROXY_PORT}") || \
        fail "requested WSS proxy port ${PROXY_PORT} is not available"
    while [[ "${PROXY_PORT}" == "${RUNTIME_PORT}" ]]; do
        PROXY_PORT=$(pick_free_port)
    done
    export NV_CXR_SERVER_PORT="${RUNTIME_PORT}"
    export PROXY_PORT
    export TELEOP_STREAM_SERVER_IP="${TELEOP_STREAM_SERVER_IP:-127.0.0.1}"
    export TELEOP_STREAM_PORT="${TELEOP_STREAM_PORT:-${PROXY_PORT}}"
    export TELEOP_CLIENT_CODEC

    log "Starting CloudXR server with hosted client/OOB hub"
    PYTHONUNBUFFERED=1 isaaclab_python -u -m isaacteleop.cloudxr \
        --cloudxr-install-dir "${CLOUDXR_INSTALL_DIR}" \
        --accept-eula \
        --host-client \
        --enable-oob-hub \
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

    run_client_probe
    run_isaac_lab_teleop "${env_file}"

    write_summary "passed" "Isaac Lab XR teleop app launched with hosted CloudXR client state"
    log "Quick Start Isaac Lab E2E workflow completed"
}

main "$@"
