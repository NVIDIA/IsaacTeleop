# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Configuration file for the Sphinx documentation builder.
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os

# -- Project information -----------------------------------------------------

project = "Isaac Teleop"
copyright = "2025-2026, NVIDIA CORPORATION & AFFILIATES."
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
]

exclude_patterns = ["build", "Thumbs.db", ".DS_Store"]

# -- Options for HTML output ---------------------------------------------------

html_title = "Isaac Teleop Documentation"
html_theme = "sphinx_book_theme"
html_show_copyright = True
html_show_sphinx = False

html_theme_options = {
    "path_to_docs": "docs/",
    "repository_url": "https://github.com/NVIDIA/IsaacTeleop",
    "use_repository_button": True,
    "use_issues_button": True,
    "use_edit_page_button": True,
    "show_toc_level": 1,
}
