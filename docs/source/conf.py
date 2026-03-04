# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
from datetime import datetime, timezone

# -- Project information -----------------------------------------------------

project = "Isaac Teleop"
build_time = datetime.now(timezone.utc)
copyright = f"2025-{build_time.year}, NVIDIA CORPORATION & AFFILIATES"
copyright += f", last updated on {build_time.strftime('%B %d, %Y')}"
author = "NVIDIA"

_version_file = os.path.join(os.path.dirname(__file__), "..", "VERSION")
if os.path.exists(_version_file):
    with open(_version_file) as f:
        full_version = f.read().strip()
    version = full_version
    release = full_version
else:
    version = release = "0.0.0"

# -- General configuration -----------------------------------------------------

extensions = [
    "sphinx.ext.githubpages",
    "sphinx_copybutton",
    "sphinx_multiversion",
    "sphinx_design",
]

exclude_patterns = ["build", "Thumbs.db", ".DS_Store"]

# sphinx-multiversion: which refs to build (avoids "No matching refs found" in CI)
smv_remote_whitelist = r"^.*$"
smv_branch_whitelist = os.getenv("SMV_BRANCH_WHITELIST", r"^(main|release/.*)$")
smv_tag_whitelist = os.getenv("SMV_TAG_WHITELIST", r"^v[1-9]\d*\.\d+\.\d+$")

# -- Options for HTML output ---------------------------------------------------

html_title = "Isaac Teleop Documentation"
html_theme = "nvidia_sphinx_theme"
html_favicon = "_static/favicon.ico"
html_show_copyright = True
html_show_sphinx = False
html_static_path = ["_static"]
html_css_files = ["css/custom.css"]

html_theme_options = {
    "collapse_navigation": True,
    "use_edit_page_button": True,
    "show_toc_level": 1,
    "search_bar_text": "Search...",
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/NVIDIA/IsaacTeleop",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
        },
        {
            "name": "CloudXR",
            "url": "https://docs.nvidia.com/cloudxr-sdk",
            "icon": "https://img.shields.io/badge/CloudXR-6.1-green.svg",
            "type": "url",
        },
        {
            "name": "Isaac Lab",
            "url": "https://isaac-sim.github.io/IsaacLab/",
            "icon": "https://img.shields.io/badge/IsaacLab-3.0-silver.svg",
            "type": "url",
        },
    ],
    "navbar_end": ["theme-switcher"],
    "navbar_persistent": ["search-button"],
}

# Primary sidebar (left): icon links row, search, then TOC (like Isaac Lab)
html_sidebars = {
    "**": ["icon-links", "search-field", "sidebar-nav-bs"],
}

# Edit page button: link to GitHub so users can suggest edits (PyData theme uses html_context)
html_context = {
    "github_user": "NVIDIA",
    "github_repo": "IsaacTeleop",
    "github_version": "main",
    "doc_path": "docs/source",
}

# Base URL for linking to repository source (used by code-file and code-dir roles).
_GH_BASE = "https://github.com/NVIDIA/IsaacTeleop"
_GH_BRANCH = html_context["github_version"]


def _parse_code_role(text):
    """Parse role text as 'path' or 'label <path>'. Returns (label, path)."""
    text = text.strip()
    if " <" in text and text.endswith(">"):
        label, path = text.rsplit(" <", 1)
        return label.strip(), path[:-1].strip()
    return text, text


def _code_file_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """Role for linking to a file in the GitHub repo: :code-file:`path` or :code-file:`label <path>`."""
    from docutils import nodes
    from docutils.utils import unescape

    label, path = _parse_code_role(unescape(text))
    url = f"{_GH_BASE}/blob/{_GH_BRANCH}/{path}"
    node = nodes.reference(rawtext, label, refuri=url)
    return [node], []


def _code_dir_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    """Role for linking to a directory in the GitHub repo: :code-dir:`path` or :code-dir:`label <path>`."""
    from docutils import nodes
    from docutils.utils import unescape

    label, path = _parse_code_role(unescape(text))
    path = path.rstrip("/")
    url = f"{_GH_BASE}/tree/{_GH_BRANCH}/{path}"
    node = nodes.reference(rawtext, label if label != path else path, refuri=url)
    return [node], []


def _external_links_new_tab(app, doctree, docname):
    """Mark external links to open in a new tab."""
    from docutils import nodes

    for node in doctree.traverse(nodes.reference):
        refuri = node.get("refuri", "")
        if refuri.startswith(("http://", "https://")):
            node["target"] = "_blank"


def setup(app):
    app.add_role("code-file", _code_file_role)
    app.add_role("code-dir", _code_dir_role)
    app.add_config_value("html_external_links_new_tab", True, "html")
    # Add rel="noopener noreferrer" when target="_blank" so external links are safe
    from sphinx.writers.html5 import HTML5Translator

    _base_visit_reference = HTML5Translator.visit_reference

    def visit_reference(self, node):
        if (
            getattr(self.config, "html_external_links_new_tab", True)
            and node.get("target") == "_blank"
            and "rel" not in node
        ):
            node["rel"] = "noopener noreferrer"
        return _base_visit_reference(self, node)

    HTML5Translator.visit_reference = visit_reference
    app.connect("doctree-resolved", _external_links_new_tab)
