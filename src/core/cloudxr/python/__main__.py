# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for python -m isaacteleop.cloudxr. Runs CloudXR runtime and WSS proxy; main process winds both down on exit."""

import argparse
import os
import signal
import sys
import time

from isaacteleop import __version__ as isaacteleop_version
from isaacteleop.cloudxr.env_config import get_env_config
from isaacteleop.cloudxr.launcher import CloudXRLauncher
from isaacteleop.cloudxr.runtime import latest_runtime_log, runtime_version
from isaacteleop.cloudxr.oob_teleop_adb import (
    OobAdbError,
    assert_exactly_one_adb_device,
    assert_headset_awake,
    require_adb_on_path,
    require_coturn_available,
    require_headset_non_loopback_network,
)
from isaacteleop.cloudxr.oob_teleop_env import (
    USB_HOST,
    WSS_PROXY_DEFAULT_PORT,
    oob_progress,
    print_host_preflight_warnings,
    print_oob_hub_startup_banner,
    resolve_lan_host_for_oob,
    usb_backend_port,
    usb_turn_port,
    usb_ui_port,
)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the CloudXR runtime entry point."""
    parser = argparse.ArgumentParser(description="CloudXR runtime and WSS proxy")
    parser.add_argument(
        "--cloudxr-install-dir",
        type=str,
        default=os.path.expanduser("~/.cloudxr"),
        metavar="PATH",
        help="CloudXR install directory (default: ~/.cloudxr)",
    )
    parser.add_argument(
        "--cloudxr-env-config",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional env file (KEY=value per line) to override default CloudXR env vars",
    )
    parser.add_argument(
        "--accept-eula",
        action="store_true",
        help="Accept the NVIDIA CloudXR EULA non-interactively (e.g. for CI or containers).",
    )
    parser.add_argument(
        "--setup-oob",
        action="store_true",
        default=False,
        help=(
            "Enable OOB teleop control hub, open the teleop page on the headset via USB adb, "
            "and auto-click CONNECT via CDP (Chrome DevTools Protocol). "
            "The headset must be connected via USB cable (for adb) and on WiFi (for streaming). "
            'See docs: "Out-of-band teleop control".'
        ),
    )
    parser.add_argument(
        "--usb-local",
        action="store_true",
        default=False,
        help=(
            "Route teleop traffic over the USB cable on headset loopback "
            "(127.0.0.1) via adb reverse.  Requires --setup-oob.  Orchestrates "
            "adb reverse for WSS proxy "
            f"({WSS_PROXY_DEFAULT_PORT}/tcp), CloudXR backend "
            f"({usb_backend_port()}/tcp; override via USB_BACKEND_PORT env), "
            f"coturn ({usb_turn_port()}/tcp; override via USB_TURN_PORT env), "
            f"and HTTPS static WebXR UI on port {usb_ui_port()} "
            "(override via USB_UI_PORT env).  Files live under "
            "TELEOP_WEB_CLIENT_STATIC_DIR or ~/.cloudxr/static-client; missing "
            "index.html / bundle.js are downloaded from nvidia.github.io/IsaacTeleop/client/.  "
            "The launcher serves them with the same PEM as the WSS proxy.  "
            "Requirements: `coturn`, `adb` on PATH.  WebRTC ICE still needs a "
            "non-loopback interface on the headset (WiFi stays connected)."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Launch the CloudXR runtime and WSS proxy, then block until interrupted."""
    args = _parse_args()

    if args.usb_local and not args.setup_oob:
        print(
            "error: --usb-local requires --setup-oob",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.setup_oob:
        oob_progress(
            "setup-oob",
            "preflight: checking adb on PATH, single headset connected, "
            "headset awake"
            + (
                ", coturn installed, headset has non-loopback IP"
                if args.usb_local
                else ""
            )
            + " ...",
        )
        require_adb_on_path()
        if not args.usb_local:
            resolve_lan_host_for_oob()
        else:
            # Fail fast with clear errors instead of letting the headset
            # silently time out on WebRTC ICE later.
            try:
                require_coturn_available()
            except OobAdbError as exc:
                print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
                raise SystemExit(1) from exc
        assert_exactly_one_adb_device()
        assert_headset_awake()
        if args.usb_local:
            # adb must be usable (just asserted) before we probe the headset.
            try:
                require_headset_non_loopback_network()
            except OobAdbError as exc:
                print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
                raise SystemExit(1) from exc
        print_host_preflight_warnings(usb_local=args.usb_local)
        oob_progress("setup-oob", "preflight OK — starting CloudXR runtime + WSS proxy")

    with CloudXRLauncher(
        install_dir=args.cloudxr_install_dir,
        env_config=args.cloudxr_env_config,
        accept_eula=args.accept_eula,
        setup_oob=args.setup_oob,
        usb_local=args.usb_local,
    ) as launcher:
        cxr_ver = runtime_version()
        print(
            f"Running Isaac Teleop \033[36m{isaacteleop_version}\033[0m, CloudXR Runtime \033[36m{cxr_ver}\033[0m"
        )

        env_cfg = get_env_config()
        logs_dir_path = env_cfg.ensure_logs_dir()
        cxr_log = latest_runtime_log() or logs_dir_path
        print(
            f"CloudXR runtime:   \033[36mrunning\033[0m, log file: \033[90m{cxr_log}\033[0m"
        )
        wss_log = launcher.wss_log_path
        print(
            f"CloudXR WSS proxy: \033[36mrunning\033[0m, log file: \033[90m{wss_log}\033[0m"
        )
        if args.setup_oob:
            if args.usb_local:
                print(
                    "        oob:       \033[32menabled\033[0m  (hub + USB-local: adb reverse + coturn)"
                )
                print_oob_hub_startup_banner(lan_host=USB_HOST, usb_local=True)
            else:
                print(
                    "        oob:       \033[32menabled\033[0m  (hub + USB adb automation — see OOB TELEOP block)"
                )
                print_oob_hub_startup_banner(lan_host=resolve_lan_host_for_oob())
        print(
            f"Activate CloudXR environment in another terminal: \033[1;32msource {env_cfg.env_filepath()}\033[0m"
        )
        print("\033[33mKeep this terminal open, Ctrl+C to terminate.\033[0m")

        stop = False

        def on_signal(sig, frame):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)

        while not stop:
            launcher.health_check()
            time.sleep(0.1)

    print("Stopped.")


if __name__ == "__main__":
    try:
        main()
    except OobAdbError as e:
        print("", file=sys.stderr)
        print(str(e), file=sys.stderr)
        print("", file=sys.stderr)
        raise SystemExit(1) from None
