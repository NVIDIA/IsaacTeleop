# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Programmatic access to a running CloudXR runtime and WSS proxy.

:class:`~isaacteleop.cloudxr.service.CloudXRService` owns them; this is the
API embedding applications (e.g. Isaac Lab Teleop) use to reach one, and the
CLI plumbing the examples share.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import warnings
from pathlib import Path

from . import background
from .env_config import DEFAULT_DEVICE_PROFILE, read_exported_env
from .runtime import check_eula, is_runtime_live, latest_wss_log
from .service import CloudXRService

logger = logging.getLogger(__name__)

_STARTED_SERVICE = """\
\033[33mNo CloudXR service was running — started one (pid {pid}).\033[0m
  logs: \033[90m{log}\033[0m
  It outlives this script.  Stop it with:
    \033[1;32mpython -m isaacteleop.cloudxr.service stop\033[0m"""


class CloudXRLauncher:
    """Attaches to the CloudXR runtime and WSS proxy a service is running.

    Owns nothing by default: it attaches to the runtime
    :class:`~isaacteleop.cloudxr.service.CloudXRService` is serving, adopting
    its environment so OpenXR resolves to it, and leaves it running on exit.
    With no service running it starts a detached one — announced, because that
    outlives this process.  ``run_embedded`` is the only way to own a runtime.

    Example::

        with CloudXRLauncher() as launcher:
            # attached to `service start`'s runtime; still running afterwards
            ...
    """

    def __init__(
        self,
        install_dir: str = "~/.cloudxr",
        env_config: str | Path | None = None,
        device_profile: str = DEFAULT_DEVICE_PROFILE,
        accept_eula: bool = False,
        setup_oob: bool = False,
        usb_local: bool = False,
        host_client: bool = False,
        run_embedded: bool = False,
        start_wss_proxy: bool | None = None,
    ) -> None:
        """Attach to the running runtime, or own one when *run_embedded*.

        Args:
            run_embedded: Run a :class:`CloudXRService` inside this process
                instead of starting a detached one.  This process then owns the
                runtime and stops it on exit.  A live runtime still wins: it is
                attached to rather than duplicated.
            start_wss_proxy: Deprecated no-op; the proxy always starts with
                the runtime.

        Every other argument is forwarded to :class:`CloudXRService` and only
        applies when this process owns it.  When attaching they describe a
        runtime that already exists, so a mismatch is reported rather than
        applied.

        Raises:
            RuntimeError: If the runtime fails to start or come up.
        """
        if start_wss_proxy is not None:
            self._warn_start_wss_proxy_deprecated()

        self._run_dir = os.path.join(os.path.expanduser(install_dir), "run")
        self._logs_dir = Path(os.path.expanduser(install_dir)) / "logs"
        self._service: CloudXRService | None = None

        if is_runtime_live(self._run_dir):
            self._attach(device_profile, env_config)
            return

        if not run_embedded:
            self._start_service(
                install_dir,
                env_config,
                device_profile,
                accept_eula,
                setup_oob,
                usb_local,
                host_client,
            )
            self._attach(device_profile, env_config)
            return

        self._service = CloudXRService(
            install_dir=install_dir,
            env_config=env_config,
            device_profile=device_profile,
            accept_eula=accept_eula,
            setup_oob=setup_oob,
            usb_local=usb_local,
            host_client=host_client,
        )

    def _start_service(
        self,
        install_dir: str,
        env_config: str | Path | None,
        device_profile: str,
        accept_eula: bool,
        setup_oob: bool,
        usb_local: bool,
        host_client: bool,
    ) -> None:
        """Start a detached service, then leave it running for the next caller.

        Announced rather than silent: it outlives this process, so a caller who
        did not ask for one still needs to know it is there and how to stop it.
        """
        # Accept here, where a terminal exists: the detached service inherits
        # /dev/null on stdin and could not prompt.
        check_eula(accept_eula=accept_eula or None, run_dir=self._run_dir)

        flags = [
            *(
                ["--cloudxr-install-dir", install_dir]
                if install_dir != "~/.cloudxr"
                else []
            ),
            *(["--cloudxr-env-config", str(env_config)] if env_config else []),
            *(["--setup-oob"] if setup_oob else []),
            *(["--usb-local"] if usb_local else []),
            *(["--host-client"] if host_client else []),
        ]
        # EnvConfig reads NV_DEVICE_PROFILE from the process environment, and
        # an env file still overrides it — so the profile needs no CLI flag.
        extra_env = (
            {"NV_DEVICE_PROFILE": device_profile}
            if device_profile != DEFAULT_DEVICE_PROFILE
            else None
        )
        pid, log = background.start_and_wait(
            flags, self._run_dir, self._logs_dir, extra_env
        )
        print(_STARTED_SERVICE.format(pid=pid, log=log), file=sys.stderr)

    def _attach(self, device_profile: str, env_config: str | Path | None) -> None:
        """Adopt the running runtime's environment and report any mismatch.

        The env file is applied, never re-resolved: resolving it would rewrite
        the file out from under the service that owns it.
        """
        env = read_exported_env(os.path.join(self._run_dir, "cloudxr.env"))
        if not env:
            raise RuntimeError(
                f"A CloudXR runtime is serving {self._run_dir}, but its "
                "environment file is missing or unreadable, so OpenXR cannot "
                "be pointed at it.  Restart the service."
            )
        os.environ.update(env)
        logger.info("Attached to the CloudXR runtime serving %s", self._run_dir)

        # These configure a runtime at start-up; attaching cannot apply them,
        # and a silently ignored device profile is the usual cause of a client
        # failing with XR_ERROR_FORM_FACTOR_UNAVAILABLE (-35).
        running = env.get("NV_DEVICE_PROFILE")
        if running and running != device_profile:
            logger.warning(
                "Attached to a runtime started with NV_DEVICE_PROFILE=%s; the "
                "requested %s is ignored.  Restart the service to change it.",
                running,
                device_profile,
            )
        if env_config is not None:
            logger.warning(
                "env_config=%s is ignored: the runtime this attached to was "
                "started with its own configuration.",
                env_config,
            )

    @property
    def owns_runtime(self) -> bool:
        """Whether this process started the runtime, and will stop it."""
        return self._service is not None

    # TODO(1.7): drop start_wss_proxy, --launch-wss-proxy and this helper.
    @staticmethod
    def _warn_start_wss_proxy_deprecated() -> None:
        """Announce that the ``start_wss_proxy`` no-op is on its way out."""
        message = (
            "start_wss_proxy is deprecated and does nothing; the WSS proxy "
            "always starts with the runtime.  It is removed in Isaac Teleop 1.7."
        )
        warnings.warn(message, DeprecationWarning, stacklevel=3)
        # Python drops DeprecationWarning raised outside __main__, which is
        # every --launch-wss-proxy run, so log it as well.
        logger.warning(message)

    # ------------------------------------------------------------------
    # CLI helpers for embedding applications and examples
    # ------------------------------------------------------------------

    @staticmethod
    def add_cloudxr_install_dir_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-install-dir`` on ``parser`` (default ``~/.cloudxr``)."""
        parser.add_argument(
            "--cloudxr-install-dir",
            type=str,
            default=os.path.expanduser("~/.cloudxr"),
            metavar="PATH",
            help="CloudXR install directory (default: ~/.cloudxr)",
        )

    # TODO(1.7): drop --launch-cloudxr-runtime and this helper.
    @staticmethod
    def add_launch_cloudxr_runtime_argument(parser: argparse.ArgumentParser) -> None:
        """Register the deprecated no-op ``--launch-cloudxr-runtime`` on ``parser``.

        Defaults to ``None`` so an explicit flag is distinguishable from an
        absent one and only the former warns.
        """
        parser.add_argument(
            "--launch-cloudxr-runtime",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Deprecated no-op, removed in 1.7: a running runtime is always "
                "attached to, and one is started only when none is serving the "
                "install dir."
            ),
        )

    # TODO(1.7): drop this helper with the flag.
    @staticmethod
    def _warn_launch_runtime_deprecated() -> None:
        """Announce that the ``--launch-cloudxr-runtime`` no-op is on its way out."""
        message = (
            "--no-launch-cloudxr-runtime is deprecated and does nothing; a "
            "running runtime is attached to automatically.  It is removed in "
            "Isaac Teleop 1.7."
        )
        warnings.warn(message, DeprecationWarning, stacklevel=3)
        logger.warning(message)

    @staticmethod
    def add_cloudxr_device_profile_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-device-profile`` on ``parser`` (default Quest3)."""
        parser.add_argument(
            "--cloudxr-device-profile",
            type=str,
            default=DEFAULT_DEVICE_PROFILE,
            metavar="PROFILE",
            help=(
                "CloudXR NV_DEVICE_PROFILE for the runtime "
                f"(default: {DEFAULT_DEVICE_PROFILE}). "
                "Examples: Quest3, auto-webrtc, auto-native, AppleVisionPro. "
                "Overridden by --cloudxr-env-config or NV_DEVICE_PROFILE in the environment."
            ),
        )

    @staticmethod
    def add_cloudxr_env_config_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--cloudxr-env-config`` on ``parser`` (default: none).

        Points the launcher at a KEY=value env file of CloudXR runtime
        overrides (see the ``env_config`` argument of
        :meth:`CloudXRService.__init__`).
        """
        parser.add_argument(
            "--cloudxr-env-config",
            type=str,
            default=None,
            metavar="PATH",
            help=(
                "Path to a KEY=value env file of CloudXR runtime overrides "
                "(default: none). Reserved keys (XR_RUNTIME_JSON, "
                "NV_CXR_RUNTIME_DIR, ...) are always computed and ignored if set."
            ),
        )

    @staticmethod
    def add_accept_eula_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--accept-eula`` on ``parser`` (default: false).

        When omitted and no acceptance marker exists, the service prompts
        on stdin before starting the runtime.
        """
        parser.add_argument(
            "--accept-eula",
            action="store_true",
            help=(
                "Accept the NVIDIA CloudXR EULA non-interactively "
                "(e.g. for CI or containers)."
            ),
        )

    @staticmethod
    def add_launch_wss_proxy_argument(parser: argparse.ArgumentParser) -> None:
        """Register the deprecated no-op ``--launch-wss-proxy`` on ``parser``.

        Defaults to ``None`` so an explicit flag is distinguishable from an
        absent one and only the former warns.
        """
        parser.add_argument(
            "--launch-wss-proxy",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=(
                "Deprecated no-op, removed in 1.7: the WSS TLS proxy always "
                "starts with the runtime."
            ),
        )

    @staticmethod
    def add_launcher_arguments(parser: argparse.ArgumentParser) -> None:
        """Register CloudXR launcher CLI arguments on ``parser``."""
        CloudXRLauncher.add_cloudxr_install_dir_argument(parser)
        CloudXRLauncher.add_cloudxr_device_profile_argument(parser)
        CloudXRLauncher.add_cloudxr_env_config_argument(parser)
        CloudXRLauncher.add_accept_eula_argument(parser)
        CloudXRLauncher.add_launch_cloudxr_runtime_argument(parser)
        CloudXRLauncher.add_launch_wss_proxy_argument(parser)

    @staticmethod
    def _resolve_install_dir(
        args: argparse.Namespace,
        install_dir: str | None = None,
    ) -> str:
        """Return ``install_dir`` or ``args.cloudxr_install_dir`` when registered."""
        if install_dir is not None:
            return install_dir
        return getattr(args, "cloudxr_install_dir", "~/.cloudxr")

    @staticmethod
    def _resolve_device_profile(
        args: argparse.Namespace,
        device_profile: str | None = None,
    ) -> str:
        """Return ``device_profile`` or ``args.cloudxr_device_profile`` when registered."""
        if device_profile is not None:
            return device_profile
        return getattr(args, "cloudxr_device_profile", DEFAULT_DEVICE_PROFILE)

    @staticmethod
    def _resolve_env_config(
        args: argparse.Namespace,
        env_config: str | Path | None = None,
    ) -> str | Path | None:
        """Return ``env_config`` or ``args.cloudxr_env_config`` when registered."""
        if env_config is not None:
            return env_config
        return getattr(args, "cloudxr_env_config", None)

    @staticmethod
    def _resolve_accept_eula(
        args: argparse.Namespace,
        accept_eula: bool | None = None,
    ) -> bool:
        """Return ``accept_eula`` or ``args.accept_eula`` when registered.

        ``None`` means no override (fall back to ``args``); an explicit ``False``
        disables EULA acceptance even when ``args.accept_eula`` is true.
        """
        if accept_eula is not None:
            return accept_eula
        return bool(getattr(args, "accept_eula", False))

    @staticmethod
    def launch_context(
        args: argparse.Namespace,
        *,
        install_dir: str | None = None,
        env_config: str | Path | None = None,
        device_profile: str | None = None,
        accept_eula: bool | None = None,
        setup_oob: bool = False,
        usb_local: bool = False,
        host_client: bool = False,
        run_embedded: bool = False,
        start_wss_proxy: bool | None = None,
    ) -> CloudXRLauncher:
        """Build a :class:`CloudXRLauncher` from parsed arguments.

        ``install_dir``, ``env_config``, ``device_profile``, and ``accept_eula``
        default to the values registered by :meth:`add_launcher_arguments`
        (``args.cloudxr_install_dir`` etc.); pass an explicit keyword only to
        override what came in on the command line. For ``accept_eula``, pass
        ``False`` to force-disable even when the CLI flag is set.
        ``run_embedded`` is forwarded to :class:`CloudXRLauncher`.
        ``start_wss_proxy`` is a deprecated no-op removed in 1.7.
        """
        if (
            start_wss_proxy is not None
            or getattr(args, "launch_wss_proxy", None) is not None
        ):
            CloudXRLauncher._warn_start_wss_proxy_deprecated()
        if getattr(args, "launch_cloudxr_runtime", None) is not None:
            CloudXRLauncher._warn_launch_runtime_deprecated()
        return CloudXRLauncher(
            install_dir=CloudXRLauncher._resolve_install_dir(args, install_dir),
            env_config=CloudXRLauncher._resolve_env_config(args, env_config),
            device_profile=CloudXRLauncher._resolve_device_profile(
                args, device_profile
            ),
            accept_eula=CloudXRLauncher._resolve_accept_eula(args, accept_eula),
            setup_oob=setup_oob,
            usb_local=usb_local,
            host_client=host_client,
            run_embedded=run_embedded,
        )

    # ------------------------------------------------------------------
    # Lifecycle — acts on the service only when this process owns it
    # ------------------------------------------------------------------

    def __enter__(self) -> CloudXRLauncher:
        """Return the launcher for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the runtime on exit, if this process started it."""
        self.stop()

    def stop(self) -> None:
        """Stop the runtime and WSS proxy this process started.

        A no-op when attached: the service that owns the runtime outlives
        every script that uses it.
        """
        if self._service is not None:
            self._service.stop()

    def health_check(self) -> None:
        """Raise :class:`RuntimeError` if the runtime is no longer available.

        Raises:
            RuntimeError: If the owned runtime or WSS proxy has stopped, or
                the runtime this attached to is gone.
        """
        if self._service is not None:
            self._service.health_check()
            return
        if not is_runtime_live(self._run_dir):
            raise RuntimeError(
                f"The CloudXR runtime serving {self._run_dir} has stopped"
            )

    @property
    def wss_log_path(self) -> Path | None:
        """Path to the WSS proxy log file, or ``None`` if there is none."""
        if self._service is not None:
            return self._service.wss_log_path
        found = latest_wss_log(self._logs_dir)
        return Path(found) if found else None
