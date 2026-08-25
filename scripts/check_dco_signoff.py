#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Commit-msg hook: require a DCO Signed-off-by that matches the committer.

A sign-off certifies that *you* have the right to submit the work, so a trailer
naming someone else certifies nothing. Presence alone was checked before this;
the identity half was documented in AGENTS.md but never enforced.

Extra trailers are fine — relaying a patch keeps the original author's sign-off
and adds yours — so the rule is that at least one matches, not that all do.
"""

from __future__ import annotations

import re
import subprocess
import sys

# A real git trailer: "Signed-off-by: Name <email>" at the start of a line, with
# at least one non-whitespace character before the angle bracket.
_TRAILER_RE = re.compile(r"^Signed-off-by:\s*(\S.*?)\s*<(\S+)>\s*$", re.MULTILINE)

# `git var` returns "Name <email> 1234567890 +0000".
_IDENT_RE = re.compile(r"^(.*?)\s*<(.*)>\s+\d+\s+[+-]\d{4}$")


def _committer() -> tuple[str, str] | None:
    """Return the (name, email) `git commit -s` would sign off with.

    GIT_COMMITTER_IDENT rather than `git config user.name`, because that is what
    --signoff itself uses: it honours the GIT_COMMITTER_* environment overrides
    the config does not see, so the two can disagree.
    """
    try:
        proc = subprocess.run(
            ["git", "var", "GIT_COMMITTER_IDENT"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None

    match = _IDENT_RE.match(proc.stdout.strip())
    return (match.group(1), match.group(2)) if match else None


def main() -> int:
    with open(sys.argv[1]) as handle:
        msg = handle.read()

    # Drop the comment lines git inserts (e.g. under --verbose).
    body = "\n".join(line for line in msg.splitlines() if not line.startswith("#"))
    trailers = [(name, email) for name, email in _TRAILER_RE.findall(body)]

    if not trailers:
        print(
            "ERROR: commit message is missing a DCO Signed-off-by line.\n"
            "\n"
            "  Add it automatically:  git commit -s  (or --signoff)\n"
            "  Or append manually:\n"
            "\n"
            "    Signed-off-by: Your Name <your@email.com>\n"
            "\n"
            "  See AGENTS.md § Commits for details.",
            file=sys.stderr,
        )
        return 1

    committer = _committer()
    if committer is None:
        # No identity to compare against — outside a repo, or git unavailable.
        # The trailer is present and well-formed, which is as far as we can get.
        return 0

    name, email = committer
    # Addresses are case-insensitive in practice; names are compared as written.
    if any(t == name and e.lower() == email.lower() for t, e in trailers):
        return 0

    found = "\n".join(f"    Signed-off-by: {t} <{e}>" for t, e in trailers)
    print(
        "ERROR: no Signed-off-by line matches your git identity.\n"
        "\n"
        f"  Your identity:\n    {name} <{email}>\n"
        "\n"
        f"  Found:\n{found}\n"
        "\n"
        "  A sign-off certifies that you have the right to submit the work, so\n"
        "  it has to be yours. Keeping someone else's is fine — add yours too:\n"
        "\n"
        "    git commit --amend -s\n"
        "\n"
        "  If the identity above is wrong, fix it and amend:\n"
        "\n"
        "    git config user.name  'Your Name'\n"
        "    git config user.email 'your@email.com'\n"
        "\n"
        "  See AGENTS.md § Commits for details.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
