# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Scriptable ``KeyEventSource`` for testing keyboard pipelines and provider integrations.

``FakeKeyEventSource`` behaves like a well-behaved host surface: it follows every rule of the
``KeyEventSource`` contract, so tests can drive a ``KeyboardSource`` through focus changes,
UI keyboard capture and press-only taps without a window. Host projects can compare their own
provider's behavior against it.
"""

from __future__ import annotations

from typing import Callable


class FakeKeyEventSource:
    """A focused input surface driven by test code.

    Starts focused, with its UI not capturing the keyboard. Key reports are dropped while the
    surface is unfocused or its UI owns the keyboard, as a real host would drop them.
    """

    supports_keyboard = True

    def __init__(self) -> None:
        self._listeners: list[
            tuple[Callable[[str | int, bool], None], Callable[[], None]]
        ] = []
        self.focused = True
        self.ui_capturing = False
        self.captured = False
        self.capture_history: list[bool] = []

    # KeyEventSource ----------------------------------------------------------------
    def add_key_listener(
        self,
        on_key: Callable[[str | int, bool], None],
        on_focus_lost: Callable[[], None],
    ) -> Callable[[], None]:
        entry = (on_key, on_focus_lost)
        self._listeners.append(entry)
        return lambda: self._listeners.remove(entry)

    def set_keyboard_captured(self, captured: bool) -> None:
        self.captured = captured
        self.capture_history.append(captured)

    # Test controls -------------------------------------------------------------------
    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    def press(self, code: str | int) -> None:
        self._emit(code, True)

    def release(self, code: str | int) -> None:
        self._emit(code, False)

    def tap(self, code: str | int) -> None:
        """A press-only surface's keystroke: press immediately followed by release."""
        self._emit(code, True)
        self._emit(code, False)

    def blur(self) -> None:
        """The surface loses focus: every held key must be released."""
        self.focused = False
        self._focus_lost()

    def focus(self) -> None:
        self.focused = True

    def begin_text_input(self) -> None:
        """The host UI takes the keyboard (a text field gains focus): same as focus loss."""
        self.ui_capturing = True
        self._focus_lost()

    def end_text_input(self) -> None:
        self.ui_capturing = False

    # Internals -----------------------------------------------------------------------
    def _emit(self, code: str | int, pressed: bool) -> None:
        if not self.focused or self.ui_capturing:
            return
        for on_key, _ in list(self._listeners):
            on_key(code, pressed)

    def _focus_lost(self) -> None:
        for _, on_focus_lost in list(self._listeners):
            on_focus_lost()
