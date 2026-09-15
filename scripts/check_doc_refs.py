#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Pre-commit hook: docs must not point at code that is not there.

Two checks, both deliberately exact rather than heuristic:

1. `:code-file:` / `:code-dir:` targets must exist, with the shape the role
   implies. The roles in docs/source/conf.py build a github.com blob/tree URL
   out of whatever string they are given and validate nothing, so a moved file
   ships a live 404 while the Sphinx build stays green.
2. `isaacteleop.*` imports inside documented Python must resolve to a real
   module under src/python/. A renamed package leaves examples that raise
   ModuleNotFoundError on the reader's first paste.

Prose and shell paths are out of scope: matching those needs heuristics, and a
doc-wide sweep of them produced mostly false positives (build artifacts,
`cd`-relative paths, other repos' trees). A committer-facing gate has to be
right every time to stay worth having.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROLE_RE = re.compile(r":code-(file|dir):`([^`]*)`", re.S)

# `.. code-block:: python` (reST) and ```python (Markdown).
RST_PY_BLOCK_RE = re.compile(
    r"^([ \t]*)\.\. code-block:: *(?:python|py)\s*$", re.MULTILINE
)
MD_PY_BLOCK_RE = re.compile(r"^```+ *(?:python|py)\s*$(.*?)^```+\s*$", re.M | re.S)

IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(isaacteleop(?:\.[\w.]+)?)\s+import\b"
    r"|import\s+(isaacteleop(?:\.[\w.]+)?))",
    re.MULTILINE,
)

PYTHON_ROOT = "src/python"

# Targets that are known to be wrong and are not fixed yet. Keep the reason, and
# delete the entry rather than let it settle in: every line here is a 404 on the
# published docs. A --all sweep reports entries that start resolving and entries
# nothing references any more, so this cannot quietly outlive its problem.
KNOWN_BROKEN: dict[str, str] = {}


# Documented imports that are known wrong and not fixed yet, for the same reason
# as KNOWN_BROKEN: the fix is not mechanical. Each value says why.
KNOWN_BROKEN_IMPORTS: dict[str, str] = {}


def _repo_root() -> Path:
    """Return the work tree root, so the hook can run from any subdirectory."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip())


def _parse_role(text: str) -> str:
    """Return the target of a role body, which is 'path' or 'label <path>'.

    Mirrors _parse_code_role in docs/source/conf.py, including the whitespace
    collapse: a role may wrap across source lines, and the label half may itself
    look like a path, so only the part inside <> counts when both are present.
    """
    text = " ".join(text.split())
    if " <" in text and text.endswith(">"):
        _, path = text.rsplit(" <", 1)
        return path[:-1].strip()
    return text


def _role_targets(source: str) -> list[tuple[int, str, str]]:
    """Return (line, kind, target) for every code-file/code-dir role."""
    found: list[tuple[int, str, str]] = []
    for match in ROLE_RE.finditer(source):
        target = _parse_role(match.group(2))
        if target:
            line = source.count("\n", 0, match.start()) + 1
            found.append((line, match.group(1), target))
    return found


def _rst_python_blocks(source: str) -> list[tuple[int, str]]:
    """Return (start_line, body) for each reST python code-block."""
    lines = source.splitlines()
    blocks: list[tuple[int, str]] = []
    for match in RST_PY_BLOCK_RE.finditer(source):
        indent = len(match.group(1))
        start = source.count("\n", 0, match.start()) + 1
        body: list[str] = []
        for index in range(start, len(lines)):
            line = lines[index]
            if not line.strip():
                body.append("")
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            body.append(line.strip())
        blocks.append((start, "\n".join(body)))
    return blocks


def _python_blocks(path: Path, source: str) -> list[tuple[int, str]]:
    """Return (start_line, body) for each documented Python block in path."""
    if path.suffix == ".rst":
        return _rst_python_blocks(source)
    return [
        (source.count("\n", 0, m.start()) + 1, m.group(1))
        for m in MD_PY_BLOCK_RE.finditer(source)
    ]


def _module_exists(root: Path, module: str) -> bool:
    """Return whether an isaacteleop.* dotted path resolves under src/python/."""
    base = root.joinpath(PYTHON_ROOT, *module.split("."))
    return (
        base.is_dir()
        or base.with_suffix(".py").is_file()
        or (base / "__init__.py").is_file()
    )


def _within(root: Path, candidate: Path) -> bool:
    """Return whether candidate is inside root once symlinks are followed.

    resolve() is what closes the symlink case: a link inside the tree pointing
    out of it would otherwise read as contained.
    """
    try:
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _references(path: Path) -> tuple[set[str], set[str]]:
    """Return (role targets, imported modules) named anywhere in path.

    Every reference, not just the broken ones: a full sweep uses this to find
    allowlist entries nothing points at any more.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set(), set()

    targets = (
        {t for _, _, t in _role_targets(source)} if path.suffix == ".rst" else set()
    )
    modules = {
        match.group(1) or match.group(2)
        for _, body in _python_blocks(path, source)
        for match in IMPORT_RE.finditer(body)
    }
    return targets, modules


def _check(root: Path, path: Path) -> list[str]:
    """Return one message per broken reference in path."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    rel = path.relative_to(root) if path.is_absolute() else path
    problems: list[str] = []

    if path.suffix == ".rst":
        for line, kind, target in _role_targets(source):
            if target in KNOWN_BROKEN:
                continue
            resolved = root / target.rstrip("/")
            # The role renders as {repo}/blob/{branch}/{target}, so a target that
            # leaves the work tree cannot resolve on GitHub however real it is on
            # this machine. Check containment before existence: `root / "/etc/x"`
            # is "/etc/x" (an absolute right operand discards the left), and
            # enough `..` walks out too, so both would otherwise pass on a file
            # that ships a 404.
            if not _within(root, resolved):
                problems.append(
                    f"{rel}:{line}: :code-{kind}: `{target}` resolves outside the "
                    f"repository; the link it builds cannot resolve on GitHub"
                )
                continue
            want_dir = kind == "dir"
            if resolved.is_dir() if want_dir else resolved.is_file():
                continue
            # A role held to the wrong kind still names something real, so saying
            # it "does not exist" sends the reader to ls, which finds the path and
            # makes the hook look broken. Name the mismatch and the role that fits.
            # The target leads and the role trails, because a role ends in a colon
            # and a trailing "use :code-file:: path" reads as a typo.
            if not resolved.exists():
                reason = "does not exist"
            else:
                found = "a directory" if resolved.is_dir() else "a file"
                fits = "code-dir" if resolved.is_dir() else "code-file"
                reason = f"is {found}; use :{fits}:"
            problems.append(f"{rel}:{line}: :code-{kind}: `{target}` {reason}")

    for start, body in _python_blocks(path, source):
        for match in IMPORT_RE.finditer(body):
            module = match.group(1) or match.group(2)
            if module in KNOWN_BROKEN_IMPORTS or _module_exists(root, module):
                continue
            line = start + body.count("\n", 0, match.start())
            problems.append(
                f"{rel}:{line}: documented import does not resolve under "
                f"{PYTHON_ROOT}/: {module}"
            )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check doc references.")
    parser.add_argument("filenames", nargs="*", help="files to check (from pre-commit)")
    parser.add_argument(
        "--all",
        action="store_true",
        help="sweep every doc in the tree instead of the passed filenames",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    if args.all:
        paths = sorted(root.glob("docs/source/**/*.rst"))
        paths += [
            path
            for path in root.glob("**/*.md")
            if not any(
                part in {".git", "build", "_build", ".venv", "node_modules"}
                for part in path.parts
            )
        ]
    else:
        paths = [
            Path(name) for name in args.filenames if name.endswith((".rst", ".md"))
        ]
    if not paths:
        return 0

    violations: list[str] = []
    seen_targets: set[str] = set()
    seen_modules: set[str] = set()
    for path in paths:
        violations.extend(_check(root, path))
        if args.all:
            targets, modules = _references(path)
            seen_targets |= targets
            seen_modules |= modules

    if violations:
        print("Docs reference code that is not in the tree.", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    # Both checks below are only meaningful for a full sweep: a partial run
    # simply did not visit the docs that would have justified an entry.
    if args.all:
        fixed = {
            target for target in KNOWN_BROKEN if (root / target.rstrip("/")).exists()
        }
        fixed |= {
            module for module in KNOWN_BROKEN_IMPORTS if _module_exists(root, module)
        }
        if fixed:
            print("Allowlisted entries that now resolve — delete them from the hook:")
            for target in sorted(fixed):
                print(f"  {target}")

        # An entry can also go stale by losing its last reference rather than by
        # starting to resolve — a doc that stops linking a generated file leaves
        # one behind, and the check above never fires because the path is still
        # absent. Without this, a dead allowlist reads as unpaid debt forever.
        unreferenced = (set(KNOWN_BROKEN) - seen_targets) | (
            set(KNOWN_BROKEN_IMPORTS) - seen_modules
        )
        # An entry can qualify both ways. Reporting it twice under two headings
        # reads as two problems; "now resolves" is the more actionable reason.
        unreferenced -= fixed
        if unreferenced:
            print("Allowlisted entries no longer referenced by any doc — delete them:")
            for target in sorted(unreferenced):
                print(f"  {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
