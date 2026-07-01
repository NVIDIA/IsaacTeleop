# Python examples

Installed under `/opt/avatar-sdk/share/sample/python/` after packaging.

## Requirements

Install the sample-only Python dependencies before running the examples:

```bash
python3 -m pip install -r /opt/avatar-sdk/share/sample/python/requirements.txt
```

`avatar_sdk` itself is provided by the Avatar SDK deb package under
`/opt/avatar-sdk/lib/python`; it is not installed from this requirements file.

## 1. `avatar_example.py`

### Intro
Minimal Avatar SDK demo: connect glove(s), print RAW joint groups in degrees.

### Command
```bash
python3 /opt/avatar-sdk/share/sample/python/avatar_example.py
```

### CLI
| Flag | Meaning |
|------|---------|
| `config` | Optional SDK JSON path (default: `/opt/avatar-sdk/share/sdk_config.json`). |
| `--side` | `LEFT`, `RIGHT`, or `BOTH`. |

---

## 2. `avatar_teleop.py`

Small teleop bridge: glove data over Zenoh, optional SharpaWave slave-hand drive.

### Responsibilities
1. Publish RAW to `glove/raw/{left|right}` and retargeted ROBOT to `glove/robot/{left|right}`.
2. With `--wave`, load `wave.py` and drive SharpaWave hands with ROBOT joints.
3. With `--wave`, forward SharpaWave tactile F6 data back to the glove through `set_3d_force`.
4. Register `cmd/glove` for the minimal `zero_calib` command.

### Command
```bash
# Glove only (wireless / USB serial dongle)
python3 /opt/avatar-sdk/share/sample/python/avatar_teleop.py --transport wireless

# Wired Ethernet glove
python3 /opt/avatar-sdk/share/sample/python/avatar_teleop.py --transport wired

# Glove + SharpaWave slave hands
python3 /opt/avatar-sdk/share/sample/python/avatar_teleop.py --transport wireless --wave

# Wired Ethernet glove + SharpaWave slave hands
python3 /opt/avatar-sdk/share/sample/python/avatar_teleop.py --transport wired --wave
```

### Data pipeline
```text
  Glove -> Avatar SDK -> avatar_teleop.py -> Zenoh PUT -> glove/raw/{side}
                              |             -> Zenoh PUT -> glove/robot/{side}
                              |
                    (--wave) wave.WaveService
                              |-> set_joint_position -> SharpaWave HAND
                              `-> set_3d_force <- tactile F6 <- SharpaWave HAND

  Zenoh GET cmd/glove key=zero_calib -> AvatarDevice.set_task()
```

### CLI
| Flag | Meaning |
|------|---------|
| `config` | SDK JSON path (default: `/opt/avatar-sdk/share/sdk_config.json`). |
| `--side` | `LEFT`, `RIGHT`, or `BOTH`. |
| `--transport` | `wired` (`ethernet_udp`) or `wireless` (`usb_serial`). |
| `--wave` | Enable SharpaWave bridge (`wave.py`). |
| `--rate-hz` | Max publish rate per connected hand. |
| `--zenoh-config` | Zenoh JSON config file. |
| `--log-level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

---

## 3. `wave.py`

Module only; imported by `avatar_teleop.py --wave`.

| Feature | Description |
|---------|-------------|
| Discovery | Lazily connect left/right SharpaWave HAND devices. |
| Joints | Apply 22-DOF ROBOT frames from SDK retarget output. |
| Tactile | Poll F6 at 30 Hz and forward `set_3d_force` to the glove. |
| Init | Position mode, SDK control source, tactile calibration, zero homing. |
| Safety | Stop the Wave bridge if multiple same-side Wave HAND devices are found. |

Wave SDK path resolution checks `wave_sdk_root`, `SHARPA_WAVE_SDK_ROOT`, `/opt/avatar-sdk/share/wave-sdk`, and `/opt/sharpa-wave-sdk`.

---

## Dependencies

| Component | Requirement |
|-----------|-------------|
| Avatar SDK | `avatar_sdk` under `/opt/avatar-sdk/lib/python` after install. |
| Zenoh | `eclipse-zenoh` from `requirements.txt`. |
| NumPy | `numpy` from `requirements.txt`; required by sample-side Python/Wave paths on some installs. |
| Wave (`--wave`) | SharpaWave SDK installed or packaged. |
