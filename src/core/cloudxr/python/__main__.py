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
    require_adb_on_path,
)
from isaacteleop.cloudxr.oob_teleop_env import (
    print_oob_hub_startup_banner,
    resolve_lan_host_for_oob,
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
            "Enable OOB teleop control hub and open the teleop page on the headset via USB adb. "
            "The headset must be connected via USB cable (for adb) and on WiFi (for streaming). "
            'See docs: "Out-of-band teleop control".'
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Launch the CloudXR runtime and WSS proxy, then block until interrupted."""
    args = _parse_args()

    if args.setup_oob:
        require_adb_on_path()
        resolve_lan_host_for_oob()
        assert_exactly_one_adb_device()

    with CloudXRLauncher(
        install_dir=args.cloudxr_install_dir,
        env_config=args.cloudxr_env_config,
        accept_eula=args.accept_eula,
        setup_oob=args.setup_oob,
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
