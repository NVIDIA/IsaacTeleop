#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Merge resolver evidence into CycloneDX and fail closed on coverage gaps."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4


PYTHON_LOCK_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^;\s]+)")
CONCRETE_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
UNSUPPORTED_MANIFEST_NAMES = {
    "Cargo.lock",
    "Cargo.toml",
    "Gemfile",
    "Gemfile.lock",
    "Pipfile",
    "Pipfile.lock",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "composer.lock",
    "conda-lock.yaml",
    "conda-lock.yml",
    "environment.yaml",
    "environment.yml",
    "go.mod",
    "go.sum",
    "gradle.lockfile",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pom.xml",
    "uv.lock",
    "yarn.lock",
}
IGNORED_DIRS = {
    ".git",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "oss-report",
    "venv",
}


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def component(
    ecosystem: str,
    name: str,
    version: str,
    evidence: str,
    source: str = "",
) -> dict[str, Any]:
    encoded_name = quote(name, safe="/")
    encoded_version = quote(version, safe="")
    purl_type = {
        "npm": "npm",
        "python": "pypi",
        "vcpkg": "generic",
        "cmake": "generic",
        "container": "oci",
        "github-actions": "github",
    }.get(ecosystem, "generic")
    purl = f"pkg:{purl_type}/{encoded_name}@{encoded_version}"
    properties = [
        {"name": "isaacteleop:dependency:ecosystem", "value": ecosystem},
        {"name": "isaacteleop:dependency:evidence", "value": evidence},
    ]
    if source:
        properties.append({"name": "isaacteleop:dependency:source", "value": source})
    return {
        "type": "library",
        "bom-ref": purl,
        "name": name,
        "version": version,
        "purl": purl,
        "properties": properties,
    }


def load_python_lock(path: Path) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return resolved
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = PYTHON_LOCK_RE.match(raw_line.strip())
        if not match:
            continue
        name, version = match.groups()
        resolved[normalized_name(name)] = component(
            "python", name, version, f"uv lock {path.name}"
        )
    return resolved


def npm_name_from_package_path(package_path: str, metadata: dict[str, Any]) -> str:
    if metadata.get("name"):
        return str(metadata["name"])
    marker = "node_modules/"
    if marker not in package_path:
        return ""
    return package_path.rsplit(marker, maxsplit=1)[1]


def load_npm_locks(root: Path) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return resolved
    for path in sorted(root.rglob("package-lock.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for package_path, metadata in (data.get("packages", {}) or {}).items():
            name = npm_name_from_package_path(package_path, metadata)
            version = str(metadata.get("version", ""))
            if not name or not version:
                continue
            resolved[normalized_name(name)] = component(
                "npm", name, version, f"npm lock {path.name}"
            )
    return resolved


def parse_vcpkg_status(path: Path) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return resolved
    for paragraph in re.split(r"\r?\n\r?\n", path.read_text(encoding="utf-8")):
        fields: dict[str, str] = {}
        for line in paragraph.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key.strip()] = value.strip()
        name = fields.get("Package", "")
        version = fields.get("Version", "")
        if name and version and fields.get("Status", "").endswith(" installed"):
            resolved[normalized_name(name)] = component(
                "vcpkg", name, version, f"vcpkg status {path.name}"
            )
    return resolved


def trace_fields(args: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    keys = {
        "GIT_REPOSITORY",
        "GIT_TAG",
        "NAME",
        "URL",
        "URL_HASH",
        "VERSION",
    }
    index = 1
    while index < len(args):
        key = args[index].upper()
        if key in keys and index + 1 < len(args):
            fields[key] = args[index + 1]
            index += 2
        else:
            index += 1
    return fields


def git_commit(path: Path) -> str:
    if not path.exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and CONCRETE_COMMIT_RE.match(value) else ""


def load_cmake_trace(trace_path: Path, build_dir: Path) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    if not trace_path.exists():
        return resolved
    for raw_line in trace_path.read_text(
        encoding="utf-8", errors="ignore"
    ).splitlines():
        if not raw_line.startswith("{"):
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        command_name = str(event.get("cmd", "")).lower()
        if command_name not in {
            "fetchcontent_declare",
            "externalproject_add",
            "cpmaddpackage",
        }:
            continue
        args = [str(value) for value in event.get("args", [])]
        if not args:
            continue
        fields = trace_fields(args)
        name = fields.get("NAME") or args[0]
        source = fields.get("GIT_REPOSITORY") or fields.get("URL") or ""
        version = fields.get("GIT_TAG") or fields.get("VERSION") or ""
        populated_commit = git_commit(build_dir / "_deps" / f"{name.lower()}-src")
        if populated_commit:
            version = populated_commit
        elif fields.get("URL_HASH"):
            version = fields["URL_HASH"]
        if not version or "${" in version or "${" in source:
            continue
        resolved[normalized_name(name)] = component(
            "cmake",
            name,
            version,
            f"expanded CMake trace {trace_path.name}",
            source,
        )
    return resolved


def load_exclusions(
    inputs_path: Path, policy_path: Path | None
) -> list[dict[str, str]]:
    exclusions: list[dict[str, str]] = []
    if inputs_path.exists():
        inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
        exclusions.extend(inputs.get("generated_exclusions", []) or [])
    if policy_path and policy_path.exists():
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        exclusions.extend(policy.get("exclusions", []) or [])
    return exclusions


def find_exclusion(
    entry: dict[str, Any], exclusions: list[dict[str, str]]
) -> dict[str, str] | None:
    for exclusion in exclusions:
        if exclusion.get("ecosystem") != entry["ecosystem"]:
            continue
        if normalized_name(exclusion.get("name", "")) != normalized_name(entry["name"]):
            continue
        if exclusion.get("path") and exclusion["path"] != entry["path"]:
            continue
        if exclusion.get("reason"):
            return exclusion
    return None


def unsupported_manifests(repo_root: Path) -> list[str]:
    paths: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.name in UNSUPPORTED_MANIFEST_NAMES:
            paths.append(path.relative_to(repo_root).as_posix())
    return sorted(paths)


def declaration_resolution(
    entry: dict[str, Any],
    resolved: dict[str, dict[str, dict[str, Any]]],
    exclusions: list[dict[str, str]],
) -> tuple[str, str, dict[str, Any] | None]:
    exclusion = find_exclusion(entry, exclusions)
    if exclusion:
        return "excluded", exclusion["reason"], None

    ecosystem = entry["ecosystem"]
    name = normalized_name(entry["name"])
    if ecosystem in resolved and name in resolved[ecosystem]:
        item = resolved[ecosystem][name]
        return "resolved", item["version"], item
    if ecosystem in {"github-actions", "container"}:
        if entry["name"] in {"base", "scratch"}:
            return "excluded", "Docker stage alias or empty scratch image.", None
        version = entry.get("version", "")
        if version and "${" not in version and "$" not in version:
            item = component(ecosystem, entry["name"], version, "declared reference")
            return "resolved", version, item
    return "unresolved", "No concrete resolver evidence or named exclusion.", None


def merge_components(
    base_sbom: dict[str, Any], components: list[dict[str, Any]], repo_root: Path
) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for item in base_sbom.get("components", []) or []:
        key = item.get("purl") or item.get("bom-ref")
        if key:
            merged[str(key)] = item
    for item in components:
        merged[item["purl"]] = item
    version_path = repo_root / "VERSION"
    project_version = version_path.read_text(encoding="utf-8").strip()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "IsaacTeleop OSS dependency coverage audit",
                        "version": "1",
                    }
                ]
            },
            "component": {
                "type": "application",
                "name": "IsaacTeleop",
                "version": project_version,
            },
        },
        "components": sorted(
            merged.values(),
            key=lambda item: (item.get("name", ""), item.get("version", "")),
        ),
    }


def write_summary(report: dict[str, Any], path: Path) -> None:
    counts = Counter(record["status"] for record in report["declarations"])
    lines = [
        "# OSS dependency resolution coverage",
        "",
        f"- Declared references: `{len(report['declarations'])}`",
        f"- Resolved declarations: `{counts['resolved']}`",
        f"- Explicit exclusions: `{counts['excluded']}`",
        f"- Unresolved declarations: `{counts['unresolved']}`",
        f"- Resolved transitive components: `{report['resolved_component_count']}`",
        f"- Unsupported manifests: `{len(report['unsupported_manifests'])}`",
        "",
    ]
    if report["unsupported_manifests"]:
        lines.extend(["## Unsupported manifests", ""])
        lines.extend(f"- `{item}`" for item in report["unsupported_manifests"])
        lines.append("")
    gaps = [item for item in report["declarations"] if item["status"] == "unresolved"]
    if gaps:
        lines.extend(["## Unresolved declarations", ""])
        lines.extend(
            f"- `{item['ecosystem']}` `{item['name']}` in `{item['path']}`"
            for item in gaps
        )
        lines.append("")
    exclusions = [
        item for item in report["declarations"] if item["status"] == "excluded"
    ]
    if exclusions:
        lines.extend(["## Explicit exclusions", ""])
        lines.extend(
            f"- `{item['ecosystem']}` `{item['name']}` in `{item['path']}`: {item['detail']}"
            for item in exclusions
        )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--resolution-inputs", type=Path, required=True)
    parser.add_argument("--python-lock", type=Path, required=True)
    parser.add_argument("--npm-root", type=Path, required=True)
    parser.add_argument("--cmake-trace", type=Path, required=True)
    parser.add_argument("--cmake-build-dir", type=Path, required=True)
    parser.add_argument("--vcpkg-status", type=Path, required=True)
    parser.add_argument("--base-sbom", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path)
    parser.add_argument("--output-sbom", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--fail-on-gaps", action="store_true")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    base_sbom = json.loads(args.base_sbom.read_text(encoding="utf-8"))
    resolved = {
        "python": load_python_lock(args.python_lock),
        "npm": load_npm_locks(args.npm_root),
        "cmake": load_cmake_trace(args.cmake_trace, args.cmake_build_dir),
        "vcpkg": parse_vcpkg_status(args.vcpkg_status),
    }
    exclusions = load_exclusions(args.resolution_inputs, args.exclusions)
    declarations: list[dict[str, Any]] = []
    used_components: list[dict[str, Any]] = []
    for entry in inventory["dependencies"]:
        if entry["manifest_type"] == "parse-error":
            declarations.append(
                {
                    **entry,
                    "status": "unresolved",
                    "detail": "Manifest parse error.",
                }
            )
            continue
        status, detail, resolved_component = declaration_resolution(
            entry, resolved, exclusions
        )
        declarations.append({**entry, "status": status, "detail": detail})
        if resolved_component:
            used_components.append(resolved_component)

    for ecosystem_components in resolved.values():
        used_components.extend(ecosystem_components.values())
    unsupported = unsupported_manifests(repo_root)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "declarations": declarations,
        "unsupported_manifests": unsupported,
        "resolved_component_count": len(
            {item["purl"] for item in used_components if item.get("purl")}
        ),
    }
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_summary(report, args.output_summary)
    merged_sbom = merge_components(base_sbom, used_components, repo_root)
    args.output_sbom.write_text(
        json.dumps(merged_sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    has_gaps = any(item["status"] == "unresolved" for item in declarations)
    has_gaps = has_gaps or bool(unsupported)
    return 2 if args.fail_on_gaps and has_gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
