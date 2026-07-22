# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_script("audit_oss_dependency_coverage")
collector = load_script("collect_oss_dependencies")


class DependencyCoverageTests(unittest.TestCase):
    def test_pyproject_extras_are_normalized_to_the_project_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pyproject = root / "pyproject.toml"
            pyproject.write_text(
                "[project]\n"
                'name = "sample"\n'
                'version = "1"\n'
                "dependencies = [\"demo[extra]>=2; python_version >= '3.11'\"]\n",
                encoding="utf-8",
            )
            entries = collector._parse_pyproject(pyproject, root)

        self.assertEqual(entries[0]["name"], "demo")
        self.assertEqual(entries[0]["version"], ">=2")
        self.assertEqual(entries[0]["source"], "python_version >= '3.11'")

    def test_lock_and_trace_evidence_resolve_direct_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "VERSION").write_text("1.4.0\n", encoding="utf-8")
            python_lock = root / "requirements.lock"
            python_lock.write_text("demo==2.3.4\n", encoding="utf-8")
            npm_root = root / "npm"
            npm_root.mkdir()
            (npm_root / "package-lock.json").write_text(
                json.dumps(
                    {
                        "lockfileVersion": 3,
                        "packages": {
                            "node_modules/widget": {
                                "name": "widget",
                                "version": "5.6.7",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            trace = root / "trace.jsonl"
            trace.write_text(
                json.dumps(
                    {
                        "cmd": "FetchContent_Declare",
                        "args": [
                            "library",
                            "GIT_REPOSITORY",
                            "https://example.com/library.git",
                            "GIT_TAG",
                            "0123456789abcdef0123456789abcdef01234567",
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            vcpkg_status = root / "status"
            vcpkg_status.write_text(
                "Package: archive\nVersion: 1.2.3\nStatus: install ok installed\n",
                encoding="utf-8",
            )

            resolved = {
                "python": audit.load_python_lock(python_lock),
                "npm": audit.load_npm_locks(npm_root),
                "cmake": audit.load_cmake_trace(trace, root / "build"),
                "vcpkg": audit.parse_vcpkg_status(vcpkg_status),
            }
            entries = [
                {"ecosystem": "python", "name": "demo", "path": "requirements.txt"},
                {"ecosystem": "npm", "name": "widget", "path": "package.json"},
                {"ecosystem": "cmake", "name": "library", "path": "CMakeLists.txt"},
            ]
            statuses = [
                audit.declaration_resolution(entry, resolved, [])[0]
                for entry in entries
            ]

        self.assertEqual(statuses, ["resolved", "resolved", "resolved"])
        self.assertIn("archive", resolved["vcpkg"])

    def test_unknown_package_manager_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
            manifests = audit.unsupported_manifests(root)

        self.assertEqual(manifests, ["Cargo.toml"])


if __name__ == "__main__":
    unittest.main()
