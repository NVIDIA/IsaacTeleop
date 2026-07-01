# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Generate a public-safe OSS dependency inventory for CI artifacts.

The report is intentionally static and non-blocking. It gives reviewers a
single artifact that covers the dependency surfaces that are otherwise spread
across Python metadata, npm package manifests, CMake FetchContent declarations,
vcpkg setup, and vendored license files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - CI uses Python 3.11+.
    tomllib = None


SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "install",
    "node_modules",
    "vcpkg_installed",
}

REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
FETCHCONTENT_RE = re.compile(
    r"FetchContent_Declare\s*\(\s*([A-Za-z0-9_.+-]+)(.*?)\)",
    re.DOTALL | re.IGNORECASE,
)
FETCHCONTENT_FIELD_RE = re.compile(
    r"^\s*(GIT_REPOSITORY|GIT_TAG|URL|URL_HASH)\s+(.+?)\s*(?:#.*)?$",
    re.MULTILINE,
)
CMAKE_SET_RE = re.compile(
    r"^\s*set\s*\(\s*([A-Za-z0-9_]+)\s+(.+?)\s*\)",
    re.MULTILINE,
)
VAR_REF_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


@dataclass(frozen=True)
class Dependency:
    ecosystem: str
    name: str
    requirement: str
    source: str
    manifest: str
    evidence: str


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_skip(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in parts)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def clean_token(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value.strip()


def resolve_vars(value: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return variables.get(match.group(1), match.group(0))

    previous = None
    current = value
    while previous != current:
        previous = current
        current = VAR_REF_RE.sub(replace, current)
    return current


def add_dependency(
    deps: set[Dependency],
    root: Path,
    *,
    ecosystem: str,
    name: str,
    requirement: str,
    source: str,
    manifest: Path,
    evidence: str,
) -> None:
    deps.add(
        Dependency(
            ecosystem=ecosystem,
            name=name.strip(),
            requirement=requirement.strip(),
            source=source.strip(),
            manifest=rel(manifest, root),
            evidence=evidence.strip(),
        )
    )


def collect_cmake_variables(root: Path) -> dict[str, str]:
    variables: dict[str, str] = {}
    for path in list(root.rglob("CMakeLists.txt")) + list(root.rglob("*.cmake")):
        if should_skip(path, root):
            continue
        for match in CMAKE_SET_RE.finditer(read_text(path)):
            name = match.group(1)
            value = clean_token(match.group(2).split(" CACHE ", 1)[0])
            variables[name] = resolve_vars(value, variables)
    return variables


def collect_python_requirements(root: Path, deps: set[Dependency]) -> None:
    for path in sorted(root.rglob("requirements*.txt")):
        if should_skip(path, root):
            continue
        for line_number, raw_line in enumerate(read_text(path).splitlines(), 1):
            line = raw_line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "git+", "http://", "https://")):
                continue
            match = REQUIREMENT_NAME_RE.match(line)
            if not match:
                continue
            add_dependency(
                deps,
                root,
                ecosystem="python",
                name=match.group(1),
                requirement=line,
                source="requirements",
                manifest=path,
                evidence=f"line {line_number}",
            )


def collect_pyproject_dependencies(
    root: Path, deps: set[Dependency], warnings: list[str]
) -> None:
    if tomllib is None:
        warnings.append("tomllib is unavailable; pyproject.toml files were skipped")
        return

    for path in sorted(root.rglob("pyproject.toml")):
        if should_skip(path, root):
            continue
        try:
            data = tomllib.loads(read_text(path))
        except tomllib.TOMLDecodeError as exc:
            warnings.append(f"{rel(path, root)} could not be parsed: {exc}")
            continue

        build_requires = data.get("build-system", {}).get("requires", [])
        for requirement in build_requires:
            match = REQUIREMENT_NAME_RE.match(requirement)
            if match:
                add_dependency(
                    deps,
                    root,
                    ecosystem="python-build",
                    name=match.group(1),
                    requirement=requirement,
                    source="pyproject build-system.requires",
                    manifest=path,
                    evidence="[build-system]",
                )

        project = data.get("project", {})
        for requirement in project.get("dependencies", []):
            match = REQUIREMENT_NAME_RE.match(requirement)
            if match:
                add_dependency(
                    deps,
                    root,
                    ecosystem="python",
                    name=match.group(1),
                    requirement=requirement,
                    source="pyproject project.dependencies",
                    manifest=path,
                    evidence="[project]",
                )

        optional_dependencies = project.get("optional-dependencies", {})
        for extra, requirements in optional_dependencies.items():
            for requirement in requirements:
                match = REQUIREMENT_NAME_RE.match(requirement)
                if match:
                    add_dependency(
                        deps,
                        root,
                        ecosystem="python",
                        name=match.group(1),
                        requirement=requirement,
                        source=f"pyproject optional-dependencies.{extra}",
                        manifest=path,
                        evidence=f"[project.optional-dependencies.{extra}]",
                    )


def collect_npm_dependencies(root: Path, deps: set[Dependency], warnings: list[str]) -> None:
    fields = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    for path in sorted(root.rglob("package.json")):
        if should_skip(path, root):
            continue
        try:
            data = json.loads(read_text(path))
        except json.JSONDecodeError as exc:
            warnings.append(f"{rel(path, root)} could not be parsed: {exc}")
            continue
        for field in fields:
            for name, requirement in data.get(field, {}).items():
                add_dependency(
                    deps,
                    root,
                    ecosystem="npm",
                    name=name,
                    requirement=str(requirement),
                    source=f"package.json {field}",
                    manifest=path,
                    evidence=field,
                )


def collect_fetchcontent_dependencies(
    root: Path, deps: set[Dependency], variables: dict[str, str]
) -> None:
    paths = list(root.rglob("CMakeLists.txt")) + list(root.rglob("*.cmake"))
    for path in sorted(paths):
        if should_skip(path, root):
            continue
        text = read_text(path)
        for match in FETCHCONTENT_RE.finditer(text):
            name = match.group(1)
            body = match.group(2)
            fields: dict[str, str] = {}
            for field_match in FETCHCONTENT_FIELD_RE.finditer(body):
                fields[field_match.group(1)] = resolve_vars(
                    clean_token(field_match.group(2)), variables
                )
            source = fields.get("GIT_REPOSITORY") or fields.get("URL", "")
            requirement = fields.get("GIT_TAG") or fields.get("URL_HASH", "")
            if not source:
                continue
            add_dependency(
                deps,
                root,
                ecosystem="cmake-fetchcontent",
                name=name,
                requirement=requirement,
                source=source,
                manifest=path,
                evidence="FetchContent_Declare",
            )


def collect_vcpkg_surface(
    root: Path, deps: set[Dependency], variables: dict[str, str]
) -> None:
    manifest = root / "cmake" / "DepthAIVcpkgManifest.cmake"
    if not manifest.exists():
        return

    version = variables.get("DEPTHAI_VERSION", "")
    commit = variables.get("DEPTHAI_COMMIT", "")
    url = (
        f"https://raw.githubusercontent.com/luxonis/depthai-core/{commit}/vcpkg.json"
        if commit
        else "https://github.com/luxonis/depthai-core"
    )
    add_dependency(
        deps,
        root,
        ecosystem="vcpkg",
        name="depthai-core vcpkg manifest",
        requirement=version or commit,
        source=url,
        manifest=manifest,
        evidence="downloaded and hash-verified during CMake configure",
    )


def collect_vendored_license_surfaces(root: Path, deps: set[Dependency]) -> None:
    for path in sorted(root.rglob("*LICENSE*")):
        if should_skip(path, root) or path.is_dir():
            continue
        if path.name in {"LICENSE.md"}:
            continue
        add_dependency(
            deps,
            root,
            ecosystem="vendored-license",
            name=path.stem,
            requirement="license file present",
            source=rel(path, root),
            manifest=path,
            evidence="license file",
        )


def write_json_report(
    output_dir: Path, dependencies: list[Dependency], warnings: list[str]
) -> None:
    output = {
        "schema_version": 1,
        "generated_by": Path(__file__).as_posix(),
        "dependency_count": len(dependencies),
        "counts_by_ecosystem": dict(Counter(dep.ecosystem for dep in dependencies)),
        "warnings": warnings,
        "dependencies": [asdict(dep) for dep in dependencies],
    }
    (output_dir / "oss-dependency-inventory.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def write_markdown_report(
    output_dir: Path, dependencies: list[Dependency], warnings: list[str]
) -> None:
    counts = Counter(dep.ecosystem for dep in dependencies)
    lines = [
        "# OSS Dependency Inventory",
        "",
        "This report is a non-blocking CI baseline for dependency visibility.",
        "It is intended to complement source-file SPDX/REUSE checks and a",
        "separate vulnerability scan artifact.",
        "",
        "## Summary",
        "",
        f"- Total entries: {len(dependencies)}",
    ]
    for ecosystem, count in sorted(counts.items()):
        lines.append(f"- {ecosystem}: {count}")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(
        [
            "",
            "## Dependency Surfaces",
            "",
            "| Ecosystem | Name | Requirement | Source | Manifest | Evidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for dep in dependencies:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(dep.ecosystem),
                    markdown_escape(dep.name),
                    markdown_escape(dep.requirement),
                    markdown_escape(dep.source),
                    markdown_escape(dep.manifest),
                    markdown_escape(dep.evidence),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Limitations And Follow-Up",
            "",
            "- This inventory is static and should be validated against the first",
            "  vulnerability/license scan artifact.",
            "- CMake FetchContent and vcpkg dependencies are included because they",
            "  may be missed by source-only package-manager scans.",
            "- The DepthAI vcpkg manifest is downloaded and hash-verified during",
            "  CMake configure, so its transitive packages should be reviewed from",
            "  the CI-generated manifest or a build-capture flow.",
            "- Keep the report non-blocking until false positives, vendored SDKs,",
            "  and intentionally bundled dependencies are triaged.",
            "",
        ]
    )
    (output_dir / "oss-dependency-inventory.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/oss_dependency_report"),
        help="Directory for generated report artifacts.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dependencies: set[Dependency] = set()
    warnings: list[str] = []
    variables = collect_cmake_variables(root)

    collect_python_requirements(root, dependencies)
    collect_pyproject_dependencies(root, dependencies, warnings)
    collect_npm_dependencies(root, dependencies, warnings)
    collect_fetchcontent_dependencies(root, dependencies, variables)
    collect_vcpkg_surface(root, dependencies, variables)
    collect_vendored_license_surfaces(root, dependencies)

    ordered = sorted(
        dependencies,
        key=lambda dep: (
            dep.ecosystem.lower(),
            dep.name.lower(),
            dep.manifest.lower(),
            dep.requirement.lower(),
        ),
    )
    write_json_report(output_dir, ordered, warnings)
    write_markdown_report(output_dir, ordered, warnings)

    print(f"Wrote {len(ordered)} dependency entries to {output_dir}")
    for ecosystem, count in sorted(Counter(dep.ecosystem for dep in ordered).items()):
        print(f"{ecosystem}: {count}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
