# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HTML for the panel's status lists.

Every mark gets its own label *and* its own colour. A reader must be able to separate a
pass from a measurement nobody judged without comparing two shades, and an unanswered
check must never render as an empty cell — blank reads as approval.
"""

from __future__ import annotations

from html import escape
from typing import Sequence

from ..report import CheckResult, Mark, Report, Verdict
from .status import Gate

# background, foreground
MARK_COLOURS: dict[Mark, tuple[str, str]] = {
    Mark.PASS: ("#cfe9d8", "#12502c"),
    Mark.FAIL: ("#c0322b", "#ffffff"),
    Mark.MEAS: ("#ffd98a", "#5a3b00"),
    Mark.UNANSWERED: ("#c9c9c9", "#2b2b2b"),
    Mark.NOTE: ("#c9ddf0", "#123f5f"),
}

VERDICT_COLOURS: dict[Verdict, tuple[str, str]] = {
    Verdict.PASS: ("#1f7a44", "#ffffff"),
    Verdict.FAIL: ("#a32820", "#ffffff"),
    Verdict.RETAKE: ("#b07100", "#ffffff"),
    Verdict.INSUFFICIENT_DATA: ("#5a5a5a", "#ffffff"),
}

VERDICT_MEANING: dict[Verdict, str] = {
    Verdict.PASS: "nothing in this recording argues against the integration",
    Verdict.FAIL: "an acceptance failure attributable to the device or its plugin",
    Verdict.RETAKE: "unusable because of how it was performed; the device is not implicated",
    Verdict.INSUFFICIENT_DATA: "the recording cannot answer the question",
}


def badge(mark: Mark) -> str:
    background, foreground = MARK_COLOURS[mark]
    return (
        f'<span style="display:inline-block;min-width:38px;padding:1px 4px;'
        f"border-radius:3px;text-align:center;font-family:monospace;font-size:10px;"
        f'font-weight:700;background:{background};color:{foreground}">{mark}</span>'
    )


def result_rows(results: Sequence[CheckResult]) -> str:
    if not results:
        return ""
    rows = "".join(
        f'<tr><td style="padding:2px 6px 2px 0;vertical-align:top">{badge(r.mark)}</td>'
        f'<td style="padding:2px 0;vertical-align:top;font-size:11px;line-height:1.35">'
        f'<span style="font-family:monospace">{escape(r.name)}</span><br>'
        f'<span style="opacity:0.75">{escape(r.detail)}</span></td></tr>'
        for r in results
    )
    # The top row sits under the folder's own edge and gets clipped without the padding.
    return (
        f'<div style="padding:7px 0 3px">'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table></div>'
    )


def gate_heading(gate: Gate) -> str:
    """The folder label: the group's own answer, before anyone expands it."""
    return f"{gate.title} — {gate.tally}"


def gate_body(gate: Gate) -> str:
    return result_rows(gate.results)


def verdict_banner(report: Report) -> str:
    background, foreground = VERDICT_COLOURS[report.verdict]
    return (
        f'<div style="background:{background};color:{foreground};padding:8px 10px;'
        f'border-radius:4px">'
        f'<div style="font-size:20px;font-weight:700;letter-spacing:0.05em;'
        f'font-family:monospace">{str(report.verdict).upper()}</div>'
        f'<div style="font-size:11px;opacity:0.9">'
        f"{escape(VERDICT_MEANING[report.verdict])}</div></div>"
    )


def facts(pairs: Sequence[tuple[str, str]]) -> str:
    rows = "".join(
        f'<tr><td style="padding:1px 8px 1px 0;font-size:11px;opacity:0.7;'
        f'white-space:nowrap">{escape(label)}</td>'
        f'<td style="padding:1px 0;font-size:11px;font-family:monospace">'
        f"{escape(value)}</td></tr>"
        for label, value in pairs
    )
    return f'<table style="border-collapse:collapse">{rows}</table>'


def packaged(filename: str, size_bytes: int, digest: str) -> str:
    """What was just handed to the browser, with the hash to quote when sending it."""
    return (
        f'<div style="font-size:11px;padding:3px 0">'
        f'<span style="font-family:monospace">{escape(filename)}</span><br>'
        f'<span style="opacity:0.75">{size_bytes / 1e6:.1f} MB &middot; sha256 '
        f"{escape(digest[:12])}…</span></div>"
    )


def package_failed(reason: object) -> str:
    return (
        f'<div style="font-size:11px;padding:3px 0;color:#b0342c">'
        f"could not package: {escape(str(reason))}</div>"
    )


def playhead(
    t_s: float,
    duration_s: float,
    sequence: int,
    valid_count: int,
    total_joints: int,
    step: str | None,
    held: Sequence[str],
) -> str:
    """The live readout under the scrubber.

    The valid-joint count is coloured, because it is the one number on this panel that
    can void the whole take on its own.
    """
    short = valid_count < total_joints
    colour = "#b0342c" if short else "#12502c"
    held_line = (
        f'<div style="font-size:11px;color:#b0342c">held: '
        f"{escape(', '.join(held))}</div>"
        if held
        else ""
    )
    return (
        f'<div style="font-family:monospace;font-size:12px">'
        f"{t_s:7.2f} s / {duration_s:.2f} s &nbsp; frame {sequence}</div>"
        f'<div style="font-size:12px">joints valid '
        f'<span style="font-weight:700;color:{colour}">{valid_count}/{total_joints}'
        f"</span></div>"
        f'<div style="font-size:11px;opacity:0.75">window: '
        f"{escape(step) if step else 'unlabelled'}</div>"
        f"{held_line}"
    )
