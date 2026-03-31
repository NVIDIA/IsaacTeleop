# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import sys
import time

import requests

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Discover custom fields on a GitHub Project v2.
_FIELDS_QUERY = """
query($owner: String!, $number: Int!) {
  %(owner_type)s(login: $owner) {
    projectV2(number: $number) {
      fields(first: 50) {
        nodes {
          ... on ProjectV2Field {
            name
            dataType
          }
          ... on ProjectV2IterationField {
            name
          }
          ... on ProjectV2SingleSelectField {
            name
            options { name }
          }
        }
      }
    }
  }
}
"""

# Fetch all project items with pagination.
_ITEMS_QUERY = """
query($owner: String!, $number: Int!, $cursor: String) {
  %(owner_type)s(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          content {
            ... on Issue {
              number
              title
              state
              url
              createdAt
              updatedAt
              milestone { title }
              labels(first: 20) {
                nodes { name }
              }
              assignees(first: 10) {
                nodes { login }
              }
            }
            ... on DraftIssue {
              title
              createdAt
              updatedAt
            }
          }
          fieldValues(first: 100) {
            nodes {
              ... on ProjectV2ItemFieldTextValue {
                field { ... on ProjectV2Field { name } }
                text
              }
              ... on ProjectV2ItemFieldNumberValue {
                field { ... on ProjectV2Field { name } }
                number
              }
              ... on ProjectV2ItemFieldDateValue {
                field { ... on ProjectV2Field { name } }
                date
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { name } }
                name
              }
              ... on ProjectV2ItemFieldIterationValue {
                field { ... on ProjectV2IterationField { name } }
                title
              }
            }
          }
        }
      }
    }
  }
}
"""

# Built-in field names that overlap with issue core fields — skip these from
# project field values to avoid duplicating columns like "Title" or "Assignees".
_BUILTIN_FIELD_NAMES = {"Title", "Assignees", "Labels", "Milestone", "Repository"}


def _graphql(token: str, query: str, variables: dict, retries: int = 3) -> dict:
    """Execute a GitHub GraphQL query with retry on transient errors."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    for attempt in range(retries):
        try:
            resp = requests.post(
                GITHUB_GRAPHQL_URL,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("Request failed (%s), retrying in %ds...", exc, wait)
                time.sleep(wait)
                continue
            raise
        if resp.status_code in (502, 503) and attempt < retries - 1:
            wait = 2 ** (attempt + 1)
            logger.warning(
                "GitHub API returned %d, retrying in %ds...", resp.status_code, wait
            )
            time.sleep(wait)
            continue
        if resp.status_code == 401:
            print(
                "Error: GitHub API returned 401 Unauthorized. "
                "Check that GITHUB_TOKEN is valid and has 'read:project' scope.",
                file=sys.stderr,
            )
            sys.exit(1)
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            print(f"Error: GitHub GraphQL errors: {data['errors']}", file=sys.stderr)
            sys.exit(1)
        return data
    return {}  # unreachable, but satisfies type checker


def _owner_key(owner_type: str) -> str:
    return "organization" if owner_type == "organization" else "user"


def fetch_project_fields(
    token: str, owner: str, owner_type: str, project_number: int
) -> list[str]:
    """Fetch custom field names from a GitHub Project v2.

    Returns field names excluding built-in fields that overlap with issue core
    fields (Title, Assignees, Labels, Milestone, Repository).
    """
    key = _owner_key(owner_type)
    query = _FIELDS_QUERY % {"owner_type": key}
    data = _graphql(token, query, {"owner": owner, "number": project_number})

    project = data["data"][key]["projectV2"]
    fields = project["fields"]["nodes"]

    custom_names = []
    for f in fields:
        name = f.get("name")
        if name and name not in _BUILTIN_FIELD_NAMES:
            custom_names.append(name)
    logger.info("Discovered project fields: %s", custom_names)
    return custom_names


def fetch_project_items(
    token: str, owner: str, owner_type: str, project_number: int
) -> list[dict]:
    """Fetch all items from a GitHub Project v2, with pagination.

    Returns a list of flat dicts, one per issue. DraftIssues are skipped.
    Each dict contains issue core fields and project custom field values.
    """
    key = _owner_key(owner_type)
    query = _ITEMS_QUERY % {"owner_type": key}

    all_items: list[dict] = []
    cursor: str | None = None

    while True:
        variables: dict = {"owner": owner, "number": project_number}
        if cursor:
            variables["cursor"] = cursor

        data = _graphql(token, query, variables)
        project = data["data"][key]["projectV2"]
        items_data = project["items"]

        for node in items_data["nodes"]:
            content = node.get("content")
            if not content or "number" not in content:
                # Skip DraftIssues and empty items
                continue

            item = {
                "#": content["number"],
                "Title": content["title"],
                "URL": content["url"],  # used for hyperlink, not a separate column
                "Assignees": ", ".join(
                    n["login"] for n in content.get("assignees", {}).get("nodes", [])
                ),
            }

            # Extract project custom field values
            for fv in node.get("fieldValues", {}).get("nodes", []):
                field_info = fv.get("field")
                if not field_info:
                    continue
                field_name = field_info.get("name", "")
                if field_name in _BUILTIN_FIELD_NAMES:
                    continue

                # Determine value based on field type (avoid `or` chain
                # which would drop falsy values like numeric 0)
                value = next(
                    (
                        v
                        for v in (
                            fv.get("text"),
                            fv.get("name"),  # SingleSelect
                            fv.get("title"),  # Iteration
                            fv.get("date"),
                            fv.get("number"),
                        )
                        if v is not None
                    ),
                    None,
                )
                if value is not None:
                    item[field_name] = str(value)

            all_items.append(item)

        logger.info("Fetched %d items so far...", len(all_items))

        page_info = items_data["pageInfo"]
        if page_info["hasNextPage"]:
            cursor = page_info["endCursor"]
        else:
            break

    return all_items
