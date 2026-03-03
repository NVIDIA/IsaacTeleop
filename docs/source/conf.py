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
