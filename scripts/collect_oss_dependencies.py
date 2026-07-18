#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Collect a lightweight OSS dependency inventory from repository manifests."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - CI uses Python 3.12.
    tomllib = None  # type: ignore[assignment]


EXCLUDED_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

REQUIREMENTS_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9_.-]+)\s*(?P<specifier>(?:===|==|~=|!=|<=|>=|<|>).*)?$"
)
DOCKER_FROM_RE = re.compile(
    r"^\s*FROM\s+(?:--platform=\S+\s+)?(?P<image>\S+)", re.IGNORECASE
)
GITHUB_ACTION_RE = re.compile(
    r"uses:\s*(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.\-/]+)@(?P<ref>[A-Za-z0-9_.\-/]+)"
)
CMAKE_FETCH_RE = re.compile(
    r"(?P<kind>FetchContent_Declare|ExternalProject_Add|CPMAddPackage)\s*\((?P<body>.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
CMAKE_NAME_RE = re.compile(r"^\s*(?P<name>[A-Za-z0-9_.:+/-]+)", re.MULTILINE)
CMAKE_KEY_VALUE_RE = re.compile(
    r"\b(?P<key>GIT_REPOSITORY|GIT_TAG|URL|VERSION|NAME)\s+(?P<value>\"[^\"]+\"|\S+)",
    re.IGNORECASE,
)


def _repo_path(repo_root: Path, path: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _iter_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in EXCLUDED_DIRS and not dirname.endswith("_deps")
        ]
        root = Path(current_root)
        for filename in filenames:
            files.append(root / filename)
    return files


def _entry(
    *,
    ecosystem: str,
    manifest_type: str,
    name: str,
    path: Path,
    repo_root: Path,
    line: int | None = None,
    version: str | None = None,
    scope: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    return {
        "ecosystem": ecosystem,
        "manifest_type": manifest_type,
        "name": name.strip(),
        "version": (version or "").strip(),
        "scope": (scope or "").strip(),
        "source": (source or "").strip(),
        "path": _repo_path(repo_root, path),
        "line": line,
    }


def _parse_requirement_text(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
    ):
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if not line or line.startswith(("-", "--")) or "://" in line:
            continue
        match = REQUIREMENTS_RE.match(line)
        if match:
            entries.append(
                _entry(
                    ecosystem="python",
                    manifest_type="requirements",
                    name=match.group("name"),
                    version=match.group("specifier"),
                    path=path,
                    repo_root=repo_root,
                    line=line_number,
                )
            )
    return entries


def _parse_pyproject(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    if tomllib is None:
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8", errors="ignore"))
    project = data.get("project", {})
    entries: list[dict[str, Any]] = []
    for dependency in project.get("dependencies", []) or []:
        entries.append(_python_dependency_entry(dependency, path, repo_root, "runtime"))
    optional = project.get("optional-dependencies", {}) or {}
    for scope, dependencies in optional.items():
        for dependency in dependencies or []:
            entries.append(
                _python_dependency_entry(dependency, path, repo_root, str(scope))
            )
    return entries


def _python_dependency_entry(
    dependency: str, path: Path, repo_root: Path, scope: str
) -> dict[str, Any]:
    match = REQUIREMENTS_RE.match(dependency)
    if match:
        return _entry(
            ecosystem="python",
            manifest_type="pyproject",
            name=match.group("name"),
            version=match.group("specifier"),
            scope=scope,
            path=path,
            repo_root=repo_root,
        )
    return _entry(
        ecosystem="python",
        manifest_type="pyproject",
        name=dependency,
        scope=scope,
        path=path,
        repo_root=repo_root,
    )


def _parse_package_json(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    entries: list[dict[str, Any]] = []
    for scope in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):
        for name, version in (data.get(scope, {}) or {}).items():
            entries.append(
                _entry(
                    ecosystem="npm",
                    manifest_type="package.json",
                    name=name,
                    version=str(version),
                    scope=scope,
                    path=path,
                    repo_root=repo_root,
                )
            )
    return entries


def _parse_vcpkg_manifest(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    entries: list[dict[str, Any]] = []
    for dependency in data.get("dependencies", []) or []:
        if isinstance(dependency, str):
            name = dependency
            version = ""
        else:
            name = str(dependency.get("name", ""))
            version = str(dependency.get("version>=", dependency.get("version", "")))
        if name:
            entries.append(
                _entry(
                    ecosystem="vcpkg",
                    manifest_type="vcpkg.json",
                    name=name,
                    version=version,
                    path=path,
                    repo_root=repo_root,
                )
            )
    return entries


def _parse_dockerfile(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
    ):
        match = DOCKER_FROM_RE.match(raw_line)
        if not match:
            continue
        image = match.group("image").split("@", maxsplit=1)[0]
        name, _, version = image.partition(":")
        entries.append(
            _entry(
                ecosystem="container",
                manifest_type="Dockerfile",
                name=name,
                version=version,
                path=path,
                repo_root=repo_root,
                line=line_number,
            )
        )
    return entries


def _parse_github_workflow(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
    ):
        match = GITHUB_ACTION_RE.search(raw_line)
        if match:
            entries.append(
                _entry(
                    ecosystem="github-actions",
                    manifest_type="workflow",
                    name=match.group("action"),
                    version=match.group("ref"),
                    path=path,
                    repo_root=repo_root,
                    line=line_number,
                )
            )
    return entries


def _parse_cmake(path: Path, repo_root: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    entries: list[dict[str, Any]] = []
    for match in CMAKE_FETCH_RE.finditer(text):
        body = match.group("body")
        fields = {
            field.group("key").upper(): field.group("value").strip('"')
            for field in CMAKE_KEY_VALUE_RE.finditer(body)
        }
        name_match = CMAKE_NAME_RE.search(body)
        name = fields.get("NAME") or (name_match.group("name") if name_match else "")
        source = fields.get("GIT_REPOSITORY") or fields.get("URL") or ""
        version = fields.get("GIT_TAG") or fields.get("VERSION") or ""
        line = text.count("\n", 0, match.start()) + 1
        if name:
            entries.append(
                _entry(
                    ecosystem="cmake",
                    manifest_type=match.group("kind"),
                    name=name,
                    version=version,
                    source=source,
                    path=path,
                    repo_root=repo_root,
                    line=line,
                )
            )
    return entries


def collect(repo_root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    manifests: Counter[str] = Counter()
    for path in _iter_files(repo_root):
        relative = _repo_path(repo_root, path)
        name = path.name.lower()
        suffix = path.suffix.lower()
        try:
            if name.startswith("requirements") and suffix == ".txt":
                entries.extend(_parse_requirement_text(path, repo_root))
                manifests["requirements"] += 1
            elif name == "pyproject.toml":
                entries.extend(_parse_pyproject(path, repo_root))
                manifests["pyproject"] += 1
            elif name == "package.json":
                entries.extend(_parse_package_json(path, repo_root))
                manifests["package.json"] += 1
            elif name == "vcpkg.json":
                entries.extend(_parse_vcpkg_manifest(path, repo_root))
                manifests["vcpkg.json"] += 1
            elif name.startswith("dockerfile") or "/dockerfile" in relative.lower():
                entries.extend(_parse_dockerfile(path, repo_root))
                manifests["Dockerfile"] += 1
            elif relative.startswith(".github/workflows/") and suffix in {
                ".yml",
                ".yaml",
            }:
                entries.extend(_parse_github_workflow(path, repo_root))
                manifests["GitHub workflow"] += 1
            elif name == "cmakelists.txt" or suffix == ".cmake":
                entries.extend(_parse_cmake(path, repo_root))
                manifests["CMake"] += 1
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            entries.append(
                _entry(
                    ecosystem="scanner",
                    manifest_type="parse-error",
                    name=relative,
                    version=type(exc).__name__,
                    source=str(exc),
                    path=path,
                    repo_root=repo_root,
                )
            )

    entries.sort(
        key=lambda item: (
            item["ecosystem"],
            item["name"].lower(),
            item["path"],
            item["line"] or 0,
        )
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "manifest_counts": dict(sorted(manifests.items())),
        "dependency_count": len(
            [entry for entry in entries if entry["manifest_type"] != "parse-error"]
        ),
        "parse_error_count": len(
            [entry for entry in entries if entry["manifest_type"] == "parse-error"]
        ),
        "dependencies": entries,
    }


def write_summary(report: dict[str, Any], summary_path: Path, limit: int = 200) -> None:
    counts = Counter(
        entry["ecosystem"]
        for entry in report["dependencies"]
        if entry["manifest_type"] != "parse-error"
    )
    lines = [
        "# OSS dependency inventory",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Totals",
        "",
        f"- Dependencies discovered: `{report['dependency_count']}`",
        f"- Parse errors: `{report['parse_error_count']}`",
        "",
        "## Ecosystems",
        "",
    ]
    for ecosystem, count in sorted(counts.items()):
        lines.append(f"- `{ecosystem}`: `{count}`")
    lines.extend(["", "## Manifest coverage", ""])
    for manifest, count in report["manifest_counts"].items():
        lines.append(f"- `{manifest}`: `{count}`")
    lines.extend(
        [
            "",
            "## Dependency sample",
            "",
            "| Ecosystem | Name | Version | Scope | Source | Path |",
            "|---|---|---|---|---|---|",
        ]
    )
    for entry in report["dependencies"][:limit]:
        path = entry["path"]
        if entry["line"]:
            path = f"{path}:{entry['line']}"
        lines.append(
            "| {ecosystem} | {name} | {version} | {scope} | {source} | {path} |".format(
                ecosystem=entry["ecosystem"],
                name=entry["name"].replace("|", "\\|"),
                version=entry["version"].replace("|", "\\|"),
                scope=entry["scope"].replace("|", "\\|"),
                source=entry["source"].replace("|", "\\|"),
                path=path.replace("|", "\\|"),
            )
        )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path("oss-report/dependency-inventory.json")
    )
    parser.add_argument(
        "--summary", type=Path, default=Path("oss-report/dependency-inventory.md")
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    report = collect(repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    write_summary(report, args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
