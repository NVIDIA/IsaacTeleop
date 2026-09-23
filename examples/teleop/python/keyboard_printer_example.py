# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Keyboard Printer Example.

Opens a small GLFW window and feeds its key events into a KeyboardSource. Keys only count
while that window has focus; click elsewhere and every held key is released. Prints held
keys each frame plus every press/release, using the "keyboard_all_keys" and
"keyboard_pressed" bitmaps.

The window is a minimal ``KeyEventSource``: any host window (a sim viewer, a browser
viewer, ...) can feed Isaac Teleop the same way. Requires ``isaaccapture[ui]`` for glfw. A
keyboard-only pipeline needs no OpenXR runtime, so no CloudXR or headset is involved.
"""

import sys
import time

import glfw
import numpy as np

from isaaccapture.retargeting_engine.deviceio_source_nodes import (
    EvdevKeyCode,
    KeyboardSource,
)
from isaaccapture.teleop_session_manager import TeleopSession, TeleopSessionConfig


def _glfw_to_w3c() -> dict[int, str]:
    """GLFW key tokens -> W3C KeyboardEvent.code for the keys this example cares about."""
    table = {getattr(glfw, f"KEY_{c}"): f"Key{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    table |= {getattr(glfw, f"KEY_{d}"): f"Digit{d}" for d in "0123456789"}
    table |= {getattr(glfw, f"KEY_KP_{d}"): f"Numpad{d}" for d in "0123456789"}
    table |= {getattr(glfw, f"KEY_F{n}"): f"F{n}" for n in range(1, 13)}
    table |= {
        glfw.KEY_UP: "ArrowUp",
        glfw.KEY_DOWN: "ArrowDown",
        glfw.KEY_LEFT: "ArrowLeft",
        glfw.KEY_RIGHT: "ArrowRight",
        glfw.KEY_SPACE: "Space",
        glfw.KEY_ENTER: "Enter",
        glfw.KEY_ESCAPE: "Escape",
        glfw.KEY_TAB: "Tab",
        glfw.KEY_LEFT_SHIFT: "ShiftLeft",
        glfw.KEY_RIGHT_SHIFT: "ShiftRight",
        glfw.KEY_LEFT_CONTROL: "ControlLeft",
        glfw.KEY_RIGHT_CONTROL: "ControlRight",
        glfw.KEY_LEFT_ALT: "AltLeft",
        glfw.KEY_RIGHT_ALT: "AltRight",
    }
    return table


class GlfwKeyWindow:
    """A GLFW window implementing the KeyEventSource protocol."""

    supports_keyboard = True

    def __init__(self, title: str):
        if not glfw.init():
            raise RuntimeError("glfw.init() failed (no display?)")
        glfw.window_hint(glfw.CLIENT_API, glfw.NO_API)
        self._window = glfw.create_window(480, 120, title, None, None)
        if not self._window:
            glfw.terminate()
            raise RuntimeError("glfw.create_window() failed")
        self._codes = _glfw_to_w3c()
        self._listeners: list = []
        glfw.set_key_callback(self._window, self._on_key)
        glfw.set_window_focus_callback(self._window, self._on_focus)

    # KeyEventSource ------------------------------------------------------------
    def add_key_listener(self, on_key, on_focus_lost):
        entry = (on_key, on_focus_lost)
        self._listeners.append(entry)
        return lambda: self._listeners.remove(entry)

    def set_keyboard_captured(self, captured: bool) -> None:
        pass  # this window has no key bindings of its own

    # GLFW callbacks --------------------------------------------------------------
    def _on_key(self, _window, key, _scancode, action, _mods):
        code = self._codes.get(key)
        if code is None or action == glfw.REPEAT:
            return
        for on_key, _ in list(self._listeners):
            on_key(code, action == glfw.PRESS)

    def _on_focus(self, _window, focused):
        if not focused:
            for _, on_focus_lost in list(self._listeners):
                on_focus_lost()

    # Host loop -----------------------------------------------------------------
    def poll(self) -> bool:
        """Dispatch window events; False once the window was closed."""
        glfw.poll_events()
        return not glfw.window_should_close(self._window)

    def close(self) -> None:
        self._on_focus(self._window, False)
        glfw.destroy_window(self._window)
        glfw.terminate()


def _key_name(code: int) -> str:
    try:
        return EvdevKeyCode(code).name.removeprefix("KEY_")
    except ValueError:
        return f"code{code}"


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print("Click the 'Isaac Teleop keyboard' window and press keys (30 s).")

    keyboard = KeyboardSource(name="keyboard")
    window = GlfwKeyWindow("Isaac Teleop keyboard")
    detach = keyboard.attach(window)

    session_config = TeleopSessionConfig(
        app_name="KeyboardPrinterExample",
        trackers=[],
        pipeline=keyboard,
    )

    try:
        with TeleopSession(session_config) as session:
            start_time = time.time()
            while time.time() - start_time < 30.0 and window.poll():
                result = session.step()
                held_group = result["keyboard_all_keys"]
                pressed_group = result["keyboard_pressed"]
                elapsed = session.get_elapsed_time()

                if held_group.is_none:
                    print(f"[{elapsed:5.1f}s] (no keyboard)", end="\r", flush=True)
                else:
                    held = np.flatnonzero(np.asarray(held_group[0]))
                    pressed = np.flatnonzero(np.asarray(pressed_group[0]))
                    for code in pressed:
                        print(f"\n[{elapsed:5.1f}s] {_key_name(int(code))} pressed")
                    names = " ".join(_key_name(int(c)) for c in held) or "-"
                    print(
                        f"[{elapsed:5.1f}s] Held: {names}" + " " * 20,
                        end="\r",
                        flush=True,
                    )

                time.sleep(0.01)
    finally:
        detach()
        window.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
