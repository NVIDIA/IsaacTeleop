#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Read-only lookups over the Ecosystem partner data, for the partner-card skill.

Never writes. Records are edited as text so partners.yaml keeps its comment header,
section separators, and block scalars, all of which a YAML round-trip would destroy.

``validate`` imports the Sphinx extension's own checker rather than restating the
rules, so this cannot drift from what the docs build enforces.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFDIR = os.path.join(REPO, "docs", "source")
DATA = os.path.join(CONFDIR, "_data", "partners.yaml")
LOGO_DIR = os.path.join(CONFDIR, "_static", "partner-logos")
EXT_DIR = os.path.join(CONFDIR, "_ext")
BUILT_PAGE = os.path.join(
    REPO, "docs", "build", "current", "overview", "ecosystem.html"
)

# Anything below this looks like a different company rather than a typo.
NEAR_MATCH = 0.6

_ISSUE_RE = re.compile(r"/(?:issues|pull)/(\d+)/?$")

# An SVG is executable text, and these ship inside the built docs. Namespace
# declarations are not flagged: only attributes that actually fetch something.
_SVG_UNSAFE = (
    (re.compile(r"<script\b", re.I), "contains <script>"),
    (re.compile(r"<foreignObject\b", re.I), "contains <foreignObject>"),
    (re.compile(r"<!ENTITY\b", re.I), "declares an XML entity"),
    (re.compile(r"\son\w+\s*=", re.I), "has an inline event handler"),
    (
        re.compile(r"(?:xlink:)?href\s*=\s*[\"']\s*https?://", re.I),
        "links to a remote resource",
    ),
    (
        re.compile(r"url\(\s*[\"']?\s*https?://", re.I),
        "fetches a remote resource in CSS",
    ),
)


def _die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _ext():
    """The docs extension, so section names and rules come from one place."""
    sys.path.insert(0, EXT_DIR)
    try:
        import partner_grid
    except ImportError as exc:
        _die(f"cannot import partner_grid from {EXT_DIR}: {exc}")
    return partner_grid


def _load_raw() -> list[dict]:
    """Parse the YAML without validating, so lookups still work mid-edit."""
    try:
        import yaml
    except ImportError:
        _die(
            "PyYAML missing. Run with the docs environment, e.g. docs/.venv/bin/python"
        )
    if not os.path.isfile(DATA):
        _die(f"{DATA} not found")
    with open(DATA, encoding="utf-8") as handle:
        return (yaml.safe_load(handle) or {}).get("partners") or []


def _row(record: dict) -> str:
    logo = (record.get("logo") or {}).get("src", "-")
    return (
        f"{record.get('section', '?'):<9} {str(record.get('order', '-')):>4}  "
        f"{record.get('id', '?'):<18} {record.get('organization', '?'):<14} "
        f"{record.get('product_name', '?'):<32} logo={logo}"
    )


def cmd_list(args) -> int:
    records = _load_raw()
    if args.section:
        records = [r for r in records if r.get("section") == args.section]
    partner_grid = _ext()
    # Section first, so the listing matches the page; within one section the extension
    # decides, which is alphabetical everywhere except the hand-ordered platform band.
    sections = list(partner_grid.SECTIONS)
    for record in sorted(
        records,
        key=lambda r: (
            sections.index(r["section"])
            if r.get("section") in sections
            else len(sections),
            partner_grid.sort_key(r),
        ),
    ):
        print(_row(record))
    print(f"\n{len(records)} record(s)")
    return 0


def cmd_find(args) -> int:
    """Report exact hits and likely typos, so a near-miss never creates a duplicate."""
    needle = args.name.strip().lower()
    records = _load_raw()

    exact, near = [], []
    for record in records:
        fields = [
            str(record.get(key, "")) for key in ("organization", "product_name", "id")
        ]
        if any(value.lower() == needle for value in fields):
            exact.append(record)
            continue
        score = max(
            difflib.SequenceMatcher(None, needle, value.lower()).ratio()
            for value in fields
            if value
        )
        if score >= NEAR_MATCH:
            near.append((score, record))

    if exact:
        print(f"EXACT match for {args.name!r} -- update this record, do not create:")
        for record in exact:
            print("  " + _row(record))
    else:
        print(f"no exact match for {args.name!r}")

    if near:
        print("\nNEAR matches -- confirm with the user before treating as new:")
        for score, record in sorted(near, key=lambda item: -item[0]):
            print(f"  {score:.2f}  " + _row(record))
    elif not exact:
        print("no near matches; safe to create a new record")
    return 0


def cmd_next_order(args) -> int:
    orders = [
        r["order"]
        for r in _load_raw()
        if r.get("section") == args.section and r.get("order") is not None
    ]
    print(max(orders) + 10 if orders else 10)
    return 0


def cmd_slug(args) -> int:
    slug = re.sub(r"[^a-z0-9]+", "-", args.text.lower()).strip("-")
    if not slug:
        _die(f"{args.text!r} has no usable characters for an id")
    taken = {r.get("id") for r in _load_raw()}
    print(slug)
    if slug in taken:
        print(f"warning: id {slug!r} is already taken", file=sys.stderr)
    return 0


def cmd_validate(_args) -> int:
    """Run the docs extension's own validator; a pass here means the build accepts it."""
    partner_grid = _ext()
    try:
        records = partner_grid._load(CONFDIR, "_data/partners.yaml")
        # The device table shares the page and the extension, so a broken devices.yaml
        # fails the same build a broken card would.
        devices, planned = partner_grid._load_devices(CONFDIR, "_data/devices.yaml")
    except (
        Exception
    ) as exc:  # ExtensionError, yaml errors, anything the build would hit
        print(f"INVALID: {exc}")
        return 1
    print(
        f"OK: {len(records)} partner record(s), {len(devices)} device(s) and "
        f"{len(planned)} planned entr(ies) pass the same checks the docs build runs"
    )
    return 0


def cmd_verify(args) -> int:
    """Report what a card actually rendered, so it can be checked against the input.

    The validator only proves the YAML is well formed. This reads the built page, which
    is where a link kind, a swapped logo variant, or a derived issue number shows up.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        _die("beautifulsoup4 missing. Run with docs/.venv/bin/python")

    if not os.path.isfile(BUILT_PAGE):
        _die(f"{BUILT_PAGE} not found; run 'cd docs && make current-docs' first")
    if os.path.getmtime(BUILT_PAGE) < os.path.getmtime(DATA):
        print("STALE   the build predates partners.yaml; rebuild before trusting this")

    with open(BUILT_PAGE, encoding="utf-8") as handle:
        soup = BeautifulSoup(handle.read(), "html.parser")

    problems: list[str] = []

    # Scope to the article: the "On this page" sidebar mirrors the h2 text, so a
    # document-wide search sees every partner-count twice.
    article = soup.select_one("article") or soup
    counts = [
        int(node.get_text(strip=True)) for node in article.select(".partner-count")
    ]
    grids = [
        len(grid.select(".partner-card")) for grid in article.select(".partner-grid")
    ]
    if counts != grids:
        problems.append(f"partner-count {counts} disagrees with rendered cards {grids}")
    print(f"page    {len(grids)} grid(s), cards {grids}, partner-count {counts}")

    # The device panels open through a CSS adjacent-sibling rule, so a panel that drifts
    # away from its own row, or an aria-controls that stops matching, breaks the section
    # silently. Cheaper to assert than to notice.
    rows = article.select(".device-action")
    headings = [heading for _, heading in _ext().DETAIL_COLUMNS]
    panels = 0
    for cell in rows:
        summary = cell.select_one("summary.device-toggle")
        if summary is None:
            continue
        panels += 1
        panel = cell.find_next_sibling(class_="device-panel")
        target = summary.get("aria-controls", "")
        if panel is None:
            problems.append(
                f"device panel {target!r} is not the next sibling of its row"
            )
        elif panel.get("id") != target:
            problems.append(
                f"a Details button points at {target!r} but the panel beside it is "
                f"{panel.get('id')!r}"
            )
        elif [
            node.get_text(strip=True) for node in panel.select(".device-panel-heading")
        ] != headings:
            problems.append(
                f"panel {target!r} does not render {', '.join(headings)} in that order"
            )
    print(f"devices {len(rows)} row(s), {panels} with a Details panel")

    card = soup.find(id=f"partner-{args.id}")
    if card is None:
        _die(f"no card with id 'partner-{args.id}' on the built page")

    grid = card.find_parent(class_="partner-grid")
    grid_classes = " ".join(grid.get("class", [])) if grid else "?"
    print(f"grid    {grid_classes}")
    # The platform band renders neither pill nor logo panel, so their absence there is
    # the design rather than a fault; elsewhere a missing one is worth seeing.
    platform = "is-platform" in card.get("class", [])
    if not platform:
        print(f"badge   {_text(card, '.partner-status')}")
    print(f"eyebrow {_text(card, '.partner-eyebrow')}")
    print(f"name    {_text(card, '.partner-name')}")
    if card.select_one(".partner-handle"):
        print(f"handle  {_text(card, '.partner-handle')}")
    # The upcoming band renders no description, so a missing one is not a fault.
    if card.select_one(".partner-desc"):
        print(f"desc    {_text(card, '.partner-desc')}")

    logo = card.select_one(".partner-logo")
    if platform:
        if logo:
            problems.append("platform card renders a logo panel; remove its 'logo'")
        if card.select_one(".partner-status"):
            problems.append("platform card renders a status pill over its own title")
        if not card.select_one(".partner-handle"):
            problems.append("platform card has no handle chip")
    elif logo and "is-placeholder" in logo.get("class", []):
        print(
            f"logo    placeholder reading {_text(card, '.partner-logo-placeholder')!r}"
        )
    else:
        for image in card.select(".partner-logo img"):
            variant = "dark" if "only-dark" in image.get("class", []) else "light"
            print(f"logo    {variant}: {image.get('src')}  alt={image.get('alt')!r}")

    if not card.select("a.partner-link, button.partner-link"):
        print("link    none")

    partner_grid = _ext()
    for link in card.select("a.partner-link"):
        classes = link.get("class", [])
        kind = next((c[3:] for c in classes if c.startswith("is-")), "unknown")
        label = _link_text(link)
        href = link.get("href", "")
        arrow = bool(link.select_one("svg.eco-link-arrow"))
        print(f"link    {kind:<8} {label!r} -> {href}" + ("  [arrow]" if arrow else ""))

        # The arrow marks leaving the project, which the target decides: a link into the
        # IsaacTeleop repo shows none even when the record calls it external.
        leaves = href.startswith(("http://", "https://")) and partner_grid._is_external(
            href
        )
        if leaves and not arrow:
            problems.append(f"external link {label!r} is missing its arrow")
        if arrow and not leaves:
            problems.append(
                f"{label!r} points inside the project ({href}) but shows an "
                "external arrow"
            )
        if kind == "tracking":
            number = _ISSUE_RE.search(href)
            if not number:
                problems.append(
                    f"tracking link {label!r} has no issue number in {href}"
                )
            elif label != f"Tracking #{number.group(1)}":
                problems.append(
                    f"tracking link renders {label!r}; expected 'Tracking "
                    f"#{number.group(1)}'. Do not write the number into the label."
                )

    for trigger in card.select("button.partner-link.is-contact"):
        label = _link_text(trigger)
        panel = card.select_one(f"#{trigger.get('popovertarget', '')}")
        if panel is None:
            problems.append(f"contact link {label!r} targets a panel that is not there")
            continue
        if not panel.has_attr("popover"):
            problems.append(
                f"contact panel for {label!r} lacks the popover attribute, so it would "
                "render inline and never close"
            )
        hrefs = [a.get("href", "") for a in panel.select("a")]
        print(f"link    contact  {label!r} -> {_text(panel, '.partner-contact-name')}")
        for href in hrefs:
            print(f"        {href}")
        if not any(href.startswith("mailto:") for href in hrefs):
            problems.append(f"contact panel for {label!r} has no mailto: link")

    if problems:
        print("\nPROBLEMS")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        "\nOK: rendered card is self-consistent; compare the values above with the input"
    )
    return 0


def _text(scope, selector: str) -> str:
    node = scope.select_one(selector)
    return node.get_text(" ", strip=True) if node else "<missing>"


def _link_text(link) -> str:
    """Resolving an internal xref replaces our inline with Sphinx's own ``std-ref``
    span, so the label has to be read off the anchor for that kind."""
    node = link.select_one(".partner-link-text")
    if node:
        return node.get_text(" ", strip=True)
    return link.get_text(" ", strip=True).replace("(external)", "").strip()


def _resolve(records: list[dict], name: str) -> dict:
    needle = name.strip().lower()
    matches = [
        record
        for record in records
        if any(
            str(record.get(key, "")).lower() == needle
            for key in ("id", "organization", "product_name")
        )
    ]
    if not matches:
        _die(f"no record matches {name!r} exactly; run 'find' to search")
    if len(matches) > 1:
        ids = ", ".join(str(record.get("id")) for record in matches)
        _die(f"{name!r} matches several records ({ids}); pass the id instead")
    return matches[0]


def cmd_remove_check(args) -> int:
    """Report what deleting a record would break, before anything is deleted."""
    records = _load_raw()
    record = _resolve(records, args.name)
    print("record  " + _row(record))

    remaining = len(records) - 1
    if not remaining:
        print(
            "ERROR   this is the last record; the docs build rejects an empty "
            "partners list"
        )
    else:
        print(f"total   {len(records)} record(s), {remaining} would remain")

    section = record.get("section")
    siblings = [
        other
        for other in records
        if other.get("section") == section and other is not record
    ]
    if siblings:
        print(f"section {section!r} keeps {len(siblings)} card(s)")
    else:
        print(
            f"WARNING this is the last {section!r} card. Nothing errors, but the heading,\n"
            "        subtitle and divider still render above an empty grid, and\n"
            "        partner-count reads 0."
        )

    logo = record.get("logo") or {}
    files = [logo[key] for key in ("src", "src_dark") if logo.get(key)]
    if not files:
        print("logos   none referenced")
    for filename in files:
        shared = [
            str(other.get("id"))
            for other in records
            if other is not record
            and filename
            in (
                (other.get("logo") or {}).get("src"),
                (other.get("logo") or {}).get("src_dark"),
            )
        ]
        if shared:
            print(f"logos   {filename} still used by {', '.join(shared)} -- keep it")
        else:
            path = os.path.join(LOGO_DIR, filename)
            state = "present" if os.path.isfile(path) else "already missing"
            print(f"logos   {filename} ({state}) -- unreferenced after removal")
    return 0 if remaining else 1


def cmd_check_logo(args) -> int:
    """Vet an artwork file before it is copied into the logo directory."""
    path = os.path.expanduser(args.path)
    if not os.path.isfile(path):
        _die(f"{path} is not a file")

    suffix = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    print(f"file    {path}\nsize    {size:,} bytes")

    if suffix == ".svg":
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        if "<svg" not in text:
            _die("file has an .svg name but no <svg> element")
        print("type    SVG -- preferred, and exempt from Git LFS in partner-logos/")

        unsafe = [note for pattern, note in _SVG_UNSAFE if pattern.search(text)]
        for note in unsafe:
            print(f"UNSAFE  {note}")
        if "viewBox" not in text:
            print(
                "WARNING no viewBox; the mark may not scale inside the fixed logo panel"
            )
        if re.search(r"data:image/(?:png|jpe?g)", text, re.I):
            print(
                "WARNING embeds a raster image, which defeats the point of vector art"
            )
        if unsafe:
            print("        Do not commit this file; ask the partner for clean artwork.")
            return 1
        print("scan    clean: no scripts, event handlers, or remote references")
    elif suffix == ".png":
        print("type    PNG -- allowed only when no vector artwork exists")
        print(
            "WARNING PNG is tracked by Git LFS (.gitattributes '*.png filter=lfs');\n"
            "        the partner-logos exemption covers *.svg only. Confirm with the\n"
            "        user before committing a raster logo."
        )
    elif suffix in (".jpg", ".jpeg"):
        _die("JPEG is not allowed for logos; ask the partner for SVG or PNG")
    else:
        _die(f"unsupported logo type {suffix!r}; use .svg, or .png as a fallback")

    if args.id:
        dest_name = f"{args.id}{suffix}"
        dest = os.path.join(LOGO_DIR, dest_name)
        print(f"dest    docs/source/_static/partner-logos/{dest_name}")
        if os.path.exists(dest):
            print("WARNING destination already exists; confirm before overwriting")
    return 0


def main() -> int:
    partner_grid = _ext()
    sections = partner_grid.SECTIONS
    ordered_sections = partner_grid.ORDERED_SECTIONS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="print every partner record")
    listing.add_argument("--section", choices=sections)
    listing.set_defaults(func=cmd_list)

    find = sub.add_parser("find", help="exact and fuzzy lookup by company or product")
    find.add_argument("name")
    find.set_defaults(func=cmd_find)

    order = sub.add_parser(
        "next-order", help="free order value for a hand-ordered section"
    )
    order.add_argument("section", choices=ordered_sections)
    order.set_defaults(func=cmd_next_order)

    slug = sub.add_parser("slug", help="suggest a kebab-case id")
    slug.add_argument("text")
    slug.set_defaults(func=cmd_slug)

    sub.add_parser(
        "validate", help="check the file the way the docs build does"
    ).set_defaults(func=cmd_validate)

    verify = sub.add_parser(
        "verify", help="report what a card rendered on the built page"
    )
    verify.add_argument("id", help="partner id, as used in the card's DOM id")
    verify.set_defaults(func=cmd_verify)

    remove = sub.add_parser(
        "remove-check", help="report what deleting a record would break"
    )
    remove.add_argument("name", help="partner id, organization, or product name")
    remove.set_defaults(func=cmd_remove_check)

    logo = sub.add_parser("check-logo", help="vet an artwork file before copying it")
    logo.add_argument("path")
    logo.add_argument("--id", help="partner id, to report the destination filename")
    logo.set_defaults(func=cmd_check_logo)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
