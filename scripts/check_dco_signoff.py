#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Commit-msg hook: reject commits that lack a DCO Signed-off-by line."""

import re
import sys

# Matches a real git trailer line: "Signed-off-by: Name <email>" at the start
# of a line, with at least one non-whitespace character before the angle bracket.
_TRAILER_RE = re.compile(r"^Signed-off-by: \S.*<\S+>", re.MULTILINE)


def main() -> None:
    commit_msg_file = sys.argv[1]
    with open(commit_msg_file) as f:
        msg = f.read()

    # Strip comment lines that git inserts (e.g. with --verbose)
    body = "\n".join(line for line in msg.splitlines() if not line.startswith("#"))

    if _TRAILER_RE.search(body):
        sys.exit(0)

    print(
        "ERROR: commit message is missing a DCO Signed-off-by line.\n"
        "\n"
        "  Add it automatically:  git commit -s  (or --signoff)\n"
        "  Or append manually:\n"
        "\n"
        "    Signed-off-by: Your Name <your@email.com>\n"
        "\n"
        "  Name/email must match: git config user.name / user.email\n"
        "  See AGENTS.md § Commits for details.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
