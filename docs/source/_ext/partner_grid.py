# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ecosystem partner cards, generated from ``_data/partners.yaml``.

Provides the ``partner-grid`` directive, the ``partner-count`` role, and the
``eco-block`` layout wrapper.  Adding a partner takes one YAML record plus one logo
file; page markup never changes.

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
LOGO_DIR = "_static/partner-logos"

# ``platform`` is the first-party band: NVIDIA stacks and teams, not partners. It is
# listed first because the page renders the sections in this order.
SECTIONS = ("platform", "active", "upcoming")
LIFECYCLE_LABELS = {
    "maintained": "Active",
    "upcoming": "Upcoming",
    "deprecated": "Deprecated",
}
INTEGRATION_LABELS = {"planning": "Planning", "in-integration": "In integration"}
LINK_KINDS = ("internal", "external", "tracking", "contact")


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
    '<svg class="partner-link-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2" aria-hidden="true" focusable="false">'
    '<path d="M7 17 17 7M9 7h8v8"></path></svg>'
)
# Contact links open a panel rather than navigating, so they get an envelope where an
# external link gets the arrow.
_MAIL_SVG = (
    '<svg class="partner-link-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
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
    "description",
    "links",
    "order",
)

_cache: dict[str, tuple[float, list[dict]]] = {}


def _fail(source: str, record: str | None, message: str) -> None:
    where = f"{source}: {record!r}" if record else source
    raise ExtensionError(f"partner data: {where}: {message}")


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

        if not _ID_RE.match(record["id"]):
            _fail(source, name, "id must be lowercase kebab-case")
        if record["id"] in seen_ids:
            _fail(source, name, "duplicate id")
        seen_ids.add(record["id"])

        if record["section"] not in SECTIONS:
            _fail(source, name, f"section must be one of {SECTIONS}")
        if record["lifecycle"] not in LIFECYCLE_LABELS:
            _fail(source, name, f"lifecycle must be one of {tuple(LIFECYCLE_LABELS)}")

        status = record.get("integration_status")
        if status is not None and status not in INTEGRATION_LABELS:
            _fail(
                source,
                name,
                f"integration_status must be one of {tuple(INTEGRATION_LABELS)}",
            )

        new_until = record.get("new_until")
        if new_until is not None and not isinstance(new_until, datetime.date):
            _fail(source, name, "new_until must be an unquoted YYYY-MM-DD date")

        orders = seen_orders.setdefault(record["section"], set())
        if record["order"] in orders:
            _fail(
                source,
                name,
                f"duplicate order {record['order']} within section {record['section']!r}",
            )
        orders.add(record["order"])

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

        for link in record["links"]:
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


def _load(confdir: str, relpath: str) -> list[dict]:
    source = os.path.join(confdir, relpath)
    if not os.path.isfile(source):
        raise ExtensionError(f"partner data: {relpath} not found")

    mtime = os.path.getmtime(source)
    cached = _cache.get(source)
    if cached and cached[0] == mtime:
        return cached[1]

    with open(source, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    records = _validate(data.get("partners"), relpath, confdir)
    _cache[source] = (mtime, records)
    return records


def _select(records: list[dict], section: str) -> list[dict]:
    return sorted(
        (r for r in records if r["section"] == section),
        key=lambda r: (r["order"], r["id"]),
    )


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


def _link_node(link: dict, docname: str) -> nodes.Element:
    label = _link_label(link)
    classes = ["partner-link", f"is-{link['kind']}"]

    if link["kind"] == "internal":
        target = link.get("doc") or link["ref"]
        xref = pending_xref(
            "",
            nodes.inline("", label, classes=["partner-link-text"]),
            refdoc=docname,
            refdomain="std",
            reftype="doc" if link.get("doc") else "ref",
            reftarget=target,
            refexplicit=True,
            refwarn=True,
            classes=classes,
        )
        return xref

    ref = nodes.reference("", "", refuri=link["url"], classes=classes)
    ref += nodes.inline("", label, classes=["partner-link-text"])
    if link["kind"] == "external":
        ref += nodes.raw("", _ARROW_SVG, format="html")
    # Screen readers should hear that the link leaves the docs; the arrow is decorative.
    ref += nodes.inline("", " (external)", classes=["partner-link-external-label"])
    return ref


def _card(record: dict, docname: str, today: datetime.date) -> nodes.Element:
    card = eco_block(ids=[f"partner-{record['id']}"], classes=["partner-card"])
    if record["section"] == "upcoming":
        card["classes"].append("is-upcoming")

    label, state_class = _status_badge(record, today)
    card += _line(["partner-status", state_class], label)
    card += _logo_panel(record)

    body = eco_block(classes=["partner-body"])
    eyebrow = " · ".join(
        part for part in (record["category"], record.get("type")) if part
    )
    body += _line(["partner-eyebrow"], eyebrow)
    body += _line(["partner-name"], record["product_name"])
    body += _line(["partner-desc"], record["description"].strip())

    if record.get("integration_status"):
        badges = _line(["partner-badges"])
        badges += nodes.inline(
            "",
            INTEGRATION_LABELS[record["integration_status"]],
            classes=["partner-badge"],
        )
        body += badges

    footer = _line(["partner-footer"])
    # Panels are siblings of the footer, not children: the footer is a <p>, and a <div>
    # inside a paragraph is invalid HTML that browsers silently reflow out of place.
    panels = []
    for index, link in enumerate(record["links"]):
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
        return [nodes.inline("", count, classes=["partner-count"])], []


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
    app.add_directive("eco-block", EcoBlock)
    app.add_role("partner-count", PartnerCount())
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
