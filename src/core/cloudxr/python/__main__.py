# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for python -m isaacteleop.cloudxr. Runs CloudXR runtime and WSS proxy; main process winds both down on exit."""

import argparse
import asyncio
import multiprocessing
import os
import signal
import sys
from datetime import datetime, timezone

from isaacteleop import __version__ as isaacteleop_version
from isaacteleop.cloudxr.env_config import EnvConfig
from isaacteleop.cloudxr.runtime import (
    check_eula,
    latest_runtime_log,
    run as runtime_run,
    runtime_version,
    terminate_or_kill_runtime,
    wait_for_runtime_ready,
)
from isaacteleop.cloudxr.wss import (
    OobAdbError,
    parse_setup_oob_cli,
    print_oob_hub_startup_banner,
    resolve_lan_host_for_oob,
    run as wss_run,
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
        "--wss-only",
        action="store_true",
        help=(
            "Do not start the CloudXR runtime; run only the WSS TLS proxy on PROXY_PORT (default 48322). "
            "Logs go to stderr."
        ),
    )
    parser.add_argument(
        "--setup-oob",
        type=parse_setup_oob_cli,
        default=None,
        metavar="tethered|HOST:PORT",
        help=(
            "Enable OOB teleop control over adb (omit to disable): from this PC, open the teleop page "
            "on the headset while it sits around your neck. "
            "Use `tethered` for USB adb reverse + UDP relay or `HOST:PORT` for wireless adb. "
            'See docs: "Out-of-band teleop control".'
        ),
    )
    return parser.parse_args()


async def _main_async() -> None:
    """Launch the CloudXR runtime and WSS proxy, then block until interrupted."""
    args = _parse_args()
    env_cfg = EnvConfig.from_args(args.cloudxr_install_dir, args.cloudxr_env_config)
    check_eula(accept_eula=args.accept_eula or None)

    stop = asyncio.get_running_loop().create_future()

    def on_signal() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
        except NotImplementedError:
            pass

    if args.wss_only:
        print(
            f"Isaac Teleop \033[36m{isaacteleop_version}\033[0m — WSS proxy only "
            f"(CloudXR runtime \033[33mnot started\033[0m)"
        )
        print("CloudXR WSS proxy: \033[36mrunning\033[0m (logs on stderr)")
        if args.setup_oob is not None:
            print(
                "        oob:       on  (teleop hub runs in this WSS proxy — see OOB TELEOP block)"
            )
            if args.setup_oob == "tethered":
                print_oob_hub_startup_banner(oob_mode="tethered")
            else:
                print_oob_hub_startup_banner(
                    oob_mode="wireless", lan_host=resolve_lan_host_for_oob()
                )
        else:
            print(
                "        oob:       off  (--setup-oob tethered|HOST:PORT for OOB + adb)"
            )
        print(
            "\033[33mNon-teleop WebSocket paths proxy to the runtime backend, which is not running.\033[0m"
        )
        print("\033[33mCtrl+C to stop.\033[0m")
        await wss_run(
            log_file_path=None,
            stop_future=stop,
            setup_oob=args.setup_oob,
        )
        print("Stopped.")
        return

    logs_dir_path = env_cfg.ensure_logs_dir()
    wss_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    wss_log_path = logs_dir_path / f"wss.{wss_ts}.log"

    runtime_proc = multiprocessing.Process(target=runtime_run)
    runtime_proc.start()

    cxr_ver = runtime_version()
    print(
        f"Running Isaac Teleop \033[36m{isaacteleop_version}\033[0m, CloudXR Runtime \033[36m{cxr_ver}\033[0m"
    )

    try:
        ready = await wait_for_runtime_ready(runtime_proc.is_alive)
        if not ready:
            if not runtime_proc.is_alive() and runtime_proc.exitcode != 0:
                sys.exit(
                    runtime_proc.exitcode if runtime_proc.exitcode is not None else 1
                )
            print("CloudXR runtime failed to start, terminating...")
            sys.exit(1)

        print("CloudXR runtime started, make sure load environment variables:")
        print("")
        print("```bash")
        print(f"source {env_cfg.env_filepath()}")
        print("```")
        print("")

        cxr_log = latest_runtime_log() or logs_dir_path
        print(
            f"CloudXR runtime:   \033[36mrunning\033[0m, log file: \033[90m{cxr_log}\033[0m"
        )
        print("CloudXR WSS proxy: \033[36mrunning\033[0m")
        print(f"        logFile:   \033[90m{wss_log_path}\033[0m")
        if args.setup_oob is not None:
            print(
                "        oob:       on  (teleop hub runs in this WSS proxy — see OOB TELEOP block)"
            )
            if args.setup_oob == "tethered":
                print_oob_hub_startup_banner(oob_mode="tethered")
            else:
                print_oob_hub_startup_banner(
                    oob_mode="wireless", lan_host=resolve_lan_host_for_oob()
                )

        print(
            f"Activate CloudXR environment in another terminal: \033[1;32msource {env_cfg.env_filepath()}\033[0m"
        )
        print("\033[33mKeep this terminal open, Ctrl+C to terminate.\033[0m")

        await wss_run(
            log_file_path=wss_log_path,
            stop_future=stop,
            setup_oob=args.setup_oob,
        )
    finally:
        terminate_or_kill_runtime(runtime_proc)

    print("Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(_main_async())
    except OobAdbError as e:
        print("", file=sys.stderr)
        print(str(e), file=sys.stderr)
        print("", file=sys.stderr)
        raise SystemExit(1) from None
