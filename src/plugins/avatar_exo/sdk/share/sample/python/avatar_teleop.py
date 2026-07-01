"""Avatar SDK teleop sample.

Pipeline:
  glove -> RAW/ROBOT frames -> Zenoh ``glove/raw/{side}``, ``glove/robot/{side}``
  ``--wave`` -> ROBOT joints drive SharpaWave hands; Wave tactile feeds back to glove

Transport (``--transport``):
  wired = Ethernet to the glove; wireless = USB serial dongle to the glove.

Dependencies: ``pip install eclipse-zenoh``; ``--wave`` needs SharpaWave SDK on the host.

Local deb test:
  export AVATAR_DIST_PREFIX=/path/to/avatar-sdk_x.y.z_amd64
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

_EXAMPLE_DIR = Path(__file__).resolve().parent
_dist_root = os.environ.get("AVATAR_DIST_PREFIX")
SDK_PREFIX = Path(_dist_root) / "opt/avatar-sdk" if _dist_root else Path("/opt/avatar-sdk")

# Installed samples ship wave.py beside this script under share/sample/python.
sys.path.insert(0, str(_EXAMPLE_DIR))
if "AVATAR_SDK_DEV_BUILD_DIR" not in os.environ:
    sys.path.insert(0, str(SDK_PREFIX / "lib/python"))

import zenoh

logger = logging.getLogger("avatar_teleop")

_TRANSPORT_ALIAS = {
    "wired": "ethernet_udp",
    "wireless": "usb_serial",
    "ethernet_udp": "ethernet_udp",
    "usb_serial": "usb_serial",
}
_TRANSPORT_CHOICES = tuple(_TRANSPORT_ALIAS.keys())
_DISCOVERY_TIMEOUT_S = 5.0


def _resolve_transport(transport: str) -> str:
    link = _TRANSPORT_ALIAS.get(transport)
    if link is None:
        raise ValueError(f"unknown transport {transport!r}; expected: {', '.join(_TRANSPORT_CHOICES)}")
    return link


def _merge_transport(config_text: str, transport: str) -> str:
    """Keep this sample aligned with avatar-backend's transport switch."""
    cfg = json.loads(config_text)
    if not isinstance(cfg, dict):
        raise ValueError("sdk_config root must be a JSON object")
    cfg["transport_link"] = _resolve_transport(transport)
    cfg.pop("transport_link_options", None)
    return json.dumps(cfg, ensure_ascii=False)


def _loopback_zenoh_config() -> zenoh.Config:
    """Default to localhost-friendly peer mode for one-machine demos."""
    cfg = zenoh.Config()
    cfg.insert_json5("mode", '"peer"')
    cfg.insert_json5("listen/endpoints", json.dumps({"peer": ["tcp/127.0.0.1:0"]}))
    cfg.insert_json5("scouting/multicast/enabled", "true")
    cfg.insert_json5("scouting/multicast/address", '"224.0.0.224:7446"')
    cfg.insert_json5("scouting/multicast/ttl", "1")
    cfg.insert_json5("scouting/multicast/interface", '"127.0.0.1"')
    return cfg


def _publish(session: zenoh.Session, cache: dict[str, zenoh.Publisher], topic: str, data: bytes) -> None:
    if topic not in cache:
        cache[topic] = session.declare_publisher(topic)
    cache[topic].put(data)


def _query_dict(query: Any) -> dict[str, Any]:
    """Read simple query parameters plus an optional JSON payload."""
    req: dict[str, Any] = {}
    params = getattr(query, "parameters", None)
    if isinstance(params, str):
        for part in params.split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                req[key] = _coerce_value(value)
    else:
        try:
            for key, value in params or []:
                req[str(key)] = _coerce_value(str(value))
        except Exception:
            pass

    try:
        raw = bytes(query.payload)
    except Exception:
        raw = b""
    if raw:
        try:
            payload = json.loads(raw.decode("utf-8"))
            if isinstance(payload, dict):
                req.update(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return req


def _coerce_value(value: str) -> Any:
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def _reply(query: Any, success: bool, message: str = "") -> None:
    query.reply(query.key_expr, json.dumps({"success": success, "message": message}, ensure_ascii=False))


def _load_config_text(cfg_path: Path) -> str:
    if not cfg_path.is_file():
        return "{}"
    cfg_path = cfg_path.resolve()
    os.environ.setdefault("AVATAR_SDK_CONFIG_PATH", str(cfg_path))
    os.environ.setdefault("AVATAR_SDK_CONFIG_DIR", str(cfg_path.parent))
    os.environ.setdefault("AVATAR_SDK_HAND_FK_DATA_DIR", str(cfg_path.parent / "hand_fk"))
    return cfg_path.read_text(encoding="utf-8")


def _requested_sides(side_arg: str, DeviceSide: Any) -> list[Any]:
    if side_arg == "BOTH":
        return [DeviceSide.LEFT, DeviceSide.RIGHT]
    if side_arg == "LEFT":
        return [DeviceSide.LEFT]
    return [DeviceSide.RIGHT]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=None, help="SDK config JSON path")
    parser.add_argument("--side", choices=("LEFT", "RIGHT", "BOTH"), default="BOTH")
    parser.add_argument(
        "--transport",
        default="wireless",
        choices=_TRANSPORT_CHOICES,
        help="Glove link: wired=direct Ethernet, wireless=USB serial dongle",
    )
    parser.add_argument("--wave", action="store_true", help="Enable SharpaWave slave-hand bridge")
    parser.add_argument("--rate-hz", type=float, default=100.0, help="Max publish rate per hand")
    parser.add_argument("--zenoh-config", default=None, help="Zenoh JSON config file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level), format="[%(levelname)s] %(name)s: %(message)s")

    # Parse CLI first so --help works without loading the native Avatar SDK.
    from avatar_sdk import AvatarDevice, AvatarSDK, DeviceDataCategery, DeviceSide, DeviceType, ErrorCode

    cfg_path = Path(args.config) if args.config else SDK_PREFIX / "share/sdk_config.json"
    config_text = _load_config_text(cfg_path)
    logger.info("Config: %s", cfg_path.resolve() if cfg_path.is_file() else args.config)

    try:
        config_text = _merge_transport(config_text, args.transport)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("config: %s", exc)
        return 1
    logger.info("transport=%s -> %s", args.transport, _resolve_transport(args.transport))
    if not args.wave:
        logger.info("Wave disabled; pass --wave to drive SharpaWave hands")

    try:
        parsed = json.loads(config_text)
        cfg_dict: dict[str, Any] = parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        cfg_dict = {}

    sdk = AvatarSDK.get_instance()
    if sdk.initialize(config_text) != ErrorCode.SUCCESS:
        logger.error("AvatarSDK.initialize failed")
        return 1

    sides = _requested_sides(args.side, DeviceSide)
    side_label = {DeviceSide.LEFT: "left", DeviceSide.RIGHT: "right"}
    running = True

    def _stop(_sig=None, _frm=None) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    gloves: dict[str, AvatarDevice] = {}
    wave_svc: Any | None = None
    session: zenoh.Session | None = None

    try:
        logger.info("Waiting for device discovery...")
        pending = list(sides)
        deadline = time.monotonic() + _DISCOVERY_TIMEOUT_S
        while pending and time.monotonic() < deadline:
            for ds in list(pending):
                label = side_label[ds]
                glove = sdk.get_device(DeviceType.GLOVE, ds)
                if glove is None:
                    continue
                glove.init("{}")
                glove.start()
                gloves[label] = glove
                pending.remove(ds)
                logger.info("Connected %s glove", label.upper())
            if pending:
                time.sleep(0.2)

        for ds in pending:
            label = side_label[ds]
            logger.error("No %s glove found", label.upper())
            if args.side != "BOTH":
                return 1

        if not gloves:
            logger.error("No gloves connected")
            return 1

        def get_glove(side: DeviceSide) -> AvatarDevice | None:
            return gloves.get(side_label[side])

        if args.wave:
            from wave import WaveService

            wave_cfg = dict(cfg_dict)
            wave_cfg["enable_wave"] = True
            wave_svc = WaveService(get_glove)
            wave_svc.configure(wave_cfg)
            wave_svc.start()

        zcfg = zenoh.Config.from_file(args.zenoh_config) if args.zenoh_config else _loopback_zenoh_config()
        session = zenoh.open(zcfg)

        def on_glove_cmd(query: zenoh.Query) -> None:
            """Minimal sample command: trigger glove zero calibration."""
            try:
                req = _query_dict(query)
                if str(req.get("key", "")).strip() != "zero_calib":
                    _reply(query, False, "unsupported key; this sample only supports zero_calib")
                    return

                side_text = str(req.get("device_side", "")).upper()
                targets = ["left", "right"] if not side_text else [side_text.lower()]
                payload: dict[str, Any] = {"key": "zero_calib"}
                for field in ("joints", "zero_values_deg"):
                    if field in req:
                        payload[field] = req[field]

                for label in targets:
                    glove = gloves.get(label)
                    if glove is None:
                        _reply(query, False, f"device not connected: {label}")
                        return
                    body = dict(payload)
                    body["device_side"] = label.upper()
                    ec_task, _ = glove.set_task(json.dumps(body, ensure_ascii=False))
                    if ec_task != ErrorCode.SUCCESS:
                        _reply(query, False, f"zero_calib {label} failed: ErrorCode={ec_task}")
                        return
                _reply(query, True)
            except Exception as exc:
                logger.exception("cmd/glove zero_calib")
                _reply(query, False, str(exc))

        session.declare_queryable("cmd/glove", on_glove_cmd)
        logger.info("Queryable cmd/glove enabled for zero_calib")

        period = 1.0 / max(0.01, args.rate_hz)
        publishers: dict[str, zenoh.Publisher] = {}
        seq = {k: 0 for k in gloves}
        logger.info("Publishing glove/raw + glove/robot at %.1f Hz (Ctrl+C to stop)", args.rate_hz)
        if wave_svc is not None and wave_svc.enabled:
            logger.info("Wave bridge enabled: joints down, tactile up")

        while running:
            t0 = time.monotonic()
            for label, glove in gloves.items():
                ec_raw, raw_frame = glove.fetch_data(DeviceDataCategery.RAW)
                if ec_raw == ErrorCode.SUCCESS and raw_frame is not None:
                    try:
                        raw_frame.raw.header.seq = seq[label]
                        seq[label] += 1
                        raw_frame.raw.header.frame_id = label
                    except Exception:
                        pass
                    _publish(session, publishers, f"glove/raw/{label}", raw_frame.SerializeToString())

                ec_robot, robot_frame = glove.fetch_data(DeviceDataCategery.ROBOT)
                if ec_robot == ErrorCode.SUCCESS and robot_frame is not None:
                    if wave_svc is not None and wave_svc.enabled:
                        robot_side = DeviceSide.LEFT if label == "left" else DeviceSide.RIGHT
                        wave_svc.on_robot_frame(robot_side, robot_frame)
                    _publish(session, publishers, f"glove/robot/{label}", robot_frame.SerializeToString())
            time.sleep(max(0.0, period - (time.monotonic() - t0)))

        logger.info("Stopping...")
        return 0
    finally:
        for label, glove in gloves.items():
            try:
                glove.stop()
            except Exception as exc:
                logger.warning("stop(%s): %s", label, exc)
        if wave_svc is not None:
            wave_svc.stop()
        if session is not None:
            session.close()
        sdk.destroy()


if __name__ == "__main__":
    raise SystemExit(main())
