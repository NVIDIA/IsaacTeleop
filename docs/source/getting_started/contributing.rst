.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Contributing
============

We welcome contributions. Please see the repository's `CONTRIBUTING.md <https://github.com/NVIDIA/IsaacTeleop/blob/main/CONTRIBUTING.md>`_ for:

- Code of conduct and how to contribute
- Development setup and coding standards
- Pull request process

Previewing documentation changes
--------------------------------

Local build
~~~~~~~~~~~

Build the docs locally to catch broken links and rendering issues before opening
a pull request:

.. code-block:: bash

   cd docs
   pip install -r requirements.txt
   make current-docs

The output is written to ``docs/build/current/``. Open ``index.html`` in a
browser to inspect it. Sphinx is run with ``-W --keep-going``, so warnings are
treated as errors — fix them locally before pushing.

PR preview on GitHub Pages
~~~~~~~~~~~~~~~~~~~~~~~~~~

Pull requests that touch the documentation automatically trigger the
``Build & deploy docs`` workflow. When the PR branch lives in
``NVIDIA/IsaacTeleop`` (not a fork), the workflow publishes a preview to
GitHub Pages at:

.. code-block:: text

   https://nvidia.github.io/IsaacTeleop/preview/pr-<N>/

The preview link is also added to the workflow run's *Summary* tab. It is
refreshed on each push to the PR. Previews accumulate on the ``gh-pages``
branch under ``preview/``; maintainers can clear them by manually running the
``Cleanup docs PR previews`` workflow from the Actions tab.

.. note::

   Pull requests opened **from a fork** do not get an automatic preview because
   the workflow's ``GITHUB_TOKEN`` is read-only in that context and cannot push
   to ``gh-pages``. If you have write access to ``NVIDIA/IsaacTeleop``, push
   your branch there directly to get a preview; otherwise, attach screenshots of
   your local build to the PR description.
