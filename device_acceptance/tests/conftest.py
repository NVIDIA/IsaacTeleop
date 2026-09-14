# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = REPO_ROOT / "design_agent-testing" / "synthetic-fixtures"


def fixtures_root() -> Path | None:
    """The fixture set is not in git, so its absence is normal, not an error.

    ``FULLBODY_FIXTURES`` overrides the default location, which matters when tests run
    from a worktree that does not carry the local-only directory.
    """
    override = os.environ.get("FULLBODY_FIXTURES")
    candidate = Path(override) if override else DEFAULT_FIXTURES
    return candidate if (candidate / "fixtures_index.json").is_file() else None


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    root = fixtures_root()
    if root is None:
        pytest.skip(
            "fixture set not found; set FULLBODY_FIXTURES to "
            "design_agent-testing/synthetic-fixtures"
        )
    return root


@pytest.fixture(scope="session")
def index(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "fixtures_index.json").read_text())
