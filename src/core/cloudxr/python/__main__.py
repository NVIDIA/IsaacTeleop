# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point for python -m isaacteleop.cloudxr. Runs CloudXR runtime and WSS proxy; main process winds both down on exit."""

import argparse
import os
import signal
import subprocess
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
    clear_headset_browser_cache,
    require_adb_on_path,
    require_coturn_available,
    require_headset_non_loopback_network,
    require_turn_port_free,
)
from isaacteleop.cloudxr.oob_teleop_env import (
    USB_HOST,
    WSS_PROXY_DEFAULT_PORT,
    guess_lan_ipv4,
    oob_progress,
    print_host_preflight_warnings,
    print_oob_hub_startup_banner,
    resolve_lan_host_for_oob,
    usb_backend_port,
    usb_turn_port,
    usb_ui_port,
    versioned_web_client_url,
    wss_proxy_port,
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
        "--clean",
        action="store_true",
        default=False,
        help=(
            "Before launching, run `pkill -f 'isaacteleop.cloudxr.runtime'` "
            "to release any stale CloudXR runtime worker subprocess left over "
            "from a previous (crashed or detached) run. The current parent "
            "process is not matched because its argv does not contain "
            "`.runtime`."
        ),
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
            f"and HTTPS static web client on port {usb_ui_port()} "
            "(override via USB_UI_PORT env).  Files live under "
            "TELEOP_WEB_CLIENT_STATIC_DIR or ~/.cloudxr/static-client; missing "
            "index.html / bundle.js are downloaded from the matching versioned "
            "client under nvidia.github.io/IsaacTeleop/client/.  "
            "The launcher serves them with the same PEM as the WSS proxy.  "
            "Requirements: `coturn`, `adb` on PATH.  WebRTC ICE still needs a "
            "non-loopback interface on the headset (WiFi stays connected).  "
            "Implies --host-client (loopback binding)."
        ),
    )
    parser.add_argument(
        "--host-client",
        action="store_true",
        default=False,
        help=(
            "Serve the web client at /client/ on the WSS proxy port (default 48322). "
            "Assets (index.html + bundle.js) are fetched once from the matching "
            "versioned release on nvidia.github.io/IsaacTeleop into "
            "TELEOP_WEB_CLIENT_STATIC_DIR or ~/.cloudxr/static-client.  "
            "No separate port, no build step, no adb required.  "
            "--usb-local implies a separate loopback HTTPS server instead."
        ),
    )
    return parser.parse_args()


def _clear_stale_runtime() -> None:
    # pkill exit codes: 0 = matched & signalled, 1 = no match. Treat both as
    # success; only louder codes (or a missing binary) get a warning so a stale
    # runtime never silently blocks the new launch on the same ports.
    print("\033[36mclear:\033[0m pkill -f 'isaacteleop.cloudxr.runtime'")
    try:
        result = subprocess.run(
            ["pkill", "-f", "isaacteleop.cloudxr.runtime"],
            check=False,
        )
    except FileNotFoundError:
        print(
            "warning: pkill not found on PATH; cannot clear stale runtime",
            file=sys.stderr,
        )
        return
    if result.returncode == 0:
        # Give the OS a brief moment to reap the killed worker and release the
        # listening ports before CloudXRLauncher starts a fresh runtime.
        time.sleep(0.5)
    elif result.returncode != 1:
        print(
            f"warning: pkill exited {result.returncode}; continuing",
            file=sys.stderr,
        )


def main() -> None:
    """Launch the CloudXR runtime and WSS proxy, then block until interrupted."""
    args = _parse_args()

    if args.clean:
        _clear_stale_runtime()

    if args.usb_local and not args.setup_oob:
        print(
            "\n\033[31m--usb-local requires --setup-oob.\033[0m\n",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Valid flag combinations and what they mean:
    #
    #   (none)                        Plain: headset navigates to GitHub Pages URL over WiFi.
    #   --host-client                 Client served at https://<lan>:<wss_port>/client/; no adb/TURN.
    #   --setup-oob                   OOB hub + CDP automation; GitHub Pages URL.
    #   --setup-oob --host-client     OOB hub + CDP; client served at /client/ on the WSS proxy.
    #   --setup-oob --usb-local       OOB hub + CDP; adb-reverse + coturn + loopback HTTPS.

    _oob_lan_host: str | None = None  # resolved once, reused in startup banner
    if args.usb_local:
        oob_progress(
            "usb-local",
            "preflight: adb, single headset, awake, coturn, non-loopback IP ...",
        )
        require_adb_on_path()
        oob_progress("usb-local", "clearing headset browser cache ...")
        cleared = clear_headset_browser_cache(usb_local=True)
        if cleared:
            oob_progress("usb-local", f"cleared cache for {cleared} origin(s)")
        else:
            oob_progress("usb-local", "no cache cleared (browser not running)")
        try:
            require_coturn_available()
            require_turn_port_free(usb_turn_port())
        except OobAdbError as exc:
            print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
            raise SystemExit(1) from exc
        assert_exactly_one_adb_device()
        assert_headset_awake()
        try:
            require_headset_non_loopback_network()
        except OobAdbError as exc:
            print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
            raise SystemExit(1) from exc
        try:
            print_host_preflight_warnings(usb_local=True)
        except RuntimeError as exc:
            print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
            raise SystemExit(1) from exc
        oob_progress("usb-local", "preflight OK")
    elif args.setup_oob:
        # WiFi OOB: resolve LAN host + warn on port/ufw issues.
        oob_progress("setup-oob", "preflight: adb, single headset, awake ...")
        require_adb_on_path()
        _oob_lan_host = resolve_lan_host_for_oob()
        assert_exactly_one_adb_device()
        assert_headset_awake()
        try:
            print_host_preflight_warnings(usb_local=False)
        except RuntimeError as exc:
            print(f"\n\033[31m{exc}\033[0m\n", file=sys.stderr)
            raise SystemExit(1) from exc
        oob_progress("setup-oob", "preflight OK")

    with CloudXRLauncher(
        install_dir=args.cloudxr_install_dir,
        env_config=args.cloudxr_env_config,
        accept_eula=args.accept_eula,
        setup_oob=args.setup_oob,
        usb_local=args.usb_local,
        host_client=args.host_client,
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

        if args.usb_local:
            _hosted_client_url = f"https://127.0.0.1:{usb_ui_port()}/"
        elif args.host_client:
            _lan = guess_lan_ipv4() or "localhost"
            _hosted_client_url = f"https://{_lan}:{wss_proxy_port()}/client/"
        else:
            _hosted_client_url = None

        if args.setup_oob:
            if args.usb_local:
                print(
                    "        oob:       \033[32menabled\033[0m  (hub + USB-local: adb reverse + coturn)"
                )
                print_oob_hub_startup_banner(lan_host=USB_HOST, usb_local=True)
            else:
                oob_suffix = " + host-client" if args.host_client else ""
                print(
                    f"        oob:       \033[32menabled\033[0m  (hub + USB adb automation{oob_suffix} — see OOB TELEOP block)"
                )
                print_oob_hub_startup_banner(
                    lan_host=_oob_lan_host,
                    web_client_base=_hosted_client_url,
                )
        else:
            if _hosted_client_url is not None:
                _label = "USB-local" if args.usb_local else "hosted locally"
                print(
                    f"web client:        \033[36m{_hosted_client_url}\033[0m  "
                    f"\033[90m({_label} — open on your headset or browser)\033[0m"
                )
            else:
                client_url = versioned_web_client_url(isaacteleop_version)
                print(f"web client:        \033[36m{client_url}\033[0m")
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
