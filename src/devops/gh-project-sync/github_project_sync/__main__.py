# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging

from .config import load_config
from .github import fetch_project_items
from .sheets import get_google_credentials, sync_to_sheet


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config()

    # Fetch all project items
    print(
        f"Fetching items from {config.project_owner}/projects/"
        f"{config.project_number}..."
    )
    items = fetch_project_items(
        config.github_token,
        config.project_owner,
        config.project_owner_type,
        config.project_number,
    )
    print(f"Fetched {len(items)} issues from GitHub project.")

    if not items:
        print("No issues found. Nothing to sync.")
        return

    # Authenticate with Google Sheets
    credentials = get_google_credentials()

    sync_to_sheet(
        items=items,
        sheet_id=config.google_sheet_id,
        credentials=credentials,
    )

    print(f"Done. Synced {len(items)} issues to Google Sheet.")


if __name__ == "__main__":
    main()
