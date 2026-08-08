# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CLI for the CloudXR service: run it, or manage its systemd user service."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from ._service import CloudXRService


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the flags that shape a running service.

    Shared by ``run`` and ``install``: whatever ``install`` accepts here it
    renders into the unit's ``ExecStart``.
    """
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
            "(127.0.0.1) via adb reverse.  Requires --setup-oob.  Requires "
            "`coturn` and `adb` on PATH.  Implies --host-client."
        ),
    )
    parser.add_argument(
        "--host-client",
        action="store_true",
        default=False,
        help=(
            "Serve the web client at /client/ on the WSS proxy port (default 48322), "
            "fetched once from the matching versioned release into "
            "TELEOP_WEB_CLIENT_STATIC_DIR or ~/.cloudxr/static-client."
        ),
    )


def _run_flags(args: argparse.Namespace) -> list[str]:
    """Re-serialise the run flags in *args* that differ from their defaults.

    ``install`` bakes these into ``ExecStart``.  ``--accept-eula`` is not among
    them: acceptance is recorded as a marker file at install time, in the
    process where the operator actually consented.
    """
    flags: list[str] = []
    if args.cloudxr_install_dir != os.path.expanduser("~/.cloudxr"):
        flags += ["--cloudxr-install-dir", args.cloudxr_install_dir]
    if args.cloudxr_env_config:
        flags += ["--cloudxr-env-config", args.cloudxr_env_config]
    for name in ("setup_oob", "usb_local", "host_client"):
        if getattr(args, name):
            flags.append("--" + name.replace("_", "-"))
    return flags


def _fail(message: str) -> None:
    """Print *message* in red on stderr and exit 1."""
    print(f"\n\033[31m{message}\033[0m\n", file=sys.stderr)
    raise SystemExit(1)


def _oob_preflight(args: argparse.Namespace) -> str | None:
    """Check adb/coturn/network prerequisites; return the resolved LAN host.

    Valid flag combinations:

    ==============================  ==================================================
    (none)                          headset navigates to the GitHub Pages URL over WiFi
    ``--host-client``               client served at ``https://<lan>:<port>/client/``
    ``--setup-oob``                 OOB hub + CDP automation; GitHub Pages URL
    ``--setup-oob --host-client``   OOB hub + CDP; client on the WSS proxy
    ``--setup-oob --usb-local``     OOB hub + CDP; adb-reverse + coturn + loopback HTTPS
    ==============================  ==================================================
    """
    from ..oob_teleop_adb import (  # noqa: PLC0415
        OobAdbError,
        assert_exactly_one_adb_device,
        assert_headset_awake,
        clear_headset_browser_cache,
        require_adb_on_path,
        require_coturn_available,
        require_headset_non_loopback_network,
        require_turn_port_free,
    )
    from ..oob_teleop_env import (  # noqa: PLC0415
        oob_progress,
        print_host_preflight_warnings,
        resolve_lan_host_for_oob,
        usb_turn_port,
    )

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
            _fail(str(exc))
        assert_exactly_one_adb_device()
        assert_headset_awake()
        try:
            require_headset_non_loopback_network()
        except OobAdbError as exc:
            _fail(str(exc))
        try:
            print_host_preflight_warnings(usb_local=True)
        except RuntimeError as exc:
            _fail(str(exc))
        oob_progress("usb-local", "preflight OK")
        return None

    if not args.setup_oob:
        return None

    # TELEOP_OOB_HUB_ONLY skips every adb step — the hub starts, but the
    # operator opens the teleop page on the headset themselves.
    hub_only = bool(os.getenv("TELEOP_OOB_HUB_ONLY"))
    if hub_only:
        oob_progress(
            "setup-oob", "hub-only mode (TELEOP_OOB_HUB_ONLY) — skipping adb preflight"
        )
    else:
        oob_progress("setup-oob", "preflight: adb, single headset, awake ...")
        require_adb_on_path()
    lan_host = resolve_lan_host_for_oob()
    if not hub_only:
        assert_exactly_one_adb_device()
        assert_headset_awake()
    try:
        print_host_preflight_warnings(usb_local=False)
    except RuntimeError as exc:
        _fail(str(exc))
    oob_progress("setup-oob", "preflight OK")
    return lan_host


def _print_startup_banner(
    args: argparse.Namespace, service: CloudXRService, oob_lan_host: str | None
) -> None:
    """Print the operator-facing summary once the service is up."""
    from isaacteleop import __version__ as isaacteleop_version  # noqa: PLC0415

    from ..env_config import get_env_config  # noqa: PLC0415
    from ..oob_teleop_env import (  # noqa: PLC0415
        USB_HOST,
        guess_lan_ipv4,
        print_oob_hub_startup_banner,
        usb_ui_port,
        versioned_web_client_url,
        wss_proxy_port,
    )
    from ..runtime import latest_runtime_log, runtime_version  # noqa: PLC0415

    print(
        f"Running Isaac Teleop \033[36m{isaacteleop_version}\033[0m, "
        f"CloudXR Runtime \033[36m{runtime_version()}\033[0m"
    )

    env_cfg = get_env_config()
    logs_dir_path = env_cfg.ensure_logs_dir()
    cxr_log = latest_runtime_log() or logs_dir_path
    print(
        f"CloudXR runtime:   \033[36mrunning\033[0m, log file: \033[90m{cxr_log}\033[0m"
    )
    print(
        f"CloudXR WSS proxy: \033[36mrunning\033[0m, "
        f"log file: \033[90m{service.wss_log_path}\033[0m"
    )
    # A profile that does not match the connecting device is the usual cause of
    # XR_ERROR_FORM_FACTOR_UNAVAILABLE (-35) in clients.
    profile = env_cfg.resolved("NV_DEVICE_PROFILE")
    print(
        f"device profile:    \033[36m{profile}\033[0m  \033[90m(NV_DEVICE_PROFILE)\033[0m"
    )

    if args.usb_local:
        hosted_client_url = f"https://127.0.0.1:{usb_ui_port()}/"
    elif args.host_client:
        hosted_client_url = (
            f"https://{guess_lan_ipv4() or 'localhost'}:{wss_proxy_port()}/client/"
        )
    else:
        hosted_client_url = None

    if args.setup_oob:
        if args.usb_local:
            print(
                "        oob:       \033[32menabled\033[0m  "
                "(hub + USB-local: adb reverse + coturn)"
            )
            print_oob_hub_startup_banner(lan_host=USB_HOST, usb_local=True)
        else:
            suffix = " + host-client" if args.host_client else ""
            print(
                f"        oob:       \033[32menabled\033[0m  (hub + USB adb "
                f"automation{suffix} — see OOB TELEOP block)"
            )
            print_oob_hub_startup_banner(
                lan_host=oob_lan_host, web_client_base=hosted_client_url
            )
    elif hosted_client_url is not None:
        label = "USB-local" if args.usb_local else "hosted locally"
        print(
            f"web client:        \033[36m{hosted_client_url}\033[0m  "
            f"\033[90m({label} — open on your headset or browser)\033[0m"
        )
    else:
        print(
            f"web client:        \033[36m{versioned_web_client_url(isaacteleop_version)}\033[0m"
        )

    print(
        "Activate CloudXR environment in another terminal: "
        f"\033[1;32msource {env_cfg.env_filepath()}\033[0m"
    )
    print("\033[33mKeep this terminal open, Ctrl+C to terminate.\033[0m")


def _cmd_run(args: argparse.Namespace) -> int:
    """Run the service in the foreground until interrupted."""
    if args.usb_local and not args.setup_oob:
        _fail("--usb-local requires --setup-oob.")
    if args.usb_local and os.getenv("TELEOP_OOB_HUB_ONLY"):
        _fail(
            "TELEOP_OOB_HUB_ONLY is not compatible with --usb-local "
            "(hub-only mode supports WiFi setup only)."
        )

    oob_lan_host = _oob_preflight(args)

    try:
        service = CloudXRService(
            install_dir=args.cloudxr_install_dir,
            env_config=args.cloudxr_env_config,
            accept_eula=args.accept_eula,
            setup_oob=args.setup_oob,
            usb_local=args.usb_local,
            host_client=args.host_client,
        )
    except RuntimeError as exc:
        # Operator-facing conditions (a live runtime, a rejected EULA); the
        # message is the whole point, so don't bury it in a traceback.
        _fail(str(exc))

    with service:
        _print_startup_banner(args, service, oob_lan_host)

        stop = False

        def on_signal(sig, frame):
            """Set the stop flag on SIGINT/SIGTERM."""
            nonlocal stop
            stop = True

        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)

        while not stop:
            service.health_check()
            time.sleep(0.1)

    print("Stopped.")
    return 0


def _require_systemd(action: str) -> None:
    """Exit with instructions when there is no user systemd to talk to."""
    from .. import systemd  # noqa: PLC0415

    if not systemd.is_available():
        _fail(systemd.unavailable_message(f"Cannot {action}."))


def _cmd_install(args: argparse.Namespace) -> int:
    """Render the systemd user service, then enable and start it."""
    from .. import systemd  # noqa: PLC0415
    from ..runtime import _EULA_URL, _write_eula_marker, eula_marker  # noqa: PLC0415

    _require_systemd("install the service")

    run_dir = os.path.join(os.path.expanduser(args.cloudxr_install_dir), "run")
    marker = eula_marker(run_dir)
    if not os.path.isfile(marker):
        if not args.accept_eula:
            _fail(
                "The NVIDIA CloudXR EULA has not been accepted.  A service "
                "started by systemd has no stdin to prompt on, so accept it "
                "here:\n  python -m isaacteleop.cloudxr.service install "
                "--accept-eula\nReview it first: " + _EULA_URL
            )
        os.makedirs(run_dir, mode=0o700, exist_ok=True)
        _write_eula_marker(marker)
        print(f"Recorded EULA acceptance: {marker}")

    path = systemd.write_unit(_run_flags(args))
    print(f"Wrote {path}")

    if args.now:
        systemd.enable_now()
        print(f"Started {systemd.UNIT_NAME}")
    else:
        print(
            f"Not started (--no-now).  Start it with: systemctl --user start {systemd.UNIT_NAME}"
        )

    print(
        "The service stops at logout unless lingering is enabled:\n  "
        + systemd.linger_hint()
    )
    return 0


def _cmd_uninstall(_args: argparse.Namespace) -> int:
    """Stop, disable, and remove the systemd user service."""
    from .. import systemd  # noqa: PLC0415

    _require_systemd("uninstall the service")
    systemd.disable_now()
    if systemd.remove_unit():
        print(f"Removed {systemd.unit_path()}")
    else:
        print(f"Nothing to remove at {systemd.unit_path()}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    """Show ``systemctl --user status`` for the service."""
    from .. import systemd  # noqa: PLC0415

    _require_systemd("query the service")
    result = systemd.systemctl("status", systemd.UNIT_NAME, "--no-pager", check=False)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def _cmd_logs(args: argparse.Namespace) -> int:
    """Tail the service's journal."""
    from .. import systemd  # noqa: PLC0415

    _require_systemd("read the service journal")
    cmd = ["journalctl", "--user", "-u", systemd.UNIT_NAME, "-n", str(args.lines)]
    if args.follow:
        cmd.append("-f")
    return subprocess.call(cmd)


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``isaacteleop.cloudxr.service`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m isaacteleop.cloudxr.service",
        description="Run the CloudXR service, or manage it as a systemd user service.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = sub.add_parser("run", help="run the service in the foreground")
    _add_run_arguments(run)
    run.set_defaults(func=_cmd_run)

    install = sub.add_parser(
        "install", help="render, enable and start the systemd user service"
    )
    _add_run_arguments(install)
    install.add_argument(
        "--now",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Start the service after installing it (default: true).",
    )
    install.set_defaults(func=_cmd_install)

    uninstall = sub.add_parser("uninstall", help="stop and remove the service")
    uninstall.set_defaults(func=_cmd_uninstall)

    status = sub.add_parser("status", help="show systemctl status for the service")
    status.set_defaults(func=_cmd_status)

    logs = sub.add_parser("logs", help="show the service journal")
    logs.add_argument("-n", "--lines", type=int, default=50, help="lines to show")
    logs.add_argument("-f", "--follow", action="store_true", help="follow the journal")
    logs.set_defaults(func=_cmd_logs)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help()
        return 0
    from ..oob_teleop_adb import OobAdbError  # noqa: PLC0415

    try:
        return args.func(args)
    except OobAdbError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
