# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Programmatic access to the CloudXR runtime and WSS proxy.

:class:`CloudXRService` owns them; this is the API embedding applications
(e.g. Isaac Lab Teleop) use to reach a running one, and the CLI plumbing the
examples share.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import warnings
from pathlib import Path

from .env_config import DEFAULT_DEVICE_PROFILE
from .service import CloudXRService

logger = logging.getLogger(__name__)


class CloudXRLauncher:
    """Programmatic entry point to the CloudXR runtime and WSS proxy.

    Holds a :class:`~isaacteleop.cloudxr.service.CloudXRService`, which is
    what actually owns the runtime process and the proxy thread.  Started on
    construction; use :meth:`stop` or the context manager protocol to shut
    it down.

    Example::

        with CloudXRLauncher() as launcher:
            # runtime + WSS proxy are running
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
        start_wss_proxy: bool | None = None,
    ) -> None:
        """Start a :class:`CloudXRService` with the given configuration.

        See :meth:`CloudXRService.__init__` for the arguments; they are
        forwarded unchanged.  ``start_wss_proxy`` is a deprecated no-op kept
        so existing callers do not hit a :class:`TypeError`; the proxy always
        starts with the runtime.

        Raises:
            RuntimeError: If the EULA is not accepted, another runtime is
                already serving *install_dir*, or the runtime fails to
                start within the timeout.
        """
        if start_wss_proxy is not None:
            self._warn_start_wss_proxy_deprecated()

        self._service = CloudXRService(
            install_dir=install_dir,
            env_config=env_config,
            device_profile=device_profile,
            accept_eula=accept_eula,
            setup_oob=setup_oob,
            usb_local=usb_local,
            host_client=host_client,
        )

    # TODO(1.6): drop start_wss_proxy, --launch-wss-proxy and this helper.
    @staticmethod
    def _warn_start_wss_proxy_deprecated() -> None:
        """Announce that the ``start_wss_proxy`` no-op is on its way out."""
        message = (
            "start_wss_proxy is deprecated and does nothing; the WSS proxy "
            "always starts with the runtime.  It is removed in 1.6."
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

    @staticmethod
    def add_launch_cloudxr_runtime_argument(parser: argparse.ArgumentParser) -> None:
        """Register ``--launch-cloudxr-runtime`` on ``parser``.

        Uses :class:`argparse.BooleanOptionalAction`, so callers may pass
        ``--no-launch-cloudxr-runtime`` when the runtime is already running
        (for example after sourcing ``~/.cloudxr/run/cloudxr.env``).
        """
        parser.add_argument(
            "--launch-cloudxr-runtime",
            action=argparse.BooleanOptionalAction,
            default=True,
            help=(
                "Launch the CloudXR runtime and WSS proxy in-process before running "
                "(default: true). Pass --no-launch-cloudxr-runtime when the runtime is "
                "already running (e.g. after sourcing ~/.cloudxr/run/cloudxr.env)."
            ),
        )

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
                "Deprecated no-op, removed in 1.6: the WSS TLS proxy always "
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
        start_wss_proxy: bool | None = None,
    ) -> contextlib.AbstractContextManager[CloudXRLauncher | None]:
        """Start :class:`CloudXRLauncher` when ``args.launch_cloudxr_runtime`` is true.

        Returns :func:`contextlib.nullcontext` when ``args.launch_cloudxr_runtime`` is
        false so callers can always use ``with CloudXRLauncher.launch_context(args):``.

        ``install_dir``, ``env_config``, ``device_profile``, and ``accept_eula``
        default to the values registered by :meth:`add_launcher_arguments`
        (``args.cloudxr_install_dir`` etc.); pass an explicit keyword only to
        override what came in on the command line. For ``accept_eula``, pass
        ``False`` to force-disable even when the CLI flag is set.
        ``start_wss_proxy`` is a deprecated no-op removed in 1.6.
        """
        if (
            start_wss_proxy is not None
            or getattr(args, "launch_wss_proxy", None) is not None
        ):
            CloudXRLauncher._warn_start_wss_proxy_deprecated()
        if not args.launch_cloudxr_runtime:
            return contextlib.nullcontext(None)
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
        )

    # ------------------------------------------------------------------
    # Lifecycle — delegated to the service
    # ------------------------------------------------------------------

    def __enter__(self) -> CloudXRLauncher:
        """Return the launcher for use in a ``with`` block."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the launcher on exiting the ``with`` block."""
        self.stop()

    def stop(self) -> None:
        """Shut down the WSS proxy and terminate the runtime process."""
        self._service.stop()

    def health_check(self) -> None:
        """Raise :class:`RuntimeError` if the runtime or WSS proxy has stopped."""
        self._service.health_check()

    @property
    def wss_log_path(self) -> Path | None:
        """Path to the WSS proxy log file, or ``None`` if not yet started."""
        return self._service.wss_log_path
