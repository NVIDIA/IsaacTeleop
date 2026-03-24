# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for python -m isaacteleop.cloudxr.

Runs CloudXR runtime and WSS proxy by default. Use ``--wss-only`` to run the WSS proxy (and
optional teleop hub) without starting the runtime—for example to exercise the operator UI.
"""

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
from isaacteleop.cloudxr.wss import operator_dashboard_urls, run as wss_run


def _print_operator_dashboard_line() -> None:
    urls = operator_dashboard_urls()
    print(f"        operator:  {urls[0]}")
    for u in urls[1:]:
        print(f"                 {u}  (LAN)")


def _parse_args() -> argparse.Namespace:
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
        "--enable-hub",
        action="store_true",
        default=os.environ.get("TELEOP_CONTROL_HUB", "") in ("1", "true", "yes"),
        help=(
            "Enable the teleop control hub on the WSS proxy port. "
            "Exposes /teleop/v1/ws (WebSocket), /api/teleop/v1/state (HTTP), "
            "and /teleop/ (operator UI). "
            "Also enabled via TELEOP_CONTROL_HUB=1 env var."
        ),
    )
    parser.add_argument(
        "--wss-only",
        action="store_true",
        help=(
            "Do not start the CloudXR runtime; run only the WSS TLS proxy on PROXY_PORT (default 48322). "
            "Logs go to stderr. Combine with --enable-hub to run the teleop hub and operator dashboard "
            "without a live runtime (same HTTP/WebSocket routes as full mode)."
        ),
    )
    return parser.parse_args()


async def _main_async() -> None:
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
        if args.enable_hub:
            print("        hub:       enabled  (teleop control hub active)")
            _print_operator_dashboard_line()
        else:
            print(
                "        hub:       off  (use --enable-hub for operator UI / teleop protocol)"
            )
        print(
            "\033[33mNon-teleop WebSocket paths proxy to the runtime backend, which is not running.\033[0m"
        )
        print("\033[33mCtrl+C to stop.\033[0m")
        await wss_run(log_file_path=None, stop_future=stop, enable_hub=args.enable_hub)
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
        ready = await wait_for_runtime_ready(runtime_proc)
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
        if args.enable_hub:
            print("        hub:       enabled  (teleop control hub active)")
            _print_operator_dashboard_line()

        print(
            f"Activate CloudXR environment in another terminal: \033[1;32msource {env_cfg.env_filepath()}\033[0m"
        )
        print("\033[33mKeep this terminal open, Ctrl+C to terminate.\033[0m")

        await wss_run(
            log_file_path=wss_log_path, stop_future=stop, enable_hub=args.enable_hub
        )
    finally:
        terminate_or_kill_runtime(runtime_proc)

    print("Stopped.")


if __name__ == "__main__":
    asyncio.run(_main_async())
