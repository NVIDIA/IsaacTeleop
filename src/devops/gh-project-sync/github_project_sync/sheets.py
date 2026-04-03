# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
import gspread
from google.oauth2.service_account import Credentials

from .config import EDITABLE_COLUMNS, READONLY_COLUMNS

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_NO_RELEASE = "Backlog"
_RELEASE_PREFIX = "Release "  # stripped from GitHub field values for tab names
ALL_COLUMNS = READONLY_COLUMNS + EDITABLE_COLUMNS


# ─── Data structures ─────────────────────────────────────────────────────────


@dataclass
class _ExistingIssue:
    """Tracks where an issue currently lives across all tabs."""

    tab_name: str
    row_idx: int  # 1-based
    editable_data: dict[str, str] = field(default_factory=dict)


# ─── Google auth ──────────────────────────────────────────────────────────────


def get_google_credentials() -> Credentials:
    """Build Google credentials, trying in order:

    1. GOOGLE_SERVICE_ACCOUNT_B64 — base64-encoded service account JSON
    2. GOOGLE_SERVICE_ACCOUNT_FILE — path to service account JSON file
    3. Application Default Credentials (ADC) — used by GitHub Actions WIF
       and ``gcloud auth application-default login`` for local dev
    """
    b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_B64")
    if b64:
        info = json.loads(base64.b64decode(b64))
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if sa_file:
        return Credentials.from_service_account_file(sa_file, scopes=SCOPES)

    # Fall back to ADC (Workload Identity Federation, gcloud login, etc.)
    try:
        import google.auth

        credentials, _ = google.auth.default(scopes=SCOPES)
        return credentials
    except google.auth.exceptions.DefaultCredentialsError:
        pass

    print(
        "Error: No Google credentials found. Set one of:\n"
        "  - GOOGLE_SERVICE_ACCOUNT_B64 (base64 JSON)\n"
        "  - GOOGLE_SERVICE_ACCOUNT_FILE (path to JSON)\n"
        "  - GOOGLE_APPLICATION_CREDENTIALS (ADC / WIF)\n"
        "  - Or run: gcloud auth application-default login "
        "--scopes=https://www.googleapis.com/auth/spreadsheets",
        file=sys.stderr,
    )
    sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _escape_cell(value: str) -> str:
    """Prefix a leading single-quote to prevent formula injection in Sheets.

    Google Sheets interprets cells starting with =, +, -, or @ as formulas
    when written with value_input_option=USER_ENTERED.
    """
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _release_tab_name(release: str) -> str:
    """Convert a GitHub Release field value to a tab name.

    Strips the 'Release ' prefix (e.g. 'Release 1.1.x' → '1.1.x').
    """
    if not release:
        return _NO_RELEASE
    if release.startswith(_RELEASE_PREFIX):
        return release[len(_RELEASE_PREFIX) :]
    return release


def _issue_hyperlink(number: int, url: str) -> str:
    return f'=HYPERLINK("{url}", {number})'


def _parse_issue_number(raw: str) -> int | None:
    """Extract issue number from a cell value (plain int or displayed hyperlink)."""
    try:
        return int(str(raw).replace("[REMOVED] ", "").strip())
    except ValueError:
        return None


def _read_tab_issues(
    worksheet: gspread.Worksheet, col_index: dict[str, int]
) -> tuple[list[list[str]], dict[int, int]]:
    """Read all data from a tab and return (all_values, {issue_num: row_idx})."""
    data = worksheet.get_all_values()
    issue_col = col_index.get("#")
    issue_map: dict[int, int] = {}
    if issue_col is not None:
        for row_idx, row in enumerate(data[1:], start=2):
            if issue_col < len(row) and row[issue_col]:
                num = _parse_issue_number(row[issue_col])
                if num is not None:
                    issue_map[num] = row_idx
    return data, issue_map


# ─── Top-level sync ──────────────────────────────────────────────────────────


def sync_to_sheet(
    items: list[dict],
    sheet_id: str,
    credentials: Credentials,
) -> None:
    """Sync GitHub project items to per-Release tabs in a Google Sheet.

    Each unique Release value gets its own tab.  When an issue's Release
    changes, the row is moved to the new tab while preserving editable data.
    Issues removed from the project are marked [REMOVED] with strikethrough.
    """
    gc = gspread.authorize(credentials)
    spreadsheet = gc.open_by_key(sheet_id)

    # ── 1. Group items by Release ────────────────────────────────────────
    release_groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        tab = _release_tab_name(item.get("Release", ""))
        release_groups[tab].append(item)

    logger.info(
        "Releases: %s",
        {r: len(v) for r, v in sorted(release_groups.items())},
    )

    # ── 2. Scan all existing data tabs → global issue map ────────────────
    global_map = _scan_all_tabs(spreadsheet)
    all_github_nums = {item["#"] for item in items}

    # ── 3. Sync each release tab ────────────────────────────────────────
    for release in sorted(release_groups):
        group = release_groups[release]
        worksheet = _get_or_create_tab(spreadsheet, release)
        _sync_tab(spreadsheet, worksheet, group, global_map, all_github_nums)

    # ── 4. Mark removed issues in tabs not covered above ─────────────────
    # (issues in tabs that no longer have any items from this sync)
    covered_tabs = set(release_groups.keys())
    for num, ei in global_map.items():
        if num not in all_github_nums and ei.tab_name not in covered_tabs:
            # This issue's tab wasn't processed above — mark it there
            try:
                ws = spreadsheet.worksheet(ei.tab_name)
            except gspread.WorksheetNotFound:
                continue
            _mark_removed_in_tab(ws, {num: ei})

    # ── 5. Trim empty rows and format every data tab ───────────────────
    for ws in spreadsheet.worksheets():
        row1 = ws.row_values(1)
        if row1 and row1[: len(ALL_COLUMNS)] == ALL_COLUMNS:
            data_rows = len(ws.get_all_values())  # header + data, no blanks
            if ws.row_count > data_rows:
                ws.resize(rows=data_rows)
            ci = {name: i for i, name in enumerate(row1)}
            _apply_formatting(spreadsheet, ws, row1, ci, data_rows)


# ─── Scan ─────────────────────────────────────────────────────────────────────


def _scan_all_tabs(
    spreadsheet: gspread.Spreadsheet,
) -> dict[int, _ExistingIssue]:
    """Scan every data tab and return {issue_num: _ExistingIssue}."""
    global_map: dict[int, _ExistingIssue] = {}
    col_index = {name: i for i, name in enumerate(ALL_COLUMNS)}
    issue_col = col_index["#"]

    for ws in spreadsheet.worksheets():
        data = ws.get_all_values()
        if not data or data[0] != ALL_COLUMNS:
            continue  # not a managed tab

        for row_idx, row in enumerate(data[1:], start=2):
            if issue_col >= len(row) or not row[issue_col]:
                continue
            num = _parse_issue_number(row[issue_col])
            if num is None:
                continue
            editable = {}
            for col_name in EDITABLE_COLUMNS:
                ci = col_index.get(col_name)
                if ci is not None and ci < len(row):
                    editable[col_name] = row[ci]
            global_map[num] = _ExistingIssue(
                tab_name=ws.title,
                row_idx=row_idx,
                editable_data=editable,
            )

    logger.info("Scanned %d existing issues across all tabs.", len(global_map))
    return global_map


# ─── Per-tab sync ─────────────────────────────────────────────────────────────


def _get_or_create_tab(
    spreadsheet: gspread.Spreadsheet, release: str
) -> gspread.Worksheet:
    """Return the worksheet for a release, creating it if needed."""
    try:
        return spreadsheet.worksheet(release)
    except gspread.WorksheetNotFound:
        logger.info("Creating tab: %s", release)
        ws = spreadsheet.add_worksheet(title=release, rows=100, cols=len(ALL_COLUMNS))
        ws.append_row(ALL_COLUMNS)
        return ws


def _sync_tab(
    spreadsheet: gspread.Spreadsheet,
    worksheet: gspread.Worksheet,
    group_items: list[dict],
    global_map: dict[int, _ExistingIssue],
    all_github_nums: set[int],
) -> None:
    """Sync a list of issues into a single tab."""
    tab_name = worksheet.title
    col_index = {name: i for i, name in enumerate(ALL_COLUMNS)}

    # Read current tab data
    data, tab_issues = _read_tab_issues(worksheet, col_index)

    # Ensure headers exist
    if not data:
        worksheet.append_row(ALL_COLUMNS)
        data = [ALL_COLUMNS]

    target_nums = {item["#"] for item in group_items}
    target_map = {item["#"]: item for item in group_items}

    to_update = target_nums & set(tab_issues.keys())
    to_add = target_nums - set(tab_issues.keys())
    to_delete = {
        n for n in tab_issues if n not in target_nums and n in all_github_nums
    }  # moved out
    to_remove = {
        n for n in tab_issues if n not in target_nums and n not in all_github_nums
    }  # gone from project

    logger.info(
        "[%s] update=%d add=%d move-out=%d remove=%d",
        tab_name,
        len(to_update),
        len(to_add),
        len(to_delete),
        len(to_remove),
    )

    # ── Batch update existing rows (read-only columns only) ──────────────
    if to_update:
        batch = []
        unstrike_rows = set()
        for num in to_update:
            item = target_map[num]
            row_idx = tab_issues[num]
            for col_name in READONLY_COLUMNS:
                ci = col_index.get(col_name)
                if ci is None:
                    continue
                cell = gspread.utils.rowcol_to_a1(row_idx, ci + 1)
                if col_name == "#":
                    val = _issue_hyperlink(item["#"], item["URL"])
                else:
                    val = _escape_cell(str(item.get(col_name, "")))
                batch.append({"range": cell, "values": [[val]]})
            # Track rows that might have stale [REMOVED] strikethrough
            title_ci = col_index.get("Title")
            if title_ci is not None:
                row_data = data[row_idx - 1] if row_idx - 1 < len(data) else []
                if title_ci < len(row_data) and "[REMOVED]" in row_data[title_ci]:
                    unstrike_rows.add(row_idx)
        if batch:
            worksheet.batch_update(batch, value_input_option="USER_ENTERED")
        # Clear strikethrough on restored rows
        for row_idx in unstrike_rows:
            r = (
                f"{gspread.utils.rowcol_to_a1(row_idx, 1)}:"
                f"{gspread.utils.rowcol_to_a1(row_idx, len(ALL_COLUMNS))}"
            )
            worksheet.format(r, {"textFormat": {"strikethrough": False}})

    # ── Append new / moved-in rows ───────────────────────────────────────
    if to_add:
        new_rows = []
        for num in sorted(to_add):
            item = target_map[num]
            row = [""] * len(ALL_COLUMNS)
            for col_name in READONLY_COLUMNS:
                ci = col_index.get(col_name)
                if ci is None:
                    continue
                if col_name == "#":
                    row[ci] = _issue_hyperlink(item["#"], item["URL"])
                else:
                    row[ci] = _escape_cell(str(item.get(col_name, "")))
            # Carry over editable data if this issue moved from another tab
            if num in global_map:
                for col_name in EDITABLE_COLUMNS:
                    ci = col_index.get(col_name)
                    if ci is not None:
                        row[ci] = _escape_cell(
                            global_map[num].editable_data.get(col_name, "")
                        )
            new_rows.append(row)
        worksheet.append_rows(new_rows, value_input_option="USER_ENTERED")

    # ── Mark removed issues ──────────────────────────────────────────────
    if to_remove:
        removed_map = {n: _ExistingIssue(tab_name, tab_issues[n]) for n in to_remove}
        _mark_removed_in_tab(worksheet, removed_map)

    # ── Delete moved-out rows (bottom-to-top to keep indices valid) ──────
    if to_delete:
        rows_to_del = sorted((tab_issues[n] for n in to_delete), reverse=True)
        for row_idx in rows_to_del:
            worksheet.delete_rows(row_idx)
        logger.info("[%s] Deleted %d moved-out rows.", tab_name, len(rows_to_del))


def _mark_removed_in_tab(
    worksheet: gspread.Worksheet,
    removed: dict[int, _ExistingIssue],
) -> None:
    """Mark issues as [REMOVED] with strikethrough in a tab."""
    col_index = {name: i for i, name in enumerate(ALL_COLUMNS)}
    title_col = col_index.get("Title")
    if title_col is None:
        return

    data = worksheet.get_all_values()
    batch = []
    format_rows = []

    for num, ei in removed.items():
        if ei.row_idx - 1 >= len(data):
            continue
        row_data = data[ei.row_idx - 1]
        if title_col < len(row_data) and row_data[title_col].startswith("[REMOVED]"):
            continue  # already marked
        old_title = row_data[title_col] if title_col < len(row_data) else ""
        cell = gspread.utils.rowcol_to_a1(ei.row_idx, title_col + 1)
        batch.append({"range": cell, "values": [[f"[REMOVED] {old_title}"]]})
        format_rows.append(ei.row_idx)

    if batch:
        worksheet.batch_update(batch)

    num_cols = len(ALL_COLUMNS)
    for row_idx in format_rows:
        r = (
            f"{gspread.utils.rowcol_to_a1(row_idx, 1)}:"
            f"{gspread.utils.rowcol_to_a1(row_idx, num_cols)}"
        )
        worksheet.format(r, {"textFormat": {"strikethrough": True}})

    if format_rows:
        logger.info(
            "[%s] Marked %d issues as removed.", worksheet.title, len(format_rows)
        )


# ─── Formatting ───────────────────────────────────────────────────────────────

_COLUMN_WIDTHS = {
    "#": 45,
    "Title": 350,
    "Assignees": 150,
    "Status": 100,
    "Priority": 80,
    "Release": 100,
    "Target date": 110,
    "Notes": 300,
}

_HEADER_BG = {"red": 0.30, "green": 0.69, "blue": 0.31}  # green
_HEADER_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}  # white text

_CENTERED_COLUMNS = {
    "#",
    "Assignees",
    "Status",
    "Priority",
    "Release",
    "Target date",
}
_READONLY_BG = {
    "red": 0.94,
    "green": 0.94,
    "blue": 0.96,
}  # light cool grey (table band 2)
_RO_BAND_ODD = {
    "red": 0.91,
    "green": 0.91,
    "blue": 0.93,
}  # read-only tint on white rows
_RO_BAND_EVEN = {
    "red": 0.87,
    "green": 0.87,
    "blue": 0.90,
}  # read-only tint on grey rows
_RO_TEXT = {
    "red": 0.0,
    "green": 0.0,
    "blue": 0.0,
}  # darker text for read-only columns
_LINK_COLOR = {"red": 0.06, "green": 0.36, "blue": 0.72}  # blue hyperlink (#105CB8)


def _apply_formatting(
    spreadsheet: gspread.Spreadsheet,
    worksheet: gspread.Worksheet,
    headers: list[str],
    col_index: dict[str, int],
    row_count: int = 1000,
) -> None:
    """Apply professional formatting and column protection in one batch call.

    Uses Google Sheets Table API for structured table (filter dropdowns,
    banding).  On first run ``addTable`` creates the table; on subsequent
    runs ``updateTable`` adjusts the range without touching data.
    Cell-level overrides (centering, wrapping, widths) are applied after.
    """
    sid = worksheet.id
    num_cols = len(headers)
    reqs: list[dict] = []

    meta = spreadsheet.fetch_sheet_metadata()

    # ── 1. Table: create or update ───────────────────────────────────────
    existing_table_id = None
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != sid:
            continue
        for tbl in sheet.get("tables", []):
            existing_table_id = tbl["tableId"]
            break

    table_range = {
        "sheetId": sid,
        "startRowIndex": 0,
        "endRowIndex": row_count,
        "startColumnIndex": 0,
        "endColumnIndex": num_cols,
    }

    if existing_table_id:
        # Table exists — just update the range (e.g. new rows were appended)
        reqs.append(
            {
                "updateTable": {
                    "table": {
                        "tableId": existing_table_id,
                        "range": table_range,
                    },
                    "fields": "range",
                }
            }
        )
    else:
        # First run — create the table
        _COL_TYPES = {
            "#": "DOUBLE",
            "Target date": "DATE",
        }  # everything else defaults to TEXT
        column_props = [
            {
                "columnIndex": i,
                "columnName": name,
                "columnType": _COL_TYPES.get(name, "TEXT"),
            }
            for i, name in enumerate(headers)
        ]
        reqs.append(
            {
                "addTable": {
                    "table": {
                        "name": "sync_"
                        + re.sub(r"[^A-Za-z0-9_]", "_", worksheet.title),
                        "range": table_range,
                        "columnProperties": column_props,
                        "rowsProperties": {
                            "headerColorStyle": {"rgbColor": _HEADER_BG},
                            "firstBandColorStyle": {
                                "rgbColor": {"red": 1, "green": 1, "blue": 1},
                            },
                            "secondBandColorStyle": {"rgbColor": _READONLY_BG},
                        },
                    }
                }
            }
        )

    # ── 2. Freeze header row ─────────────────────────────────────────────
    reqs.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )

    # ── 3. Header: bold white text, centered ─────────────────────────────
    reqs.append(
        {
            "repeatCell": {
                "range": _range(sid, 0, 1, 0, num_cols),
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": True,
                            "fontSize": 10,
                            "foregroundColor": _HEADER_FG,
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": (
                    "userEnteredFormat(textFormat,"
                    "horizontalAlignment,verticalAlignment)"
                ),
            }
        }
    )

    # ── 4. Column widths ─────────────────────────────────────────────────
    for col_name, width in _COLUMN_WIDTHS.items():
        if col_name not in col_index:
            continue
        ci = col_index[col_name]
        reqs.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "COLUMNS",
                        "startIndex": ci,
                        "endIndex": ci + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    # ── 5. Text wrapping for Title and Notes ─────────────────────────────
    for col_name in ("Title", "Notes"):
        if col_name not in col_index:
            continue
        ci = col_index[col_name]
        reqs.append(
            {
                "repeatCell": {
                    "range": _range(sid, 1, None, ci, ci + 1),
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            }
        )

    # ── 6. Read-only columns: tinted background preserving alternating rows
    #    Table banding: odd rows = white, even rows = _READONLY_BG
    #    Read-only tint: odd rows = _RO_BAND_ODD, even rows = _RO_BAND_EVEN
    #    Delete existing conditional format rules first to avoid duplicates.
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != sid:
            continue
        existing_cf = sheet.get("conditionalFormats", [])
        # Delete in reverse index order so indices stay valid
        for i in range(len(existing_cf) - 1, -1, -1):
            reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})

    ro_cols = sorted(col_index[c] for c in READONLY_COLUMNS if c in col_index)
    if ro_cols:
        # Group consecutive columns into ranges for fewer requests
        for ci in ro_cols:
            col_range = _range(sid, 1, None, ci, ci + 1)
            # Odd data rows (ROW() is even because header is row 1)
            reqs.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [col_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [
                                        {"userEnteredValue": ("=ISEVEN(ROW())")}
                                    ],
                                },
                                "format": {
                                    "backgroundColor": _RO_BAND_ODD,
                                },
                            },
                        },
                        "index": 0,
                    }
                }
            )
            # Even data rows
            reqs.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [col_range],
                            "booleanRule": {
                                "condition": {
                                    "type": "CUSTOM_FORMULA",
                                    "values": [{"userEnteredValue": ("=ISODD(ROW())")}],
                                },
                                "format": {
                                    "backgroundColor": _RO_BAND_EVEN,
                                },
                            },
                        },
                        "index": 0,
                    }
                }
            )

    # ── 7. Vertical divider between read-only and editable columns ───────
    ro_indices = [col_index[c] for c in READONLY_COLUMNS if c in col_index]
    ed_indices = [col_index[c] for c in EDITABLE_COLUMNS if c in col_index]
    if ro_indices and ed_indices:
        divider_col = max(ro_indices) + 1  # first editable column
        reqs.append(
            {
                "updateBorders": {
                    "range": _range(sid, 0, None, divider_col, divider_col + 1),
                    "left": {
                        "style": "SOLID_THICK",
                        "color": {"red": 0.4, "green": 0.4, "blue": 0.4},
                    },
                }
            }
        )

    # ── 8. Center-align specific columns ─────────────────────────────────
    for col_name in _CENTERED_COLUMNS:
        if col_name not in col_index:
            continue
        ci = col_index[col_name]
        reqs.append(
            {
                "repeatCell": {
                    "range": _range(sid, 1, None, ci, ci + 1),
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            }
        )

    # ── 9. Read-only text color (darker for contrast) ─────────────────────
    for col_name in READONLY_COLUMNS:
        if col_name not in col_index:
            continue
        ci = col_index[col_name]
        fg = _LINK_COLOR if col_name == "#" else _RO_TEXT
        reqs.append(
            {
                "repeatCell": {
                    "range": _range(sid, 1, None, ci, ci + 1),
                    "cell": {
                        "userEnteredFormat": {"textFormat": {"foregroundColor": fg}}
                    },
                    "fields": "userEnteredFormat.textFormat.foregroundColor",
                }
            }
        )

    # ── 10. Column protection (warning-only) ─────────────────────────────
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != sid:
            continue
        for pp in sheet.get("protectedRanges", []):
            if pp.get("description", "").startswith("github-project-sync:"):
                reqs.append(
                    {
                        "deleteProtectedRange": {
                            "protectedRangeId": pp["protectedRangeId"]
                        }
                    }
                )

    ro_indices = sorted(col_index[c] for c in READONLY_COLUMNS if c in col_index)
    for ci in ro_indices:
        reqs.append(
            {
                "addProtectedRange": {
                    "protectedRange": {
                        "range": {
                            "sheetId": sid,
                            "startColumnIndex": ci,
                            "endColumnIndex": ci + 1,
                        },
                        "description": f"github-project-sync: {headers[ci]}",
                        "warningOnly": True,
                    }
                }
            }
        )

    if reqs:
        spreadsheet.batch_update({"requests": reqs})
    logger.info("[%s] Applied formatting and protection.", worksheet.title)


def _range(
    sheet_id: int,
    start_row: int,
    end_row: int | None,
    start_col: int,
    end_col: int,
) -> dict:
    r: dict = {
        "sheetId": sheet_id,
        "startRowIndex": start_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }
    if end_row is not None:
        r["endRowIndex"] = end_row
    return r
