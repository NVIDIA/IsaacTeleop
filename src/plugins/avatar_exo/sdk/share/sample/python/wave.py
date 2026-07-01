"""SharpaWave bridge used by avatar_teleop.py --wave.

Data flow:
  - glove ROBOT joints -> SharpaWave HAND position control
  - SharpaWave tactile F6 -> glove set_3d_force
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from avatar_sdk import AvatarDataFrame, AvatarDevice, DeviceSide, ErrorCode

logger = logging.getLogger("wave")

_SDK_ROOTS = (
    Path("/opt/avatar-sdk/share/wave-sdk"),
    Path("/opt/sharpa-wave-sdk"),
)

DISCOVERY_POLL_SEC = 0.25
ROBOT_POLL_SEC = 0.01
TACTILE_HZ = 30.0
ZERO_FORCE_REPEAT_COUNT = 5
ZERO_FORCE_REPEAT_INTERVAL_S = 0.1

# Wave channels are pinky..thumb; Avatar set_3d_force expects thumb..pinky.
_WAVE_TACTILE_CHANNELS = {
    "right": [("PINKY", 0), ("RING", 1), ("MIDDLE", 2), ("INDEX", 3), ("THUMB", 4)],
    "left": [("PINKY", 5), ("RING", 6), ("MIDDLE", 7), ("INDEX", 8), ("THUMB", 9)],
}
_AVATAR_FINGER_INDEX = {"THUMB": 0, "INDEX": 1, "MIDDLE": 2, "RING": 3, "PINKY": 4}


class WaveService:
    """Small sample bridge owned by avatar_teleop.py."""

    def __init__(self, get_glove: Callable[[DeviceSide], AvatarDevice | None]) -> None:
        self._get_glove = get_glove
        self._sdk_root = ""
        self._discovery_poll_sec = DISCOVERY_POLL_SEC

        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._active_sides: set[str] = set()
        self._hands: dict[str, object] = {}
        self._latest_joints: dict[str, list[float]] = {}
        self._last_force: dict[str, tuple[float, ...]] = {}
        self._last_log: dict[str, float] = {}

        self._mgr: object | None = None
        self._DeviceType: Any = None
        self._HandSide: Any = None

    @property
    def enabled(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def configure(self, cfg: dict[str, Any]) -> None:
        self._sdk_root = str(cfg.get("wave_sdk_root", ""))
        self._discovery_poll_sec = _positive_float(cfg.get("wave_discovery_poll_sec", cfg.get("wave_poll_sec")), DISCOVERY_POLL_SEC)
        logger.debug("WaveService discovery_poll_sec=%.3f", self._discovery_poll_sec)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="SampleWaveBridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)
        self._thread = None

        with self._lock:
            hands = list(self._hands.items())
            self._hands.clear()
            self._active_sides.clear()
            self._latest_joints.clear()
            self._last_force.clear()

        for side, hand in hands:
            try:
                hand.stop()
            except Exception as exc:
                logger.warning("Wave stop %s: %s", side, exc)
        if self._mgr is not None:
            try:
                self._mgr.disconnect_all()
            except Exception as exc:
                logger.warning("disconnect_all: %s", exc)
            self._mgr = None

    def on_robot_frame(self, side: DeviceSide, frame: AvatarDataFrame) -> None:
        try:
            joints = [float(value) for value in list(frame.robot.joint.position)[:22]]
        except Exception:
            return
        if len(joints) != 22:
            return
        with self._lock:
            key = _side_key(side)
            self._active_sides.add(key)
            self._latest_joints[key] = joints

    def _run(self) -> None:
        if not self._init_wave_sdk():
            return

        next_discovery = 0.0
        next_tactile = 0.0
        tactile_period = 1.0 / TACTILE_HZ

        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                active_sides = sorted(self._active_sides)
                latest_joints = {side: joints[:] for side, joints in self._latest_joints.items()}

            if now >= next_discovery:
                if not self._connect_missing_hands(active_sides):
                    self._stop.set()
                    break
                next_discovery = now + self._discovery_poll_sec

            for side, joints in latest_joints.items():
                hand = self._hand(side)
                if hand is not None:
                    self._send_joints(side, hand, joints)

            if now >= next_tactile:
                for side in active_sides:
                    self._poll_tactile(side)
                next_tactile = now + tactile_period

            time.sleep(ROBOT_POLL_SEC)

    # ---- Wave setup and discovery -----------------------------------------------------

    def _init_wave_sdk(self) -> bool:
        py_dir, lib_dir = _wave_paths(self._sdk_root)
        logger.info(
            "SharpaWave SDK runtime: Python %s wave_python=%s available_extensions=%s",
            _python_version_label(),
            py_dir,
            _available_sharpa_extensions(py_dir),
        )
        if str(py_dir) not in sys.path:
            sys.path.insert(0, str(py_dir))
        _preload_wave_libs(lib_dir)
        try:
            from sharpa import DeviceType, HandSide, SharpaWaveManager
        except ImportError as exc:
            logger.error(
                "SharpaWave import failed; tactile disabled: %s; Python %s; wave_python=%s; "
                "available_extensions=%s; import_error=%s",
                _wave_import_failure_reason(py_dir),
                _python_version_label(),
                py_dir,
                _available_sharpa_extensions(py_dir),
                exc,
            )
            return False
        try:
            self._mgr = SharpaWaveManager.get_instance()
        except Exception as exc:
            logger.warning("SharpaWaveManager init failed: %s", exc)
            return False
        self._DeviceType = DeviceType
        self._HandSide = HandSide
        logger.debug("SharpaWave manager initialized")
        return True

    def _connect_missing_hands(self, active_sides: list[str]) -> bool:
        if self._mgr is None:
            return False
        if not active_sides:
            return True

        try:
            devices = list(self._mgr.get_all_devices())
        except Exception as exc:
            self._throttled_debug("devices:error", "SharpaWave get_all_devices failed: %s", exc)
            return True

        self._throttled_debug("devices", "SharpaWave devices: %s", _device_summaries(devices, self._HandSide))
        for side in active_sides:
            hand_info = self._single_hand_for_side(devices, side)
            if hand_info is False:
                return False
            if self._hand(side) is not None:
                continue
            if hand_info is None:
                self._throttled_debug(f"nohand:{side}", "waiting for %s Wave HAND", side)
                continue
            self._connect_hand(side, hand_info)
        return True

    def _single_hand_for_side(self, devices: list[object], side: str) -> object | None | bool:
        wanted = self._HandSide.LEFT if side == "left" else self._HandSide.RIGHT
        matches = [
            dev for dev in devices
            if getattr(dev, "device_type", None) == self._DeviceType.HAND and getattr(dev, "hand_side", None) == wanted
        ]
        if len(matches) > 1:
            sns = ", ".join(str(getattr(dev, "sn", "")) for dev in matches)
            logger.error("Multiple %s Wave HAND devices found (%s); stop Wave bridge", side, sns)
            return False
        return matches[0] if matches else None

    def _connect_hand(self, side: str, info: object) -> None:
        if self._mgr is None:
            return
        sn = getattr(info, "sn", "")
        try:
            hand = self._mgr.connect(sn)
        except RuntimeError as exc:
            logger.debug("SharpaWave connect pending side=%s sn=%s: %s", side, sn, exc)
            return
        except Exception as exc:
            logger.warning("SharpaWave connect failed side=%s sn=%s: %s", side, sn, exc)
            return

        if not self._setup_hand(hand):
            logger.warning("Wave init failed side=%s sn=%s; will retry", side, sn)
            try:
                hand.stop()
            except Exception:
                pass
            return

        with self._lock:
            if side in self._active_sides and side not in self._hands:
                self._hands[side] = hand
                logger.info("Wave connected %s sn=%s", side, sn)
            else:
                try:
                    hand.stop()
                except Exception:
                    pass

    def _setup_hand(self, hand: object) -> bool:
        from sharpa import ControlMode, ControlSource

        deadline = time.monotonic() + 5.0
        while not hand.is_hand_ready():
            if time.monotonic() > deadline:
                return False
            time.sleep(0.1)

        for step in (
            lambda: hand.set_control_mode(ControlMode.POSITION),
            lambda: hand.set_speed_coeff(1.0),
            lambda: hand.set_current_coeff(0.6),
            lambda: hand.set_control_source(ControlSource.SDK),
        ):
            err = step()
            if getattr(err, "code", 0):
                return False
        if not hand.start():
            return False
        try:
            hand.calib_tactile()
        except Exception as exc:
            logger.debug("calib_tactile: %s", exc)
        hand.set_joint_position([0.0] * 22, True)
        return True

    # ---- Downstream: glove ROBOT joints -> Wave hand ----------------------------------

    def _send_joints(self, side: str, hand: object, joints: list[float]) -> None:
        try:
            err = hand.set_joint_position(joints, False)
        except Exception as exc:
            self._throttled_warning(f"joint:{side}", "set_joint_position %s: %s", side, exc)
            return
        if getattr(err, "code", 0):
            self._throttled_warning(
                f"joint:{side}",
                "set_joint_position %s: %s",
                side,
                getattr(err, "message", err),
            )

    # ---- Upstream: Wave tactile -> glove set_3d_force ---------------------------------

    def _poll_tactile(self, side: str) -> None:
        hand = self._hand(side)
        if hand is None:
            return

        force_x = [0.0] * 5
        force_y = [0.0] * 5
        force_z = [0.0] * 5
        found = False

        for finger, channel in _WAVE_TACTILE_CHANNELS.get(side, []):
            xyz = _fetch_f6(hand, channel)
            if xyz is None:
                continue
            idx = _AVATAR_FINGER_INDEX[finger]
            force_x[idx], force_y[idx], force_z[idx] = xyz
            found = True

        if found:
            self._send_force_if_changed(side, force_x, force_y, force_z)

    def _send_force_if_changed(self, side: str, fx: list[float], fy: list[float], fz: list[float]) -> None:
        force_key = tuple(fx + fy + fz)
        with self._lock:
            if self._last_force.get(side) == force_key:
                return

        device_side = _device_side(side)
        payload = {
            "key": "set_3d_force",
            "device_side": _side_name(device_side),
            "force_x": fx,
            "force_y": fy,
            "force_z": fz,
        }
        if self._send_force(device_side, payload):
            with self._lock:
                self._last_force[side] = force_key

    def _send_force(self, side: DeviceSide, payload: dict[str, Any]) -> bool:
        glove = self._get_glove(side)
        if glove is None:
            return False

        body = json.dumps(payload, ensure_ascii=False)
        repeats = ZERO_FORCE_REPEAT_COUNT if _is_zero_force(payload) else 1
        ok = True
        for idx in range(repeats):
            if idx:
                time.sleep(ZERO_FORCE_REPEAT_INTERVAL_S)
            try:
                ec, _ = glove.set_task(body)
            except Exception as exc:
                self._throttled_warning("set_force", "set_3d_force: %s", exc)
                ok = False
                continue
            if ec != ErrorCode.SUCCESS:
                self._throttled_warning("set_force", "set_3d_force %s ec=%s", _side_name(side), ec)
                ok = False
        return ok

    # ---- Small helpers -----------------------------------------------------------------

    def _hand(self, side: str) -> object | None:
        with self._lock:
            return self._hands.get(side)

    def _throttled_warning(self, key: str, msg: str, *args: Any) -> None:
        if self._should_log(key):
            logger.warning(msg, *args)

    def _throttled_debug(self, key: str, msg: str, *args: Any) -> None:
        if self._should_log(key):
            logger.debug(msg, *args)

    def _should_log(self, key: str) -> bool:
        now = time.monotonic()
        if now - self._last_log.get(key, 0.0) < 2.0:
            return False
        self._last_log[key] = now
        return True


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _side_key(side: DeviceSide | str) -> str:
    if isinstance(side, DeviceSide):
        return "left" if side == DeviceSide.LEFT else "right"
    return "left" if str(side).lower() == "left" else "right"


def _device_side(side: str) -> DeviceSide:
    return DeviceSide.LEFT if side == "left" else DeviceSide.RIGHT


def _side_name(side: DeviceSide) -> str:
    return "LEFT" if side == DeviceSide.LEFT else "RIGHT"


def _wave_paths(configured_root: str = "") -> tuple[Path, Path]:
    candidates: list[Path] = []
    if configured_root:
        candidates.append(Path(configured_root).expanduser())
    env_root = os.getenv("SHARPA_WAVE_SDK_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.extend(_SDK_ROOTS)

    for root in candidates:
        if (root / "python" / "sharpa").exists():
            return root / "python", root / "lib"
    return candidates[0] / "python", candidates[0] / "lib"


def _python_version_label() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _available_sharpa_extensions(py_dir: Path) -> list[str]:
    sharpa_dir = py_dir / "sharpa"
    if not sharpa_dir.is_dir():
        return []
    return sorted(path.name for path in sharpa_dir.glob("sharpa.cpython-*.so"))


def _wave_import_failure_reason(py_dir: Path) -> str:
    expected_tag = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    available = _available_sharpa_extensions(py_dir)
    if not any(expected_tag in name for name in available):
        return f"no SharpaWave native extension for Python {_python_version_label()}"
    return "SharpaWave import failed"


def _preload_wave_libs(lib_dir: Path) -> None:
    if not lib_dir.is_dir():
        logger.warning("SharpaWave SDK lib directory not found: %s", lib_dir)
        return
    for name in ("libsharpa-wave-c-api.so", "libsharpa-wave-sdk.so"):
        path = lib_dir / name
        if not path.is_file():
            logger.warning("SharpaWave SDK native library not found: %s", path)
            continue
        try:
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
        except OSError as exc:
            logger.warning("preload %s: %s", path, exc)


def _fetch_f6(hand: object, channel: int) -> tuple[float, float, float] | None:
    try:
        ret = hand.fetch_tactile_frame(channel, 0.0)
    except TypeError:
        ret = hand.fetch_tactile_frame(channel)
    except Exception:
        return None

    content = ret.get("content") if isinstance(ret, dict) else None
    if not isinstance(content, dict):
        return None
    return _xyz(content.get("F6"))


def _xyz(value: Any) -> tuple[float, float, float] | None:
    if value is None:
        return None
    if hasattr(value, "flatten"):
        try:
            value = value.flatten()
        except Exception:
            pass
    try:
        seq = list(value)
    except TypeError:
        return None
    if len(seq) < 3:
        return None
    try:
        return float(seq[0]), float(seq[1]), float(seq[2])
    except (TypeError, ValueError):
        return None


def _device_summaries(devices: list[object], HandSide: Any) -> str:
    out: list[str] = []
    for dev in devices:
        side = getattr(dev, "hand_side", None)
        if side == HandSide.LEFT:
            side_name = "left"
        elif side == HandSide.RIGHT:
            side_name = "right"
        else:
            side_name = str(side)
        out.append(f"sn={getattr(dev, 'sn', '')} side={side_name} type={getattr(dev, 'device_type', '')}")
    return "[" + "; ".join(out) + "]"


def _is_zero_force(payload: dict[str, Any]) -> bool:
    return all(
        float(value) == 0.0
        for axis in ("force_x", "force_y", "force_z")
        for value in (payload.get(axis) or [])[:5]
    )
