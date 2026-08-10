#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# One entry point for building, inspecting, recording, and verifying the
# capability-compatible Orbbec Ego camera plugin.  It intentionally never
# installs packages, SDKs, or udev rules: those operations need user approval.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DEFAULT_PRESET="py3.11"

die() {
    echo "orbbec_ego.sh: $*" >&2
    exit 1
}

warn() {
    echo "orbbec_ego.sh: warning: $*" >&2
}

usage() {
    cat <<'EOF'
Usage:
  src/plugins/orbbec/orbbec_ego.sh doctor [--sdk-root PATH] [--preset py3.11]
  src/plugins/orbbec/orbbec_ego.sh build --sdk-root PATH [--preset py3.11] [--jobs N] [--clean] [--install-prefix PATH]
  src/plugins/orbbec/orbbec_ego.sh capabilities [--preset py3.11] [--plugin PATH]
  src/plugins/orbbec/orbbec_ego.sh record [options] [-- PLUGIN_OPTIONS...]
  src/plugins/orbbec/orbbec_ego.sh verify RUN_DIRECTORY [--preset py3.11] [--plugin PATH]

Common record options:
  --duration SECONDS              Stop cleanly after SECONDS; omit for Ctrl-C.
  --output DIRECTORY              Default: recordings/orbbec_ego_<timestamp>.
  --format mjpg|h264|h265         Default: h264.
  --width N --height N --fps N    Default: 1600 1300 30.
  --device-uid UID                Select one enumerated device.
  --no-imu --no-audio             Do not request optional sensors.
  --preview                       Enable the plugin's SDL preview.
  --mcap-media MODE               metadata-only (default) or embedded.
  --keep-media-sidecars           Retain H.264/H.265/MJPEG and WAV beside embedded MCAP.
  --preset NAME --plugin PATH     Select a build tree or override the executable.

Examples:
  ./src/plugins/orbbec/orbbec_ego.sh doctor --sdk-root /opt/OrbbecSDK
  ./src/plugins/orbbec/orbbec_ego.sh build --sdk-root /opt/OrbbecSDK --jobs 8
  ./src/plugins/orbbec/orbbec_ego.sh capabilities
  ./src/plugins/orbbec/orbbec_ego.sh record --duration 30
  ./src/plugins/orbbec/orbbec_ego.sh verify recordings/orbbec_ego_20260810_120000

All options after -- are passed unchanged to camera_plugin_orbbec.  For example:
  ... record --duration 30 -- --bitrate=8 --dynamic-bitrate=on
EOF
}

preset_python_version() {
    case "$1" in
        py3.10) echo "3.10" ;;
        py3.11) echo "3.11" ;;
        py3.12) echo "3.12" ;;
        py3.13) echo "3.13" ;;
        *) die "Unknown preset '$1'. Expected py3.10, py3.11, py3.12, or py3.13." ;;
    esac
}

build_dir_for_preset() {
    local version compact_version
    version="$(preset_python_version "$1")"
    # CMakePresets names build directories with the compact CPython ABI digits:
    # py3.11 -> cmake-cpython-311, not cmake-cpython-11.
    compact_version="${version//./}"
    echo "$SOURCE_ROOT/build/cmake-cpython-$compact_version"
}

validate_sdk_root() {
    local sdk_root="$1"
    [[ -n "$sdk_root" ]] || die "--sdk-root PATH (or ORBBEC_SDK_ROOT) is required."
    [[ -f "$sdk_root/include/libobsensor/ObSensor.hpp" ]] || die "Invalid SDK root '$sdk_root': missing include/libobsensor/ObSensor.hpp"
    [[ -f "$sdk_root/lib/OrbbecSDKConfig.cmake" ]] || die "Invalid SDK root '$sdk_root': missing lib/OrbbecSDKConfig.cmake"
    [[ -f "$sdk_root/lib/libOrbbecSDK.so.2" ]] || die "Invalid SDK root '$sdk_root': missing lib/libOrbbecSDK.so.2"
    [[ -d "$sdk_root/lib/extensions" ]] || die "Invalid SDK root '$sdk_root': missing lib/extensions"
}

resolve_plugin() {
    local preset="$1"
    local requested="${2:-}"
    local candidate
    if [[ -n "$requested" ]]; then
        candidate="$requested"
    elif [[ -n "${ORBBEC_PLUGIN:-}" ]]; then
        candidate="$ORBBEC_PLUGIN"
    elif [[ -x "$SCRIPT_DIR/camera_plugin_orbbec" ]]; then
        candidate="$SCRIPT_DIR/camera_plugin_orbbec"
    else
        candidate="$(build_dir_for_preset "$preset")/src/plugins/orbbec/app/camera_plugin_orbbec"
    fi
    [[ -x "$candidate" ]] || die "Plugin is not executable: $candidate. Run 'build' first or pass --plugin PATH."
    echo "$candidate"
}

resolve_exporter() {
    local preset="$1"
    local candidate
    if [[ -x "$SCRIPT_DIR/orbbec_mcap_export_media" ]]; then
        candidate="$SCRIPT_DIR/orbbec_mcap_export_media"
    else
        candidate="$(build_dir_for_preset "$preset")/src/plugins/orbbec/app/orbbec_mcap_export_media"
    fi
    [[ -x "$candidate" ]] || die "Embedded-media exporter is not executable: $candidate. Run 'build' first."
    echo "$candidate"
}

require_command() {
    local command_name="$1"
    local remediation="$2"
    if ! command -v "$command_name" >/dev/null 2>&1; then
        warn "Missing command '$command_name'. $remediation"
        return 1
    fi
}

command_doctor() {
    local sdk_root="${ORBBEC_SDK_ROOT:-}"
    local preset="$DEFAULT_PRESET"
    local arg
    while (( $# )); do
        arg="$1"
        case "$arg" in
            --sdk-root) sdk_root="${2:-}"; shift 2 ;;
            --preset) preset="${2:-}"; shift 2 ;;
            --help|-h) usage; return 0 ;;
            *) die "Unknown doctor option: $arg" ;;
        esac
    done
    preset_python_version "$preset" >/dev/null

    local failed=0
    echo "== Orbbec Ego environment diagnosis =="
    echo "Architecture: $(uname -m)"
    if [[ "$(uname -m)" != "x86_64" ]]; then
        warn "The validated host architecture is x86_64."
    fi
    if [[ -r /etc/os-release ]]; then
        . /etc/os-release
        echo "OS: ${PRETTY_NAME:-unknown}"
    fi
    require_command cmake "Install it with: sudo apt update && sudo apt install -y cmake" || failed=1
    require_command c++ "Install it with: sudo apt update && sudo apt install -y build-essential" || failed=1
    require_command python3 "Install it with: sudo apt update && sudo apt install -y python3" || failed=1
    require_command uv "Install uv before configuring Isaac Teleop." || failed=1
    require_command ffmpeg "Install it with: sudo apt update && sudo apt install -y ffmpeg" || failed=1
    require_command ffprobe "Install it with: sudo apt update && sudo apt install -y ffmpeg" || failed=1
    if ! require_command patchelf "Install it with: sudo apt update && sudo apt install -y patchelf"; then
        warn "CloudXR packaging can retain a host OpenSSL dependency without patchelf."
    fi

    if [[ -n "$sdk_root" ]]; then
        if validate_sdk_root "$sdk_root"; then
            echo "OrbbecSDK: $sdk_root"
            if [[ -x "$sdk_root/shared/install_udev_rules.sh" ]]; then
                echo "udev rules installer: sudo $sdk_root/shared/install_udev_rules.sh"
            else
                warn "Could not find this SDK release's shared/install_udev_rules.sh. Consult its package documentation."
            fi
        fi
    else
        warn "No SDK root supplied. Build requires --sdk-root PATH or ORBBEC_SDK_ROOT."
        failed=1
    fi

    if command -v pkg-config >/dev/null 2>&1; then
        local preview_package
        for preview_package in sdl2 libavcodec libavutil libswscale; do
            if ! pkg-config --exists "$preview_package"; then
                warn "Optional SDL preview dependency '$preview_package' is missing. Install libsdl2-dev libavcodec-dev libavutil-dev libswscale-dev."
            fi
        done
    else
        warn "pkg-config is missing; SDL preview dependencies cannot be checked."
    fi

    local plugin=""
    if plugin="$(resolve_plugin "$preset" "" 2>/dev/null)"; then
        echo "Plugin: $plugin"
    else
        warn "Plugin is not built for $preset yet. Run: $SCRIPT_DIR/orbbec_ego.sh build --sdk-root PATH"
    fi

    if command -v lsusb >/dev/null 2>&1; then
        local usb_line bus device node
        usb_line="$(lsusb -d 2bc5: 2>/dev/null || true)"
        if [[ -z "$usb_line" ]]; then
            warn "No Orbbec USB device found. Connect the camera before capabilities or record."
        else
            echo "Detected Orbbec USB device(s):"
            echo "$usb_line"
            while IFS= read -r usb_line; do
                bus="$(awk '{print $2}' <<< "$usb_line")"
                device="$(awk '{gsub(/:/, "", $4); print $4}' <<< "$usb_line")"
                node="/dev/bus/usb/$bus/$device"
                if [[ -r "$node" && -w "$node" ]]; then
                    echo "USB access: OK ($node)"
                else
                    warn "USB access is unavailable for $node. Install this SDK's udev rules, reconnect the camera, then run doctor again."
                fi
            done <<< "$usb_line"
        fi
    else
        warn "lsusb is unavailable; install usbutils to check camera discovery."
    fi

    if (( failed )); then
        return 1
    fi
    echo "Doctor completed. Hardware and preview warnings above are actionable but do not block a source build."
}

command_build() {
    local sdk_root="${ORBBEC_SDK_ROOT:-}"
    local preset="$DEFAULT_PRESET"
    local jobs=""
    local clean=0
    local install_prefix=""
    while (( $# )); do
        case "$1" in
            --sdk-root) sdk_root="${2:-}"; shift 2 ;;
            --preset) preset="${2:-}"; shift 2 ;;
            --jobs) jobs="${2:-}"; shift 2 ;;
            --clean) clean=1; shift ;;
            --install-prefix) install_prefix="${2:-}"; shift 2 ;;
            --help|-h) usage; return 0 ;;
            *) die "Unknown build option: $1" ;;
        esac
    done
    [[ -f "$SOURCE_ROOT/CMakePresets.json" ]] || die "The build command is only available from a source checkout."
    preset_python_version "$preset" >/dev/null
    validate_sdk_root "$sdk_root"
    local build_dir
    build_dir="$(build_dir_for_preset "$preset")"
    if (( clean )); then
        echo "Removing generated build directory: $build_dir"
        cmake -E rm -rf "$build_dir"
    fi
    (
        cd "$SOURCE_ROOT"
        cmake --preset "$preset" -DBUILD_VIZ=OFF -DBUILD_PLUGIN_ORBBEC_CAMERA=ON -DORBBEC_SDK_ROOT="$sdk_root"
        local build_args=(--build "$build_dir" --target camera_plugin_orbbec orbbec_mcap_export_media)
        if [[ -n "$jobs" ]]; then
            [[ "$jobs" =~ ^[1-9][0-9]*$ ]] || die "--jobs must be a positive integer."
            build_args+=(--parallel "$jobs")
        else
            build_args+=(--parallel)
        fi
        cmake "${build_args[@]}"
        if [[ -n "$install_prefix" ]]; then
            cmake --install "$build_dir" --prefix "$install_prefix"
        fi
    )
    echo "Build completed."
    echo "Plugin: $build_dir/src/plugins/orbbec/app/camera_plugin_orbbec"
    echo "Next: $SCRIPT_DIR/orbbec_ego.sh capabilities --preset $preset"
}

command_capabilities() {
    local preset="$DEFAULT_PRESET"
    local plugin_path=""
    while (( $# )); do
        case "$1" in
            --preset) preset="${2:-}"; shift 2 ;;
            --plugin) plugin_path="${2:-}"; shift 2 ;;
            --help|-h) usage; return 0 ;;
            *) die "Unknown capabilities option: $1" ;;
        esac
    done
    preset_python_version "$preset" >/dev/null
    local plugin
    plugin="$(resolve_plugin "$preset" "$plugin_path")"
    "$plugin" --list-capabilities
}

record_usage_error() {
    die "record option error: $*. Run '$SCRIPT_DIR/orbbec_ego.sh record --help' for usage."
}

stream_extension() {
    case "$1" in
        mjpg) echo "mjpg" ;;
        h264) echo "h264" ;;
        h265) echo "h265" ;;
        *) die "Unsupported format '$1'." ;;
    esac
}

command_record() {
    local preset="$DEFAULT_PRESET"
    local plugin_path=""
    local duration=""
    local run_dir=""
    local format="h264"
    local width=1600
    local height=1300
    local fps=30
    local device_uid=""
    local request_imu=1
    local request_audio=1
    local preview=0
    local media_mode="metadata-only"
    local keep_sidecars=0
    local -a passthrough=()
    while (( $# )); do
        case "$1" in
            --) shift; passthrough=("$@"); break ;;
            --duration) duration="${2:-}"; shift 2 ;;
            --output) run_dir="${2:-}"; shift 2 ;;
            --format) format="${2:-}"; shift 2 ;;
            --width) width="${2:-}"; shift 2 ;;
            --height) height="${2:-}"; shift 2 ;;
            --fps) fps="${2:-}"; shift 2 ;;
            --device-uid) device_uid="${2:-}"; shift 2 ;;
            --no-imu) request_imu=0; shift ;;
            --no-audio) request_audio=0; shift ;;
            --preview) preview=1; shift ;;
            --mcap-media) media_mode="${2:-}"; shift 2 ;;
            --keep-media-sidecars) keep_sidecars=1; shift ;;
            --preset) preset="${2:-}"; shift 2 ;;
            --plugin) plugin_path="${2:-}"; shift 2 ;;
            --help|-h) usage; return 0 ;;
            *) record_usage_error "unknown option '$1'" ;;
        esac
    done
    preset_python_version "$preset" >/dev/null
    [[ "$format" == "mjpg" || "$format" == "h264" || "$format" == "h265" ]] || record_usage_error "--format must be mjpg, h264, or h265"
    [[ "$media_mode" == "metadata-only" || "$media_mode" == "embedded" ]] || record_usage_error "--mcap-media must be metadata-only or embedded"
    [[ "$width" =~ ^[1-9][0-9]*$ && "$height" =~ ^[1-9][0-9]*$ && "$fps" =~ ^[1-9][0-9]*$ ]] || record_usage_error "width, height, and fps must be positive integers"
    if [[ -n "$duration" ]]; then
        [[ "$duration" =~ ^[1-9][0-9]*$ ]] || record_usage_error "--duration must be a positive integer"
    fi
    if (( keep_sidecars )) && [[ "$media_mode" == "metadata-only" ]]; then
        record_usage_error "--keep-media-sidecars is only valid with embedded media"
    fi

    local plugin
    plugin="$(resolve_plugin "$preset" "$plugin_path")"
    local output_base="$SOURCE_ROOT"
    [[ -f "$SOURCE_ROOT/CMakePresets.json" ]] || output_base="$PWD"
    if [[ -z "$run_dir" ]]; then
        run_dir="$output_base/recordings/orbbec_ego_$(date +%Y%m%d_%H%M%S)"
    elif [[ "$run_dir" != /* ]]; then
        run_dir="$PWD/$run_dir"
    fi
    [[ ! -e "$run_dir" ]] || die "Output directory already exists: $run_dir"
    mkdir -p "$run_dir/logs"
    if [[ "$media_mode" == "metadata-only" ]] || (( keep_sidecars )); then
        mkdir -p "$run_dir/raw"
    fi

    local capabilities_file="$run_dir/capabilities.txt"
    echo "Inspecting connected device before recording..."
    "$plugin" --list-capabilities | tee "$capabilities_file"
    grep -q '^Sensor LeftColor$' "$capabilities_file" || die "Connected device has no ColorLeft sensor."
    grep -q '^Sensor RightColor$' "$capabilities_file" || die "Connected device has no ColorRight sensor."

    local enable_imu=0
    local enable_audio=0
    if (( request_imu )); then
        if grep -q '^Sensor Accel$' "$capabilities_file" && grep -q '^Sensor Gyro$' "$capabilities_file"; then
            enable_imu=1
        else
            warn "Accel/Gyro are unavailable; continuing without IMU. Use --no-imu to silence this warning."
        fi
    fi
    if (( request_audio )); then
        if grep -q '^Sensor Audio$' "$capabilities_file"; then
            enable_audio=1
        else
            warn "Audio is unavailable; continuing without audio. Use --no-audio to silence this warning."
        fi
    fi

    local extension
    extension="$(stream_extension "$format")"
    local -a plugin_args=(
        "--mcap-filename=$run_dir/metadata.mcap"
        "--mcap-media=$media_mode"
        "--calibration-output=$run_dir/calibration.json"
    )
    if [[ "$media_mode" == "metadata-only" ]] || (( keep_sidecars )); then
        plugin_args+=(
            "--add-stream=camera=ColorLeft,output=$run_dir/raw/ColorLeft.$extension,format=$format,width=$width,height=$height,fps=$fps"
            "--add-stream=camera=ColorRight,output=$run_dir/raw/ColorRight.$extension,format=$format,width=$width,height=$height,fps=$fps"
        )
    else
        plugin_args+=(
            "--add-stream=camera=ColorLeft,format=$format,width=$width,height=$height,fps=$fps"
            "--add-stream=camera=ColorRight,format=$format,width=$width,height=$height,fps=$fps"
        )
    fi
    [[ -n "$device_uid" ]] && plugin_args+=("--device-uid=$device_uid")
    (( preview )) && plugin_args+=(--preview)
    (( enable_imu )) && plugin_args+=(--enable-imu --imu-rate=1000)
    if (( enable_audio )); then
        if [[ "$media_mode" == "metadata-only" ]] || (( keep_sidecars )); then
            plugin_args+=("--audio-output=$run_dir/Audio.wav")
        else
            plugin_args+=(--enable-audio)
        fi
    fi
    (( keep_sidecars )) && plugin_args+=(--keep-media-sidecars)
    plugin_args+=("${passthrough[@]}")

    echo "Recording directory: $run_dir"
    echo "Stop with Ctrl-C once; the plugin will finalize WAV and MCAP files."
    local capture_status
    local -a pipeline_statuses=()
    set +e
    if [[ -n "$duration" ]]; then
        timeout -s INT "$duration" "$plugin" "${plugin_args[@]}" 2>&1 | tee "$run_dir/logs/capture.log"
    else
        "$plugin" "${plugin_args[@]}" 2>&1 | tee "$run_dir/logs/capture.log"
    fi
    pipeline_statuses=("${PIPESTATUS[@]}")
    capture_status=${pipeline_statuses[0]}
    [[ "${pipeline_statuses[1]}" -eq 0 ]] || die "Unable to write capture log: $run_dir/logs/capture.log"
    set -e
    if [[ "$capture_status" -ne 0 && "$capture_status" -ne 124 ]]; then
        die "Capture failed with status $capture_status. See $run_dir/logs/capture.log"
    fi
    if [[ "$capture_status" -eq 124 ]]; then
        echo "Timed capture ended by intentional SIGINT after $duration seconds."
    fi
    local -a verify_args=("$run_dir" --preset "$preset" --plugin "$plugin" --media-mode "$media_mode")
    (( enable_imu )) && verify_args+=(--expect-imu)
    (( enable_audio )) && verify_args+=(--expect-audio)
    command_verify "${verify_args[@]}"
}

find_media_file() {
    local directory="$1"
    local stream="$2"
    local candidate
    for candidate in "$directory/$stream.h264" "$directory/$stream.h265" "$directory/$stream.mjpg"; do
        if [[ -s "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

command_verify() {
    local run_dir="${1:-}"
    shift || true
    [[ -n "$run_dir" ]] || die "verify requires a RUN_DIRECTORY"
    [[ -d "$run_dir" ]] || die "Run directory does not exist: $run_dir"
    local preset="$DEFAULT_PRESET"
    local plugin_path=""
    local expected_mode=""
    local expect_imu=0
    local expect_audio=0
    while (( $# )); do
        case "$1" in
            --preset) preset="${2:-}"; shift 2 ;;
            --plugin) plugin_path="${2:-}"; shift 2 ;;
            --media-mode) expected_mode="${2:-}"; shift 2 ;;
            --expect-imu) expect_imu=1; shift ;;
            --expect-audio) expect_audio=1; shift ;;
            --help|-h) usage; return 0 ;;
            *) die "Unknown verify option: $1" ;;
        esac
    done
    preset_python_version "$preset" >/dev/null
    run_dir="$(cd "$run_dir" && pwd)"
    local mcap="$run_dir/metadata.mcap"
    [[ -s "$mcap" ]] || die "Missing or empty MCAP: $mcap"
    [[ ! -e "$mcap.partial" ]] || die "Incomplete capture: found $mcap.partial"
    require_command ffmpeg "Install it with: sudo apt update && sudo apt install -y ffmpeg" || exit 1
    require_command ffprobe "Install it with: sudo apt update && sudo apt install -y ffmpeg" || exit 1
    require_command python3 "Install Python 3 and the standard MCAP reader: python3 -m pip install --user mcap" || exit 1
    python3 -c 'from mcap.reader import make_reader' 2>/dev/null || die "Python MCAP reader is missing. Install it with: python3 -m pip install --user mcap"

    local mode="$expected_mode"
    if [[ -z "$mode" ]]; then
        mode="$(python3 - "$mcap" <<'PY'
import sys
from mcap.reader import make_reader
topics = set()
with open(sys.argv[1], "rb") as stream:
    for _, channel, _ in make_reader(stream).iter_messages():
        topics.add(channel.topic)
print("embedded" if any(topic.startswith("orbbec_media/") for topic in topics) else "metadata-only")
PY
        )"
    fi
    [[ "$mode" == "metadata-only" || "$mode" == "embedded" ]] || die "Unknown MCAP media mode '$mode'"

    local -a topic_check_args=("$mcap" "$mode")
    (( expect_imu )) && topic_check_args+=(--expect-imu)
    (( expect_audio )) && topic_check_args+=(--expect-audio)
    python3 - "${topic_check_args[@]}" <<'PY'
from collections import Counter
import sys
from mcap.reader import make_reader

path, mode = sys.argv[1:3]
counts = Counter()
with open(path, "rb") as stream:
    for _schema, channel, _message in make_reader(stream).iter_messages():
        counts[channel.topic] += 1
required = [
    "orbbec_metadata/ColorLeft", "orbbec_metadata/ColorRight",
    "orbbec_calibration/Calibration", "orbbec_device/DeviceState",
]
if mode == "embedded":
    required += ["orbbec_media/ColorLeft", "orbbec_media/ColorRight"]
if "--expect-imu" in sys.argv:
    required += ["orbbec_imu/Accel", "orbbec_imu/Gyro"]
if "--expect-audio" in sys.argv:
    required += ["orbbec_audio/Audio"]
missing = [topic for topic in required if counts[topic] == 0]
for topic in sorted(counts):
    print(f"  {topic}: {counts[topic]}")
if missing:
    raise SystemExit(f"Missing or empty required MCAP topics: {missing}")
print("MCAP Footer and required topics: OK")
PY

    local media_dir="$run_dir/raw"
    local temporary_export=""
    if [[ "$mode" != "metadata-only" && ! -d "$media_dir" ]]; then
        temporary_export="$(mktemp -d "$run_dir/.verify_export.XXXXXX")"
        trap '[[ -n "${temporary_export:-}" ]] && rm -rf "$temporary_export"' RETURN
        "$(resolve_exporter "$preset")" "$mcap" "$temporary_export"
        media_dir="$temporary_export"
    fi
    local left right
    left="$(find_media_file "$media_dir" ColorLeft)" || die "Could not find exported ColorLeft media in $media_dir"
    right="$(find_media_file "$media_dir" ColorRight)" || die "Could not find exported ColorRight media in $media_dir"
    local decoder_args=()
    [[ "$left" == *.mjpg ]] && decoder_args=(-f mjpeg)
    ffmpeg -v error "${decoder_args[@]}" -i "$left" -f null -
    decoder_args=()
    [[ "$right" == *.mjpg ]] && decoder_args=(-f mjpeg)
    ffmpeg -v error "${decoder_args[@]}" -i "$right" -f null -
    local wav="$run_dir/Audio.wav"
    [[ -s "$wav" ]] || wav="$media_dir/Audio.wav"
    if [[ -s "$wav" ]]; then
        ffprobe -v error -show_entries stream=codec_name,sample_rate,channels,bits_per_sample -of default=noprint_wrappers=1 "$wav"
    else
        warn "No WAV sidecar exists. This is expected only when audio was unavailable, disabled, or embedded without sidecars."
    fi
    echo "Verification passed: $run_dir"
    echo "Delivery file: $mcap"
}

main() {
    local command="${1:-}"
    [[ -n "$command" ]] || { usage; return 1; }
    shift
    case "$command" in
        doctor) command_doctor "$@" ;;
        build) command_build "$@" ;;
        capabilities) command_capabilities "$@" ;;
        record) command_record "$@" ;;
        verify) command_verify "$@" ;;
        --help|-h|help) usage ;;
        *) die "Unknown command '$command'." ;;
    esac
}

main "$@"
