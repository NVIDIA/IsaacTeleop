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

from isaacteleop.cloudxr.env_config import EnvConfig
from isaacteleop.cloudxr.runtime import (
    check_eula,
    run as runtime_run,
    terminate_or_kill_runtime,
    wait_for_runtime_ready,
)
from isaacteleop.cloudxr.wss import run as wss_run


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
    return parser.parse_args()


async def _main_async() -> None:
    args = _parse_args()
    env_cfg = EnvConfig.from_args(args.cloudxr_install_dir, args.cloudxr_env_config)
    check_eula()
    logs_dir_path = env_cfg.ensure_logs_dir()
    wss_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    wss_log_path = logs_dir_path / f"wss.{wss_ts}.log"

    runtime_proc = multiprocessing.Process(target=runtime_run)
    runtime_proc.start()

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

        stop = asyncio.get_running_loop().create_future()

        def on_signal() -> None:
            if not stop.done():
                stop.set_result(None)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, on_signal)

        print("CloudXR WSS proxy: running")
        print(f"        logFile:   {wss_log_path}")

        await wss_run(log_file_path=wss_log_path, stop_future=stop)
    finally:
        terminate_or_kill_runtime(runtime_proc)

    print("Stopped.")


if __name__ == "__main__":
    asyncio.run(_main_async())
