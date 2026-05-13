#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# camera_viz.sh — one entry point for local development AND robot
# deployment of the camera_viz example.
#
# Local:
#   ./camera_viz.sh setup [--sender-only]      install deps + build codec
#   ./camera_viz.sh loopback CONFIG            run streamer + viz on 127.0.0.1
#
# Remote (Jetson robot):
#   ./camera_viz.sh deploy --host H --user U [--password P] CONFIG
#   ./camera_viz.sh service-status   --host H --user U [--password P]
#   ./camera_viz.sh service-logs     --host H --user U [--password P]
#   ./camera_viz.sh service-restart  --host H --user U [--password P]
#
# SSH auth: --password uses sshpass (must be installed). Without it,
# falls back to plain ssh — you need keys set up.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$HERE/scripts"
SERVICE_NAME="camera-streamer"
SERVICE_TEMPLATE="$SCRIPTS_DIR/${SERVICE_NAME}.service.in"

# Where the source tree lands on the robot. ``~`` expands on the remote
# side at command time.
REMOTE_DIR='$HOME/camera_viz'

# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────

_C_OK="\033[32m"; _C_INFO="\033[36m"; _C_WARN="\033[33m"; _C_ERR="\033[31m"; _C_RESET="\033[0m"
log_info()  { echo -e "${_C_INFO}[info]${_C_RESET}  $*"; }
log_ok()    { echo -e "${_C_OK}[ok]${_C_RESET}    $*"; }
log_warn()  { echo -e "${_C_WARN}[warn]${_C_RESET}  $*" >&2; }
log_error() { echo -e "${_C_ERR}[error]${_C_RESET} $*" >&2; }
log_step()  { echo -e "\n\033[1m=== $* ===${_C_RESET}"; }

# ──────────────────────────────────────────────────────────────────────
# Shared remote arg parsing (--host/--user/--password)
# ──────────────────────────────────────────────────────────────────────

# Sets REMOTE_HOST / REMOTE_USER / REMOTE_PASSWORD and consumes those
# flags from "$@". Leaves any remaining positionals in REMOTE_REST[].
parse_remote_args() {
    REMOTE_HOST=""
    REMOTE_USER=""
    REMOTE_PASSWORD=""
    REMOTE_REST=()
    while (( $# )); do
        case $1 in
            --host)     REMOTE_HOST=$2; shift 2;;
            --user)     REMOTE_USER=$2; shift 2;;
            --password) REMOTE_PASSWORD=$2; shift 2;;
            --) shift; REMOTE_REST+=("$@"); break;;
            *)  REMOTE_REST+=("$1"); shift;;
        esac
    done
    [[ -n "$REMOTE_HOST" ]] || { log_error "--host is required"; exit 1; }
    [[ -n "$REMOTE_USER" ]] || { log_error "--user is required"; exit 1; }
    if [[ -n "$REMOTE_PASSWORD" ]] && ! command -v sshpass >/dev/null 2>&1; then
        log_error "--password set but sshpass not installed. apt install sshpass, or drop --password and use key auth."
        exit 1
    fi
}

# Run a command on the remote. Stdin is forwarded; stdout/stderr stream
# back. Caller passes the remote command as a single string in $1.
ssh_run() {
    local cmd="$1"
    if [[ -n "$REMOTE_PASSWORD" ]]; then
        sshpass -p "$REMOTE_PASSWORD" ssh -o StrictHostKeyChecking=accept-new \
            "$REMOTE_USER@$REMOTE_HOST" "$cmd"
    else
        ssh -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$REMOTE_HOST" "$cmd"
    fi
}

# Same as ssh_run but allocates a TTY (needed for remote sudo prompts).
ssh_run_tty() {
    local cmd="$1"
    if [[ -n "$REMOTE_PASSWORD" ]]; then
        sshpass -p "$REMOTE_PASSWORD" ssh -t -o StrictHostKeyChecking=accept-new \
            "$REMOTE_USER@$REMOTE_HOST" "$cmd"
    else
        ssh -t -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$REMOTE_HOST" "$cmd"
    fi
}

# rsync source → robot. Excludes build / venv / git artifacts.
rsync_to_remote() {
    local rsync_ssh="ssh -o StrictHostKeyChecking=accept-new"
    if [[ -n "$REMOTE_PASSWORD" ]]; then
        rsync_ssh="sshpass -p $REMOTE_PASSWORD $rsync_ssh"
    fi
    rsync -az --delete \
        --exclude='.venv/' \
        --exclude='codec/build/' \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude='.pytest_cache/' \
        -e "$rsync_ssh" \
        "$HERE/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"
}

# ──────────────────────────────────────────────────────────────────────
# setup (local)
# ──────────────────────────────────────────────────────────────────────

cmd_setup() {
    log_step "Local setup"
    exec "$SCRIPTS_DIR/_install_deps.sh" "$@"
}

# ──────────────────────────────────────────────────────────────────────
# loopback (local)
# ──────────────────────────────────────────────────────────────────────

cmd_loopback() {
    local config="${1:-}"
    [[ -n "$config" ]] || { log_error "usage: camera_viz.sh loopback CONFIG"; exit 1; }
    [[ -f "$config" ]] || { log_error "config not found: $config"; exit 1; }

    local venv="$HERE/.venv"
    [[ -x "$venv/bin/python" ]] || {
        log_error "no venv at $venv — run ./camera_viz.sh setup first"
        exit 1
    }

    # Receiver gets a copy of the config with source flipped to rtp.
    local recv_config
    recv_config="$(mktemp -t camera_viz_recv.XXXXXX.yaml)"
    # shellcheck disable=SC2064
    trap "rm -f '$recv_config'" EXIT
    "$venv/bin/python" - "$config" "$recv_config" <<'PY'
import sys, yaml
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f: cfg = yaml.safe_load(f)
cfg["source"] = "rtp"
with open(dst, "w") as f: yaml.safe_dump(cfg, f)
PY

    log_step "Starting camera_streamer → 127.0.0.1 (background)"
    "$venv/bin/python" "$HERE/camera_streamer.py" "$config" --host 127.0.0.1 &
    local sender_pid=$!

    cleanup_sender() {
        if kill -0 "$sender_pid" 2>/dev/null; then
            log_info "stopping camera_streamer (pid $sender_pid)"
            kill -INT "$sender_pid" 2>/dev/null || true
            wait "$sender_pid" 2>/dev/null || true
        fi
    }
    trap 'cleanup_sender; rm -f "$recv_config"' EXIT

    log_step "Starting camera_viz (foreground) — Ctrl-C to exit"
    "$venv/bin/python" "$HERE/camera_viz.py" "$recv_config"
}

# ──────────────────────────────────────────────────────────────────────
# deploy (remote)
# ──────────────────────────────────────────────────────────────────────

cmd_deploy() {
    parse_remote_args "$@"
    [[ "${#REMOTE_REST[@]}" -eq 1 ]] || {
        log_error "usage: camera_viz.sh deploy --host H --user U [--password P] CONFIG"
        exit 1
    }
    local config="${REMOTE_REST[0]}"
    [[ -f "$HERE/$config" ]] || {
        log_error "config not found: $HERE/$config"
        exit 1
    }
    [[ -f "$SERVICE_TEMPLATE" ]] || {
        log_error "service template missing: $SERVICE_TEMPLATE"
        exit 1
    }
    command -v rsync >/dev/null || { log_error "rsync not installed"; exit 1; }

    log_step "Pushing source → $REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR"
    rsync_to_remote
    log_ok "source synced"

    log_step "Installing deps on robot (sender-only)"
    # ``--sender-only`` means no isaacteleop wheel + no vulkan deps.
    # We pass --no-oakd / --no-v4l2 only if the user wants them; default
    # everything on so first deploy "just works" given the YAML.
    ssh_run "cd $REMOTE_DIR && bash scripts/_install_deps.sh --sender-only"
    log_ok "deps installed"

    log_step "Installing systemd unit"
    # Render the service file from template with absolute remote paths.
    # WORKDIR/VENV/CONFIG must be expanded on the REMOTE side because
    # ~/camera_viz expands to a different path per host. We do this with
    # a small shell snippet inline.
    local install_cmd
    install_cmd=$(cat <<REMOTE
set -euo pipefail
workdir="\$HOME/camera_viz"
venv="\$workdir/.venv"
config="\$workdir/$config"
unit_dir="\$HOME/.config/systemd/user"
mkdir -p "\$unit_dir"
sed -e "s|{{WORKDIR}}|\$workdir|g" \
    -e "s|{{VENV}}|\$venv|g" \
    -e "s|{{CONFIG}}|\$config|g" \
    "\$workdir/scripts/${SERVICE_NAME}.service.in" \
    > "\$unit_dir/${SERVICE_NAME}.service"
echo "wrote \$unit_dir/${SERVICE_NAME}.service"
systemctl --user daemon-reload
REMOTE
)
    ssh_run "$install_cmd"

    # loginctl enable-linger needs root, and only once per Jetson. Skip
    # if already enabled. ssh -t so the sudo prompt can interact.
    log_step "Enabling user-mode systemd persistence"
    local linger_cmd
    linger_cmd=$(cat <<REMOTE
if loginctl show-user "$REMOTE_USER" -p Linger 2>/dev/null | grep -q "Linger=yes"; then
    echo "linger already enabled"
else
    echo "enabling linger (sudo required, one-time)"
    sudo loginctl enable-linger "$REMOTE_USER"
fi
REMOTE
)
    ssh_run_tty "$linger_cmd"

    log_step "Enabling + starting service"
    ssh_run "systemctl --user enable --now ${SERVICE_NAME}.service"
    log_ok "deployed."

    log_info "Tail logs with:   ./camera_viz.sh service-logs --host $REMOTE_HOST --user $REMOTE_USER"
    log_info "Check status:     ./camera_viz.sh service-status --host $REMOTE_HOST --user $REMOTE_USER"
}

# ──────────────────────────────────────────────────────────────────────
# service-{status,logs,restart}
# ──────────────────────────────────────────────────────────────────────

cmd_service_status() {
    parse_remote_args "$@"
    ssh_run "systemctl --user status ${SERVICE_NAME}.service --no-pager" || true
}

cmd_service_logs() {
    parse_remote_args "$@"
    # ssh -t so Ctrl-C reaches journalctl cleanly.
    ssh_run_tty "journalctl --user -u ${SERVICE_NAME}.service -f"
}

cmd_service_restart() {
    parse_remote_args "$@"
    ssh_run "systemctl --user restart ${SERVICE_NAME}.service"
    log_ok "restarted"
}

# ──────────────────────────────────────────────────────────────────────
# Help
# ──────────────────────────────────────────────────────────────────────

show_help() {
    cat <<EOF
camera_viz.sh — local development + Jetson deployment for camera_viz

LOCAL
    setup [--sender-only] [--no-v4l2] [--no-oakd] [--no-rtp] [--with-zed]
                          Create .venv, install deps, build native codec.
                          --sender-only skips the isaacteleop wheel + vulkan
                          deps (use on Jetson sender hosts).

    loopback CONFIG       Run camera_streamer + camera_viz on 127.0.0.1.

REMOTE (Jetson robot)
    deploy --host H --user U [--password P] CONFIG
                          rsync source, install deps, install + start
                          systemd user service running camera_streamer.py.

    service-status   --host H --user U [--password P]
    service-logs     --host H --user U [--password P]
    service-restart  --host H --user U [--password P]
                          Inspect / manage the deployed service.

EXAMPLES
    ./camera_viz.sh setup
    ./camera_viz.sh loopback configs/v4l2.yaml
    ./camera_viz.sh deploy --host 10.29.90.127 --user nvidia configs/v4l2.yaml
    ./camera_viz.sh service-logs --host 10.29.90.127 --user nvidia

SSH AUTH
    Without --password, uses your SSH keys. With --password, uses sshpass
    (apt install sshpass). The password is passed via process args, so
    avoid this on shared hosts.
EOF
}

# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

[[ $# -eq 0 ]] && { show_help; exit 0; }

cmd="$1"; shift
case "$cmd" in
    setup)            cmd_setup "$@" ;;
    loopback)         cmd_loopback "$@" ;;
    deploy)           cmd_deploy "$@" ;;
    service-status)   cmd_service_status "$@" ;;
    service-logs)     cmd_service_logs "$@" ;;
    service-restart)  cmd_service_restart "$@" ;;
    -h|--help|help)   show_help ;;
    *) log_error "unknown command: $cmd"; show_help; exit 1 ;;
esac
