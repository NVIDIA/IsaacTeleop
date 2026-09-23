# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard Terminal Example (no window).

Feeds a KeyboardSource from the terminal it runs in: keys count only while this terminal
is focused, no extra window or privileges are needed, and it works over SSH. Prints every
press and the held keys each frame. Ctrl+C quits.

Terminals only report key releases when they support the kitty keyboard protocol (kitty,
WezTerm, foot, Ghostty, recent Alacritty); holding keys works there. Elsewhere (GNOME
Terminal, xterm, tmux) each keystroke is reported as a tap, which suits toggles (the K
gripper) but not held motion keys. Focus reporting (mode 1004) releases every key when the
terminal loses focus.

A keyboard-only pipeline needs no OpenXR runtime, so no CloudXR or headset is involved:

    python keyboard_terminal_example.py
"""

import os
import re
import select
import sys
import termios
import time
import tty

import numpy as np

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    EvdevKeyCode,
    KeyboardSource,
)
from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig

# kitty keyboard protocol flags: disambiguate (1) | report event types (2) | all keys as escapes (8).
_KITTY_FLAGS = 1 | 2 | 8
# CSI [key[:alternates]] [; modifiers[:event]] [; text] final -- covers kitty "u" keys, kitty
# arrows ("CSI 1;1:3A") and legacy arrows ("CSI A").
_KITTY_KEY = re.compile(
    rb"\x1b\[(\d*)(?::\d*)*(?:;(\d+)(?::(\d+))?)?(?:;[\d:]*)?([uABCDEFHPQS~])"
)
_LEGACY_ARROWS = {
    b"A": "ArrowUp",
    b"B": "ArrowDown",
    b"C": "ArrowRight",
    b"D": "ArrowLeft",
}
_KITTY_FUNCTIONAL = {
    27: "Escape",
    13: "Enter",
    9: "Tab",
    127: "Backspace",
    32: "Space",
    57441: "ShiftLeft",
    57447: "ShiftRight",
    57442: "ControlLeft",
    57448: "ControlRight",
    57443: "AltLeft",
    57449: "AltRight",
    **{57399 + d: f"Numpad{d}" for d in range(10)},
}
_CTRL_MODIFIER = 4  # kitty modifier bits are reported as 1 + bitmask


def _code_for_char(ch: str) -> str | None:
    if "a" <= ch.lower() <= "z":
        return f"Key{ch.upper()}"
    if "0" <= ch <= "9":
        return f"Digit{ch}"
    return {" ": "Space", "\r": "Enter", "\n": "Enter", "\t": "Tab"}.get(ch)


class TerminalKeySource:
    """KeyEventSource over the controlling terminal (no window)."""

    supports_keyboard = True

    def __init__(self, fd: int | None = None):
        self._fd = sys.stdin.fileno() if fd is None else fd
        self._listeners: list = []
        self._saved_attrs = None
        self._buffer = b""
        self.kitty = False

    # KeyEventSource --------------------------------------------------------------
    def add_key_listener(self, on_key, on_focus_lost):
        entry = (on_key, on_focus_lost)
        self._listeners.append(entry)
        return lambda: self._listeners.remove(entry)

    def set_keyboard_captured(self, captured: bool) -> None:
        pass  # the terminal has no key bindings of its own to yield

    # Terminal setup --------------------------------------------------------------
    def __enter__(self):
        self._saved_attrs = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        self._write(b"\x1b[?1004h")  # focus in/out reports
        # Ask for kitty protocol support; the primary device attributes reply ends the probe.
        self._write(b"\x1b[?u\x1b[c")
        reply = self._read_until(b"c", timeout_s=0.5)
        self.kitty = re.search(rb"\x1b\[\?\d+u", reply) is not None
        if self.kitty:
            self._write(b"\x1b[>%du" % _KITTY_FLAGS)
        return self

    def __exit__(self, *exc):
        self._release_all()
        if self.kitty:
            self._write(b"\x1b[<u")
        self._write(b"\x1b[?1004l")
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_attrs)
        return False

    # Polling ----------------------------------------------------------------------
    def poll(self) -> None:
        """Read pending input and dispatch key events. Raises KeyboardInterrupt on Ctrl+C."""
        while select.select([self._fd], [], [], 0)[0]:
            chunk = os.read(self._fd, 1024)
            if not chunk:
                break
            self._buffer += chunk
        self._parse()

    def _parse(self) -> None:
        buf = self._buffer
        while buf:
            if buf.startswith(b"\x1b[I"):
                buf = buf[3:]
                continue
            if buf.startswith(b"\x1b[O"):
                self._release_all()
                buf = buf[3:]
                continue
            if buf.startswith(b"\x1b["):
                match = _KITTY_KEY.match(buf)
                if match is None:
                    if len(buf) < 32:
                        break  # incomplete escape sequence; wait for more bytes
                    buf = buf[1:]
                    continue
                self._on_escape(match)
                buf = buf[match.end() :]
                continue
            ch, buf = buf[:1].decode("utf-8", "replace"), buf[1:]
            if ch == "\x03":
                raise KeyboardInterrupt
            code = _code_for_char(ch)
            if code is not None:  # legacy terminal: no release events, report a tap
                self._emit(code, True)
                self._emit(code, False)
        self._buffer = buf

    def _on_escape(self, match: re.Match) -> None:
        number, mods, event, final = match.groups()
        # Event type: 1 = press, 2 = repeat (ignored by the tracker), 3 = release.
        pressed = event != b"3"
        if final in _LEGACY_ARROWS:
            code = _LEGACY_ARROWS[final]
        elif final == b"u" and number:
            key = int(number)
            if key == ord("c") and mods and (int(mods) - 1) & _CTRL_MODIFIER:
                raise KeyboardInterrupt
            code = _KITTY_FUNCTIONAL.get(key) or (
                _code_for_char(chr(key)) if key < 128 else None
            )
        else:
            code = None
        if code is None:
            return
        if self.kitty:
            self._emit(code, pressed)
        else:  # legacy arrow: tap
            self._emit(code, True)
            self._emit(code, False)

    # Helpers ---------------------------------------------------------------------
    def _emit(self, code: str, pressed: bool) -> None:
        for on_key, _ in list(self._listeners):
            on_key(code, pressed)

    def _release_all(self) -> None:
        for _, on_focus_lost in list(self._listeners):
            on_focus_lost()

    def _write(self, data: bytes) -> None:
        os.write(sys.stdout.fileno(), data)

    def _read_until(self, terminator: bytes, timeout_s: float) -> bytes:
        data = b""
        deadline = time.monotonic() + timeout_s
        while (remaining := deadline - time.monotonic()) > 0:
            readable, _, _ = select.select([self._fd], [], [], remaining)
            if readable:
                data += os.read(self._fd, 256)
                if re.search(rb"\x1b\[\?[\d;]*" + terminator, data):
                    break
        return data


def _key_name(code: int) -> str:
    try:
        return EvdevKeyCode(code).name.removeprefix("KEY_")
    except ValueError:
        return f"code{code}"


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--duration", type=float, default=30.0, help="Seconds to run")
    args = parser.parse_args()

    if not os.isatty(sys.stdin.fileno()):
        parser.error("stdin must be a terminal")

    keyboard = KeyboardSource(name="keyboard")
    session_config = TeleopSessionConfig(
        app_name="KeyboardTerminalExample", trackers=[], pipeline=keyboard
    )

    with TeleopSession(session_config) as session, TerminalKeySource() as terminal:
        mode = (
            "press/release"
            if terminal.kitty
            else "tap-only (no kitty keyboard protocol)"
        )
        print(f"Keyboard mode: {mode}. Type here; Ctrl+C quits.", flush=True)
        detach = keyboard.attach(terminal)
        try:
            start = time.monotonic()
            last_held: list[int] = []
            while time.monotonic() - start < args.duration:
                terminal.poll()
                result = session.step()
                if not result["keyboard_all_keys"].is_none:
                    pressed = np.flatnonzero(np.asarray(result["keyboard_pressed"][0]))
                    held = np.flatnonzero(
                        np.asarray(result["keyboard_all_keys"][0])
                    ).tolist()
                    for code in pressed:
                        print(f"pressed: {_key_name(int(code))}", flush=True)
                    if held != last_held:
                        names = " ".join(_key_name(c) for c in held) or "-"
                        print(f"held: {names}", flush=True)
                        last_held = held
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            detach()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
