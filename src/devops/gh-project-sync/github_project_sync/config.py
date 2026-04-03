# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

# Columns always overwritten from GitHub (locked for end users).
# "#" is rendered as a hyperlink to the GitHub issue URL.
READONLY_COLUMNS = [
    "#",
    "Title",
    "Assignees",
    "Status",
    "Priority",
    "Release",
    "Target date",
]

# Columns preserved across syncs (user-editable, unlocked)
EDITABLE_COLUMNS = [
    "Notes",
]

_PROJECT_URL_RE = re.compile(
    r"https://github\.com/(?P<type>orgs|users)/(?P<owner>[^/]+)/projects/(?P<number>\d+)"
)


@dataclass
class Config:
    github_token: str
    project_owner: str
    project_owner_type: str  # "organization" or "user"
    project_number: int
    google_sheet_id: str
    google_service_account_b64: str | None
    google_service_account_file: str | None


def parse_project_url(url: str) -> tuple[str, str, int]:
    """Parse a GitHub Project URL into (owner, owner_type, project_number).

    Accepts:
      - https://github.com/orgs/NVIDIA/projects/123
      - https://github.com/users/someone/projects/456
    """
    m = _PROJECT_URL_RE.match(url)
    if not m:
        print(
            f"Error: Invalid project URL: {url}\n"
            "Expected format: https://github.com/orgs/<owner>/projects/<number> "
            "or https://github.com/users/<owner>/projects/<number>",
            file=sys.stderr,
        )
        sys.exit(1)
    owner_type = "organization" if m.group("type") == "orgs" else "user"
    return m.group("owner"), owner_type, int(m.group("number"))


def load_config() -> Config:
    """Load and validate configuration from environment variables."""
    missing = []
    for var in ("GITHUB_TOKEN", "ISAAC_TELEOP_GITHUB_PROJECT_URL", "GOOGLE_SHEET_ID"):
        if not os.environ.get(var):
            missing.append(var)

    b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_B64")
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    # Google credentials are optional here — ADC / WIF may provide them
    # at runtime without any env vars. Validated later in get_google_credentials().

    if missing:
        print(
            f"Error: Missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    owner, owner_type, number = parse_project_url(
        os.environ["ISAAC_TELEOP_GITHUB_PROJECT_URL"]
    )

    return Config(
        github_token=os.environ["GITHUB_TOKEN"],
        project_owner=owner,
        project_owner_type=owner_type,
        project_number=number,
        google_sheet_id=os.environ["GOOGLE_SHEET_ID"],
        google_service_account_b64=b64,
        google_service_account_file=sa_file,
    )
