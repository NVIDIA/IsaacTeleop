# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ecosystem page content, generated from the YAML files in ``_data/``.

Partner cards come from ``partners.yaml`` through the ``partner-grid`` directive and
the ``partner-count`` role; the supported-device table comes from ``devices.yaml``
through ``device-matrix`` and ``device-count``.  ``eco-block`` wraps layout.  Adding a
partner or a device takes one YAML record; page markup never changes.

Invalid records raise at build time rather than warn, because ``make current-docs``
runs ``sphinx-build -W`` and a silently dropped card is worse than a failed build.
"""

from __future__ import annotations

import datetime
import os
import re

import yaml
from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.addnodes import pending_xref
from sphinx.errors import ExtensionError
from sphinx.util.docutils import SphinxRole

DEFAULT_DATA = "_data/partners.yaml"
DEVICE_DATA = "_data/devices.yaml"
LOGO_DIR = "_static/partner-logos"

# A link into the docs site or into the IsaacTeleop repository stays inside this
# project, so it carries no external marker -- arrow or screen-reader label. Every
# other domain gets one, including other GitHub organizations such as isaac-sim.
PROJECT_REPO = "https://github.com/NVIDIA/IsaacTeleop"

# ``platform`` is the first-party band: NVIDIA stacks and teams, not partners. It is
# listed first because the page renders the sections in this order.
SECTIONS = ("platform", "active", "upcoming")
# Only the first-party band is hand-ordered, through ``order``. Partner sections sort
# alphabetically by organization, so no one has to be assigned a rank.
ORDERED_SECTIONS = ("platform",)
# The same band trades the logo panel and the status pill for a handle chip: with four
# NVIDIA entries both slots repeated the section heading, while the role each stack plays
# differs per card.
# Past this width the chip wraps inside a 282px card.
HANDLE_MAX_CHARS = 24
LIFECYCLE_LABELS = {
    "maintained": "Active",
    "upcoming": "Upcoming",
    "deprecated": "Deprecated",
}
LINK_KINDS = ("internal", "external", "tracking", "contact")

# The device table's two group header rows, rendered in this order. The wording is the
# old page's own table titles, so a reader arriving from an old link recognizes them.
DEVICE_GROUPS = {
    "xr": "XR Headsets and Tracking Peripherals",
    "peripheral": "Standalone Input Devices",
}
# The Details panel's three columns, in this order and never renamed per device: set up
# first because it is what most readers came for, acquire last because few need it. A
# column with nothing to say still renders, so the three stay aligned down the table.
DETAIL_COLUMNS = (
    ("setup", "Set up"),
    ("requirements", "Requirements"),
    ("acquire", "Acquire"),
)
# Every row's disclosure shares one name, which is what makes the browser close the open
# panel when the reader opens another -- no JavaScript involved.
DISCLOSURE_GROUP = "isaac-teleop-device"


class eco_block(nodes.General, nodes.Element):
    """A plain ``<div>`` carrying only the classes we ask for.

    Deliberately not docutils' own ``container`` node: that emits
    ``class="docutils container"``, and because Bootstrap claims the same class name
    the theme neutralizes it with ``.docutils.container {padding-inline: unset}``.
    That rule outranks ours and silently flattens every horizontal padding.

    ``html_tag`` and ``html_attributes`` let one node also stand in for the handful of
    elements docutils has no equivalent for (a ``<button>``, a ``[popover]`` panel)
    while keeping their contents as ordinary docutils children, so non-HTML builders
    still render the text.
    """


def _visit_eco_block(self, node):
    self.body.append(
        self.starttag(
            node, node.get("html_tag", "div"), "", **node.get("html_attributes", {})
        )
    )


def _depart_eco_block(self, node):
    self.body.append(f"</{node.get('html_tag', 'div')}>\n")


class eco_inline(nodes.Inline, nodes.Element):
    """``eco_block``'s inline twin, for elements that sit inside a paragraph."""


def _element(tag: str, classes: list[str], *, inline: bool = False, **attributes):
    node = (eco_inline if inline else eco_block)(classes=classes)
    node["html_tag"] = tag
    node["html_attributes"] = attributes
    return node


def _passthrough(self, node):
    """Non-HTML builders render the children and ignore the wrapper."""


_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ISSUE_RE = re.compile(r"/(?:issues|pull)/(\d+)/?$")
_TEL_RE = re.compile(r"[^\d+]")

# A stroked glyph rather than U+2197: the Unicode arrow renders far heavier than the
# surrounding 13px text in system fonts. Size and stroke come from the design mock.
_ARROW_SVG = (
    '<svg class="eco-link-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" aria-hidden="true" focusable="false">'
    '<path d="M7 17 17 7M9 7h8v8"></path></svg>'
)
# Contact links open a panel rather than navigating, so they get an envelope where an
# external link gets the arrow.
_MAIL_SVG = (
    '<svg class="eco-link-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" stroke-linejoin="round" aria-hidden="true" focusable="false">'
    '<rect x="3" y="5" width="18" height="14" rx="2"></rect>'
    '<path d="m3.5 7 8.5 6 8.5-6"></path></svg>'
)
_REQUIRED = (
    "id",
    "organization",
    "product_name",
    "section",
    "lifecycle",
    "category",
)
# Every key a record may carry. Checked so a typo, or a field the cards stopped
# rendering, fails the build instead of sitting in the file doing nothing.
_KNOWN = _REQUIRED + (
    "version",
    "type",
    "handle",
    "logo",
    "description",
    "links",
    "order",
    "new_until",
)

_cache: dict[str, tuple[float, object]] = {}


def _fail(source: str, record: str | None, message: str) -> None:
    where = f"{source}: {record!r}" if record else source
    raise ExtensionError(f"ecosystem data: {where}: {message}")


def _validate(records: list, source: str, confdir: str) -> list[dict]:
    if not isinstance(records, list) or not records:
        _fail(source, None, "expected a non-empty 'partners' list")

    seen_ids: set[str] = set()
    seen_orders: dict[str, set[int]] = {}

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            _fail(source, None, f"entry {index} is not a mapping")
        name = record.get("id", f"<entry {index}>")

        for field in _REQUIRED:
            if record.get(field) in (None, "", []):
                _fail(source, name, f"missing required field {field!r}")

        unknown = sorted(set(record) - set(_KNOWN))
        if unknown:
            _fail(source, name, f"unknown field(s) {', '.join(unknown)}")

        if not _ID_RE.match(record["id"]):
            _fail(source, name, "id must be lowercase kebab-case")
        if record["id"] in seen_ids:
            _fail(source, name, "duplicate id")
        seen_ids.add(record["id"])

        if record["section"] not in SECTIONS:
            _fail(source, name, f"section must be one of {SECTIONS}")

        if record["lifecycle"] not in LIFECYCLE_LABELS:
            _fail(source, name, f"lifecycle must be one of {tuple(LIFECYCLE_LABELS)}")

        # An upcoming card is a name, a category, and a tracking link once one exists:
        # nothing is integrated yet, so it renders no description, and a partner with no
        # public page yet gets no link rather than a placeholder.
        if record["section"] == "upcoming":
            if record.get("description") is not None:
                _fail(
                    source,
                    name,
                    "the upcoming band renders no description; remove it, or move the "
                    "record to 'active' if the integration ships",
                )
        else:
            for field in ("description", "links"):
                if record.get(field) in (None, "", []):
                    _fail(source, name, f"missing required field {field!r}")

        new_until = record.get("new_until")
        # Not isinstance: PyYAML loads a timestamp as datetime.datetime, which subclasses
        # date and would pass, then blow up on the date comparison in _status_badge.
        if new_until is not None and type(new_until) is not datetime.date:
            _fail(source, name, "new_until must be an unquoted YYYY-MM-DD date")

        if record["section"] in ORDERED_SECTIONS:
            if record.get("order") is None:
                _fail(source, name, "hand-ordered section: 'order' is required")
            orders = seen_orders.setdefault(record["section"], set())
            if record["order"] in orders:
                _fail(
                    source,
                    name,
                    f"duplicate order {record['order']} within section "
                    f"{record['section']!r}",
                )
            orders.add(record["order"])
        elif record.get("order") is not None:
            _fail(
                source,
                name,
                f"section {record['section']!r} sorts alphabetically by organization; "
                "remove 'order'",
            )

        version = record.get("version")
        # Quoted, because PyYAML reads an unquoted 6.0 as a float and str() would then
        # print version 3.10 as "3.1".
        if version is not None and not isinstance(version, str):
            _fail(source, name, 'version must be a quoted string, e.g. version: "6.0"')

        # The platform band renders no logo and no status pill, so a field feeding
        # either one would be read, validated, and then silently dropped.
        if record["section"] == "platform":
            handle = record.get("handle")
            if not isinstance(handle, str) or not handle.strip():
                _fail(
                    source,
                    name,
                    "the platform band shows a handle chip where a partner card shows "
                    "its logo: 'handle' is required",
                )
            if len(handle) > HANDLE_MAX_CHARS:
                _fail(
                    source,
                    name,
                    f"handle {handle!r} is over {HANDLE_MAX_CHARS} characters and would "
                    "wrap in the chip; name the role in two or three words",
                )
            if record.get("logo") is not None:
                _fail(
                    source,
                    name,
                    "the platform band renders no logo panel; remove 'logo'",
                )
            if record["lifecycle"] != "maintained":
                _fail(
                    source,
                    name,
                    "the platform band renders no status pill, so it cannot show "
                    f"lifecycle {record['lifecycle']!r}",
                )
            if record.get("new_until") is not None:
                _fail(
                    source,
                    name,
                    "the platform band renders no status pill; remove 'new_until'",
                )
        elif record.get("handle") is not None:
            _fail(
                source,
                name,
                "the handle chip renders only in the platform band; remove 'handle'",
            )

        logo = record.get("logo")
        if logo is not None:
            if not logo.get("src"):
                _fail(source, name, "logo present but logo.src is empty")
            if not logo.get("alt"):
                _fail(
                    source, name, "logo.alt is required for accessible alternative text"
                )
            for key in ("src", "src_dark"):
                filename = logo.get(key)
                if filename and not os.path.isfile(
                    os.path.join(confdir, LOGO_DIR, filename)
                ):
                    _fail(
                        source,
                        name,
                        f"{key} points at {LOGO_DIR}/{filename}, which does not exist",
                    )

        for link in record.get("links") or []:
            label = link.get("label")
            kind = link.get("kind")
            if not label:
                _fail(source, name, "every link needs a label")
            if kind not in LINK_KINDS:
                _fail(source, name, f"link {label!r}: kind must be one of {LINK_KINDS}")
            if kind == "internal":
                if bool(link.get("doc")) == bool(link.get("ref")):
                    _fail(
                        source,
                        name,
                        f"link {label!r}: internal links need exactly one of 'doc' or 'ref'",
                    )
            elif kind == "contact":
                contact = link.get("contact")
                if not isinstance(contact, dict):
                    _fail(
                        source,
                        name,
                        f"link {label!r}: contact links need a 'contact' mapping",
                    )
                for field in ("name", "email"):
                    if not contact.get(field):
                        _fail(
                            source,
                            name,
                            f"link {label!r}: contact.{field} is required",
                        )
                if "@" not in str(contact["email"]):
                    _fail(
                        source,
                        name,
                        f"link {label!r}: contact.email must be an email address",
                    )
            elif not str(link.get("url", "")).startswith(("http://", "https://")):
                _fail(source, name, f"link {label!r}: {kind} links need an http(s) url")
            elif kind == "tracking" and not _ISSUE_RE.search(link["url"]):
                _fail(
                    source,
                    name,
                    f"link {label!r}: tracking urls must end in an issue or pull number, "
                    "so the card can render 'Tracking #274'",
                )

    return records


_DEVICE_REQUIRED = ("id", "name", "url", "group", "modes")
_DEVICE_KNOWN = _DEVICE_REQUIRED + ("details",)
_PLANNED_REQUIRED = ("id", "name", "url", "note", "tracking")


_ENTRY_FORMS = ("label", "email", "phone")
_ENTRY_KEYS = set(_ENTRY_FORMS) | {"doc", "ref", "url", "note"}


def _validate_entry(entry, source: str, name: str, column: str) -> None:
    """A panel entry is a bare string, a link, or a way to reach someone."""
    if isinstance(entry, str):
        if entry.endswith("."):
            _fail(
                source,
                name,
                f"{column} entry {entry!r}: drop the trailing period, panel entries are "
                "noun phrases and not sentences",
            )
        return
    if not isinstance(entry, dict):
        _fail(source, name, f"{column} entry must be a string or a mapping")

    unknown = sorted(set(entry) - _ENTRY_KEYS)
    if unknown:
        _fail(source, name, f"{column} entry: unknown field(s) {', '.join(unknown)}")
    forms = [key for key in _ENTRY_FORMS if entry.get(key)]
    if len(forms) != 1:
        _fail(
            source,
            name,
            f"{column} entry: needs exactly one of {', '.join(_ENTRY_FORMS)}",
        )

    if forms == ["email"]:
        if "@" not in str(entry["email"]):
            _fail(source, name, f"{column} entry: {entry['email']!r} is not an address")
        return
    if forms == ["phone"]:
        return

    label = entry["label"]
    targets = [key for key in ("doc", "ref", "url") if entry.get(key)]
    if len(targets) != 1:
        _fail(
            source,
            name,
            f"{column} entry {label!r}: needs exactly one of 'doc', 'ref', or 'url'",
        )
    if targets == ["url"] and not str(entry["url"]).startswith(("http://", "https://")):
        _fail(source, name, f"{column} entry {label!r}: url must be http(s)")


def _validate_details(details, source: str, name: str) -> None:
    if not isinstance(details, dict):
        _fail(source, name, "'details' must be a mapping of panel columns")
    unknown = sorted(set(details) - {key for key, _ in DETAIL_COLUMNS})
    if unknown:
        _fail(
            source,
            name,
            f"details: unknown column(s) {', '.join(unknown)}; the panel renders "
            f"{', '.join(key for key, _ in DETAIL_COLUMNS)}",
        )
    if not any(details.get(key) for key, _ in DETAIL_COLUMNS):
        _fail(
            source,
            name,
            "details is empty; omit it and the row renders without a Details button",
        )
    for key, heading in DETAIL_COLUMNS:
        entries = details.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list) or not entries:
            _fail(
                source,
                name,
                f"details.{key} must be a non-empty list; leave it out and the "
                f"{heading!r} column renders an em dash",
            )
        for entry in entries:
            _validate_entry(entry, source, name, f"details.{key}")


def _validate_devices(data: dict, source: str) -> tuple[list[dict], list[dict]]:
    """The device table is reference, so the schema is flat: no bands, no lifecycles."""
    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        _fail(source, None, "expected a non-empty 'devices' list")

    seen_ids: set[str] = set()
    for index, record in enumerate(devices):
        if not isinstance(record, dict):
            _fail(source, None, f"entry {index} is not a mapping")
        name = record.get("id", f"<entry {index}>")

        for field in _DEVICE_REQUIRED:
            if record.get(field) in (None, "", []):
                _fail(source, name, f"missing required field {field!r}")
        unknown = sorted(set(record) - set(_DEVICE_KNOWN))
        if unknown:
            _fail(source, name, f"unknown field(s) {', '.join(unknown)}")

        if not _ID_RE.match(record["id"]):
            _fail(source, name, "id must be lowercase kebab-case")
        if record["id"] in seen_ids:
            _fail(source, name, "duplicate id")
        seen_ids.add(record["id"])

        if record["group"] not in DEVICE_GROUPS:
            _fail(source, name, f"group must be one of {tuple(DEVICE_GROUPS)}")
        # The device name is the manufacturer link, which is the only reason no row
        # carries a separate "Overview" link.
        if not str(record["url"]).startswith(("http://", "https://")):
            _fail(source, name, "url must be the manufacturer's http(s) product page")

        if record.get("details") is not None:
            _validate_details(record["details"], source, name)

    planned = data.get("planned") or []
    if not isinstance(planned, list):
        _fail(source, None, "'planned' must be a list")
    for index, record in enumerate(planned):
        name = (
            record.get("id", f"<planned {index}>") if isinstance(record, dict) else None
        )
        if not isinstance(record, dict):
            _fail(source, None, f"planned entry {index} is not a mapping")
        for field in _PLANNED_REQUIRED:
            if record.get(field) in (None, "", []):
                _fail(source, name, f"missing required field {field!r}")
        unknown = sorted(set(record) - set(_PLANNED_REQUIRED))
        if unknown:
            _fail(source, name, f"unknown field(s) {', '.join(unknown)}")
        if not _ISSUE_RE.search(str(record["tracking"])):
            _fail(
                source,
                name,
                "tracking urls must end in an issue or pull number, so the line can "
                "render 'Tracking #276'",
            )

    return devices, planned


def _read(confdir: str, relpath: str, build):
    """Parse and validate a data file, cached until it changes on disk."""
    source = os.path.join(confdir, relpath)
    if not os.path.isfile(source):
        raise ExtensionError(f"ecosystem data: {relpath} not found")

    mtime = os.path.getmtime(source)
    cached = _cache.get(source)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(source, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    parsed = build(data)
    _cache[source] = (mtime, parsed)
    return parsed


def _load(confdir: str, relpath: str = DEFAULT_DATA) -> list[dict]:
    return _read(
        confdir,
        relpath,
        lambda data: _validate(data.get("partners"), relpath, confdir),
    )


def _load_devices(
    confdir: str, relpath: str = DEVICE_DATA
) -> tuple[list[dict], list[dict]]:
    return _read(confdir, relpath, lambda data: _validate_devices(data, relpath))


def sort_key(record: dict) -> tuple:
    """Position within a section. Only comparable against keys from the same section."""
    if record.get("section") in ORDERED_SECTIONS:
        return (record.get("order", 0), record.get("id", ""))
    return (
        str(record.get("organization", "")).casefold(),
        str(record.get("product_name", "")).casefold(),
        str(record.get("id", "")),
    )


def _select(records: list[dict], section: str) -> list[dict]:
    return sorted((r for r in records if r["section"] == section), key=sort_key)


def _status_badge(record: dict, today: datetime.date) -> tuple[str, str]:
    """Corner label. Upcoming wins over New, which wins over the lifecycle label."""
    if record["section"] == "upcoming":
        return "Upcoming", "is-upcoming"
    new_until = record.get("new_until")
    if new_until and today <= new_until:
        return "New", "is-new"
    return LIFECYCLE_LABELS[record["lifecycle"]], f"is-{record['lifecycle']}"


def _line(classes: list[str], text: str = "") -> nodes.paragraph:
    """A paragraph, which is what docutils expects as the parent of inline content."""
    para = nodes.paragraph(classes=classes)
    if text:
        para += nodes.Text(text)
    return para


def _logo_panel(record: dict) -> nodes.Element:
    logo = record.get("logo")
    panel = eco_block(classes=["partner-logo"])
    if logo:
        holder = _line(["partner-logo-img"])
        dark = logo.get("src_dark")
        # A single-color mark disappears against the other theme, so a partner may
        # ship a second file; the theme's only-light/only-dark classes swap them.
        light_classes = ["only-light"] if dark else []
        holder += nodes.image(
            uri=f"/{LOGO_DIR}/{logo['src']}", alt=logo["alt"], classes=light_classes
        )
        if dark:
            holder += nodes.image(
                uri=f"/{LOGO_DIR}/{dark}",
                alt=logo["alt"],
                classes=["only-dark", "pst-js-only"],
            )
        panel += holder
    else:
        panel["classes"].append("is-placeholder")
        panel += _line(["partner-logo-placeholder"], record["organization"])
    return panel


def _name_line(record: dict) -> nodes.paragraph:
    """Card title, with any version as a quiet suffix rather than part of the name."""
    line = _line(["partner-name"], record["product_name"])
    version = record.get("version")
    if version:
        # The space belongs inside the span so text builders keep the two words apart.
        line += nodes.inline("", f" {version}", classes=["partner-version"])
    return line


def _handle_chip(handle: str) -> nodes.paragraph:
    """The API surface the card names, in the slot a partner card gives its logo.

    A bare ``<code>`` rather than ``nodes.literal``: the theme strips background,
    border, and padding off ``code.literal`` with ``!important``.
    """
    row = _line(["partner-handle"])
    chip = _element("code", [], inline=True)
    chip += nodes.Text(handle)
    row += chip
    return row


def _link_label(link: dict) -> str:
    """``Tracking`` becomes ``Tracking #274``, numbered from the issue URL itself.

    Reading the number off the URL keeps it from drifting away from the link target.
    """
    if link["kind"] != "tracking":
        return link["label"]
    return f"{link['label']} #{_ISSUE_RE.search(link['url']).group(1)}"


def _contact_trigger(link: dict, panel_id: str) -> nodes.Element:
    """The footer control. A ``<button>``, because it opens a panel instead of going
    anywhere; ``popovertarget`` gives us light dismiss, Esc, and focus return with no
    JavaScript, and the panel renders in the top layer so the card cannot clip it."""
    button = _element(
        "button",
        ["partner-link", "is-contact"],
        inline=True,
        type="button",
        popovertarget=panel_id,
    )
    button += nodes.inline("", link["label"], classes=["partner-link-text"])
    button += nodes.raw("", _MAIL_SVG, format="html")
    return button


def _contact_panel(link: dict, panel_id: str) -> nodes.Element:
    contact = link["contact"]
    panel = _element("div", ["partner-contact"], popover="")
    panel["ids"] = [panel_id]
    panel += _line(["partner-contact-title"], contact.get("title", "Sales contact"))
    panel += _line(["partner-contact-name"], contact["name"])

    row = _line(["partner-contact-row"])
    row += nodes.reference("", contact["email"], refuri=f"mailto:{contact['email']}")
    panel += row

    phone = str(contact.get("phone", ""))
    if phone:
        row = _line(["partner-contact-row"])
        row += nodes.reference("", phone, refuri=f"tel:{_TEL_RE.sub('', phone)}")
        panel += row
    return panel


def _is_external(url: str) -> bool:
    return not str(url).startswith(PROJECT_REPO)


def _mark_external(ref: nodes.Element, *, arrow: bool = True) -> None:
    """Say the link leaves the project. The arrow is decorative, so screen readers get
    the hidden label instead; a link that shows no arrow still carries it."""
    if arrow:
        ref += nodes.raw("", _ARROW_SVG, format="html")
    ref += nodes.inline("", " (external)", classes=["eco-link-external-label"])


def _xref(
    target: str, label: nodes.Node, docname: str, is_doc: bool, classes: list[str]
):
    """A cross-reference Sphinx resolves later, so a dead target fails the build."""
    return pending_xref(
        "",
        label,
        refdoc=docname,
        refdomain="std",
        reftype="doc" if is_doc else "ref",
        reftarget=target,
        refexplicit=True,
        refwarn=True,
        classes=classes,
    )


def _link_node(link: dict, docname: str) -> nodes.Element:
    label = _link_label(link)
    classes = ["partner-link", f"is-{link['kind']}"]

    if link["kind"] == "internal":
        return _xref(
            link.get("doc") or link["ref"],
            nodes.inline("", label, classes=["partner-link-text"]),
            docname,
            bool(link.get("doc")),
            classes,
        )

    ref = nodes.reference("", "", refuri=link["url"], classes=classes)
    ref += nodes.inline("", label, classes=["partner-link-text"])
    # The marker follows the target, not the declared kind: a tracking link, or an
    # `external` one pointing into our own repository, has not left the project.
    if _is_external(link["url"]):
        _mark_external(ref)
    return ref


def _card(record: dict, docname: str, today: datetime.date) -> nodes.Element:
    card = eco_block(ids=[f"partner-{record['id']}"], classes=["partner-card"])
    if record["section"] == "upcoming":
        card["classes"].append("is-upcoming")

    # The first-party band carries its brand in the section heading, so the logo panel
    # and the "Active" pill are spent on the handle chip in the body instead.
    if record["section"] == "platform":
        card["classes"].append("is-platform")
    else:
        label, state_class = _status_badge(record, today)
        card += _line(["partner-status", state_class], label)
        card += _logo_panel(record)

    body = eco_block(classes=["partner-body"])
    eyebrow = " · ".join(
        part for part in (record["category"], record.get("type")) if part
    )
    body += _line(["partner-eyebrow"], eyebrow)
    body += _name_line(record)
    if record.get("handle"):
        body += _handle_chip(record["handle"])
    if record.get("description"):
        body += _line(["partner-desc"], record["description"].strip())

    # Panels are siblings of the footer, not children: the footer is a <p>, and a <div>
    # inside a paragraph is invalid HTML that browsers silently reflow out of place.
    panels = []
    # The footer is emitted even with no links, because it carries the rule that closes
    # every card; the CSS holds its height open through :empty.
    footer = _line(["partner-footer"])
    for index, link in enumerate(record.get("links") or []):
        if link["kind"] == "contact":
            panel_id = f"partner-{record['id']}-contact-{index}"
            footer += _contact_trigger(link, panel_id)
            panels.append(_contact_panel(link, panel_id))
        else:
            footer += _link_node(link, docname)
    body += footer

    card += body
    card += panels
    return card


def _device_name(record: dict) -> nodes.paragraph:
    """The row label is the manufacturer link, so no row needs an Overview link.

    No arrow: with one on every row the column reads as decoration rather than as a
    signal, and the mock leaves them off. Screen readers still get the label.
    """
    line = _line(["device-name"])
    ref = nodes.reference("", record["name"], refuri=record["url"])
    _mark_external(ref, arrow=False)
    line += ref
    return line


def _detail_line(entry, docname: str) -> nodes.paragraph:
    """One panel entry: a noun phrase, a link, or an address to reach someone at."""
    line = _line(["device-panel-line"])
    if isinstance(entry, str):
        line += nodes.Text(entry)
        return line

    # No external marker on either: mailto: and tel: do not navigate anywhere, and the
    # arrow would read as "this leaves the docs".
    if entry.get("email"):
        address = str(entry["email"])
        line += nodes.reference("", address, refuri=f"mailto:{address}")
    elif entry.get("phone"):
        phone = str(entry["phone"])
        line += nodes.reference("", phone, refuri=f"tel:{_TEL_RE.sub('', phone)}")
    elif entry.get("url"):
        ref = nodes.reference("", entry["label"], refuri=entry["url"])
        if _is_external(entry["url"]):
            _mark_external(ref)
        line += ref
    else:
        line += _xref(
            entry.get("doc") or entry["ref"],
            nodes.Text(entry["label"]),
            docname,
            bool(entry.get("doc")),
            [],
        )
    if entry.get("note"):
        line += nodes.Text(f" — {entry['note']}")
    return line


def _disclosure(panel_id: str) -> nodes.Element:
    """The row's third column: a native ``<details>`` holding only its ``<summary>``.

    The panel itself is a sibling grid item so it can span all three columns, and the
    CSS reveals it from ``:has(details[open])``. Keeping the panel outside the
    ``<details>`` is also what lets the device name stay a real link: a link inside a
    ``<summary>`` both navigates and toggles.
    """
    cell = _element("div", ["device-action"])
    disclosure = _element("details", ["device-disclosure"], name=DISCLOSURE_GROUP)
    # On the summary rather than the details: the summary is the control, and it is what
    # a screen reader announces along with its expanded state.
    summary = _element("summary", ["device-toggle"], **{"aria-controls": panel_id})
    summary += nodes.inline("", "Details", classes=["device-toggle-label"])
    summary += nodes.inline("", "Close", classes=["device-toggle-label", "is-open"])
    disclosure += summary
    cell += disclosure
    return cell


def _device_panel(record: dict, panel_id: str, docname: str) -> nodes.Element:
    panel = _element("div", ["device-panel"])
    panel["ids"] = [panel_id]
    details = record["details"]
    for key, heading in DETAIL_COLUMNS:
        column = _element("div", ["device-panel-col"])
        title = _element("h4", ["device-panel-heading"])
        title += nodes.Text(heading)
        column += title
        entries = details.get(key) or ["—"]
        for entry in entries:
            column += _detail_line(entry, docname)
        panel += column
    return panel


def _planned_line(record: dict, docname: str) -> nodes.paragraph:
    """One line rather than a row: a planned device has no input modes or setup yet."""
    line = _line(["device-planned"])
    line += nodes.inline("", "Planned", classes=["device-planned-label"])

    entry = nodes.inline("", "", classes=["device-planned-entry"])
    entry += nodes.reference("", record["name"], refuri=record["url"])
    entry += nodes.Text(f" — {record['note']}")
    line += entry

    number = _ISSUE_RE.search(record["tracking"]).group(1)
    track = nodes.reference(
        "",
        f"Tracking #{number}",
        refuri=record["tracking"],
        classes=["device-planned-track"],
    )
    line += track
    return line


def _matrix(devices: list[dict], planned: list[dict], docname: str) -> nodes.Element:
    wrapper = eco_block(classes=["device-matrix"])
    grid = eco_block(classes=["device-grid"])
    grid += _line(["device-col"], "Device")
    grid += _line(["device-col"], "Input modes")
    # No label over the buttons -- they describe themselves. The cell stays to carry the
    # header rule across the third column.
    grid += _line(["device-col", "device-col-action"])

    for group, heading in DEVICE_GROUPS.items():
        rows = [record for record in devices if record["group"] == group]
        if not rows:
            continue
        grid += _line(["device-group"], heading)
        for record in rows:
            panel_id = f"device-{record['id']}-details"
            grid += _device_name(record)
            modes = _element("p", ["device-modes"], **{"data-label": "Input modes"})
            modes += nodes.Text(record["modes"])
            grid += modes
            # Emitted with or without a panel: the cell carries the row's bottom border.
            if record.get("details"):
                grid += _disclosure(panel_id)
                grid += _device_panel(record, panel_id, docname)
            else:
                grid += _element("div", ["device-action"])

    wrapper += grid
    for record in planned:
        wrapper += _planned_line(record, docname)
    return wrapper


class PartnerGrid(Directive):
    """Render every partner in one section of ``partners.yaml`` as a card grid."""

    has_content = False
    option_spec = {
        "section": lambda arg: directives.choice(arg, SECTIONS),
        "data": directives.unchanged,
    }

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        section = self.options.get("section", "active")
        records = _load(env.app.confdir, self.options.get("data", DEFAULT_DATA))
        today = datetime.date.today()

        grid = eco_block(classes=["partner-grid", f"partner-grid-{section}"])
        for record in _select(records, section):
            grid += _card(record, env.docname, today)
        return [grid]


class DeviceMatrix(Directive):
    """Render ``devices.yaml`` as one table: device, input modes, Details panel."""

    has_content = False
    option_spec = {"data": directives.unchanged}

    def run(self) -> list[nodes.Node]:
        env = self.state.document.settings.env
        devices, planned = _load_devices(
            env.app.confdir, self.options.get("data", DEVICE_DATA)
        )
        return [_matrix(devices, planned, env.docname)]


class EcoBlock(Directive):
    """``.. eco-block:: class-a class-b`` — a styled ``<div>`` around nested content.

    Use this instead of ``.. container::`` for anything the ecosystem CSS gives
    padding to; see the ``eco_block`` node for why.
    """

    required_arguments = 1
    final_argument_whitespace = True
    has_content = True

    def run(self) -> list[nodes.Node]:
        node = eco_block(classes=self.arguments[0].split())
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


class PartnerCount(SphinxRole):
    """``:partner-count:`active``` — the number of cards actually rendered."""

    def run(self) -> tuple[list[nodes.Node], list[nodes.system_message]]:
        section = self.text.strip()
        if section not in SECTIONS:
            raise ExtensionError(
                f"partner-count: unknown section {section!r}; expected one of {SECTIONS}"
            )
        records = _load(self.env.app.confdir, DEFAULT_DATA)
        count = str(len(_select(records, section)))
        # eco-count styles the pill; the second class tells a partner count apart from a
        # device one, which is how scripts/partner_card.py checks it against the grids.
        return [nodes.inline("", count, classes=["eco-count", "partner-count"])], []


class DeviceCount(SphinxRole):
    """``:device-count:`all``` — rows in the device table, planned entries excluded."""

    def run(self) -> tuple[list[nodes.Node], list[nodes.system_message]]:
        target = self.text.strip()
        groups = ("all",) + tuple(DEVICE_GROUPS)
        if target not in groups:
            raise ExtensionError(
                f"device-count: unknown group {target!r}; expected one of {groups}"
            )
        devices, _ = _load_devices(self.env.app.confdir, DEVICE_DATA)
        if target != "all":
            devices = [record for record in devices if record["group"] == target]
        return [
            nodes.inline("", str(len(devices)), classes=["eco-count", "device-count"])
        ], []


def setup(app):
    for node_class in (eco_block, eco_inline):
        app.add_node(
            node_class,
            html=(_visit_eco_block, _depart_eco_block),
            latex=(_passthrough, _passthrough),
            text=(_passthrough, _passthrough),
            man=(_passthrough, _passthrough),
            texinfo=(_passthrough, _passthrough),
        )
    app.add_directive("partner-grid", PartnerGrid)
    app.add_directive("device-matrix", DeviceMatrix)
    app.add_directive("eco-block", EcoBlock)
    app.add_role("partner-count", PartnerCount())
    app.add_role("device-count", DeviceCount())
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
