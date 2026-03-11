# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CloudXR environment variable management.

Defines default env vars, optionally loads overrides from a user file,
resolves path-derived vars, applies to the process environment, and writes
the final env to a file under openxr_run_dir(). EnvConfig is a singleton so
state (e.g. resolved env) can be stored and reused.
"""

import os
import shlex
import warnings
from pathlib import Path


class EnvConfig:
    """Singleton holding CloudXR env configuration and resolved state.

    Configuration can come from three sources, with this precedence order:
    1. Env file (highest precedence)
    2. Process environment variables
    3. Hard-coded defaults in this class (_DEFAULT_ENV)

    Process environment variables are primarily intended for containerized
    environments (for example Docker/docker-compose). For local development,
    setting values via the env file is recommended over manually exporting
    environment variables.
    """

    _instance: "EnvConfig | None" = None

    # Env vars that are always computed; user env file must not override them.
    _RESOLVED_ONLY_KEYS: frozenset[str] = frozenset(
        {
            "XR_RUNTIME_JSON",
            "NV_CXR_RUNTIME_DIR",
            "NV_CXR_OUTPUT_DIR",
        }
    )

    # Default env var name -> default value. Empty string or None means "resolve later"
    _DEFAULT_ENV: dict[str, str | None] = {
        "XR_RUNTIME_JSON": None,  # resolved from openxr_run_dir()
        "NV_CXR_RUNTIME_DIR": None,  # resolved from openxr_run_dir()
        "NV_CXR_OUTPUT_DIR": None,  # resolved from ensure_logs_dir()
        "NV_CXR_ENABLE_PUSH_DEVICES": "true",
        "NV_CXR_ENABLE_TENSOR_DATA": "true",
        "XRT_NO_STDIN": "true",
        "NV_CXR_FILE_LOGGING": "true",
        "NV_DEVICE_PROFILE": "auto-webrtc",
    }

    def __new__(cls) -> "EnvConfig":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        # Resolved env after _load_resolve_and_apply / _resolve_and_apply (stored state)
        self._resolved_env: dict[str, str] | None = None
        # Install dir set from CLI (--cloudxr-install-dir); subprocess uses env fallback
        self._install_dir: str | None = None

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @classmethod
    def from_args(
        cls,
        install_dir: str,
        env_file: str | Path | None = None,
    ) -> "EnvConfig":
        """Create (or get) the singleton, set install dir, load/resolve/apply env, and return it."""
        cfg = cls()
        cfg._set_install_dir(install_dir)
        cfg._load_resolve_and_apply(env_file)
        return cfg

    def openxr_run_dir(self) -> str:
        """Return the CloudXR OpenXR run directory (volume/run, e.g. ~/.cloudxr/run)."""
        return os.path.join(self._cloudxr_install_dir(), "run")

    def ensure_logs_dir(self) -> Path:
        """Return the directory for CloudXR log files (volume/logs, e.g. ~/.cloudxr/logs)."""
        logs_dir = Path(self._cloudxr_install_dir()) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    def env_filepath(self) -> str:
        """Return the path to the env file."""
        return os.path.join(self.openxr_run_dir(), self._env_filename())

    # -------------------------------------------------------------------------
    # Private instance methods
    # -------------------------------------------------------------------------

    def _set_install_dir(self, path: str) -> None:
        """Set the CloudXR install directory (e.g. ~/.cloudxr)."""
        self._install_dir = os.path.abspath(os.path.expanduser(path))

    def _cloudxr_install_dir(self) -> str:
        """Return the CloudXR install directory (from from_args or, in subprocess, env)."""
        if self._install_dir is not None:
            return self._install_dir
        # Subprocess inherits env; install dir is set there from parent's applied env
        install = os.environ.get("CXR_INSTALL_DIR")
        if install:
            return os.path.abspath(os.path.expanduser(install))
        raise RuntimeError(
            "CloudXR install dir not set (call from_args or set CXR_INSTALL_DIR)"
        )

    def _env_filename(self) -> str:
        """Filename under openxr_run_dir() where the final env is written."""
        return "cloudxr.env"

    def _resolve_and_apply(self, env: dict[str, str]) -> dict[str, str]:
        """
        Resolve path-derived vars, apply to os.environ, and write to a file under
        openxr_run_dir(). Returns the final env dict and stores it in state.
        """
        install_dir = self._cloudxr_install_dir()
        env = {
            **env,
            "CXR_INSTALL_DIR": install_dir,
            "CXR_HOST_VOLUME_PATH": install_dir,  # for shell/docker scripts that expect it
        }
        for k, v in env.items():
            if v:
                os.environ[k] = v

        run_dir = self.openxr_run_dir()
        logs_dir = self.ensure_logs_dir()
        openxr_dir = os.path.dirname(run_dir)

        path_vars = {
            "XR_RUNTIME_JSON": os.path.join(openxr_dir, "openxr_cloudxr.json"),
            "NV_CXR_RUNTIME_DIR": run_dir,
            "NV_CXR_OUTPUT_DIR": str(logs_dir),
        }
        for k, v in path_vars.items():
            env[k] = v
            os.environ[k] = v

        out_path = self.env_filepath()
        os.makedirs(run_dir, mode=0o700, exist_ok=True)
        os.chmod(run_dir, 0o700)
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.chmod(out_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for k in sorted(env.keys()):
                v = env.get(k)
                if v is not None:
                    f.write(f"export {k}={shlex.quote(v)}\n")

        self._resolved_env = env
        return env

    def _load_resolve_and_apply(
        self,
        env_file: str | Path | None = None,
    ) -> dict[str, str]:
        """
        Load defaults, apply optional user env file overrides, resolve path vars,
        apply to process, and write to run dir. Returns the final env dict and stores it in state.
        """
        overrides = self._load_env_file(env_file) if env_file else {}
        for key in self._RESOLVED_ONLY_KEYS:
            if key in overrides:
                path_hint = f" in {env_file}" if env_file else ""
                warnings.warn(
                    f"Env file{path_hint} contains '{key}'; ignored (reserved, set by runtime).",
                    UserWarning,
                    stacklevel=2,
                )
                del overrides[key]

        merged = self._merge_env(self._DEFAULT_ENV, overrides)

        # Respect existing process environment values (e.g. docker-compose
        # container env) unless explicitly overridden via env_file.
        for key in self._DEFAULT_ENV:
            if key in self._RESOLVED_ONLY_KEYS or key in overrides:
                continue
            value = os.environ.get(key)
            if value is not None:
                merged[key] = value

        return self._resolve_and_apply(merged)

    # -------------------------------------------------------------------------
    # Private static methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_env_file(path: str | Path) -> dict[str, str]:
        """
        Parse a KEY=value env file (e.g. .env style). One KEY=value per line.
        Comments (#) and blank lines are ignored. Values undergo env expansion
        (e.g. $HOME) via os.path.expandvars and os.path.expanduser.
        """
        result: dict[str, str] = {}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"CloudXR env config not found: {p}")
        if not p.is_file():
            raise RuntimeError(f"CloudXR env config is not a file: {p}")
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    value = os.path.expanduser(os.path.expandvars(value))
                    result[key] = value
        return result

    @staticmethod
    def _merge_env(
        defaults: dict[str, str | None], overrides: dict[str, str]
    ) -> dict[str, str]:
        """Merge overrides onto defaults; only string values are kept in output."""
        out: dict[str, str] = {}
        for k, v in defaults.items():
            if v is not None and v != "":
                out[k] = v
        for k, v in overrides.items():
            if v is not None:
                out[k] = v
        return out


def get_env_config() -> EnvConfig:
    """Return the singleton EnvConfig instance."""
    return EnvConfig()
