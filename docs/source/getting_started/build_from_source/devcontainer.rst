.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Dev Container (VS Code)
=======================

.. admonition:: Scope

   The dev container is intended for **development and unit testing only** — not for running a
   production teleop session.

The repository ships a :code-file:`.devcontainer/devcontainer.json` that pre-installs all build
dependencies and VS Code extensions, so you can configure and build without installing anything on
your host machine. See the
`VS Code Dev Containers documentation <https://code.visualstudio.com/docs/devcontainers/containers>`_
for a full overview of the workflow.

Prerequisites
-------------

- `Docker <https://docs.docker.com/get-docker/>`_ running on the host
- `VS Code <https://code.visualstudio.com/>`_ with the
  `Dev Containers extension <https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers>`_
  (``ms-vscode-remote.remote-containers``) installed

Usage
-----

1. Open the repository folder in VS Code.
2. When prompted *"Reopen in Container"*, click it — or open the Command Palette
   (:kbd:`Ctrl+Shift+P`) and run **Dev Containers: Reopen in Container**.
3. VS Code rebuilds the container (first time only) and reopens the workspace inside it.
4. Use the CMake Tools sidebar to configure and build. The build directory is set to
   ``build-devcontainer`` to keep it separate from any host build.

What's included
---------------

The container provides:

- Ubuntu 22.04 base image with ``build-essential``, ``cmake``, ``uv``,
  ``clang-format-14``, and the X11/GL headers required by Isaac Teleop
- ``git`` and ``git-lfs``
- ``docker-outside-of-docker`` so Docker commands reach the host daemon
- VS Code extensions: C/C++ IntelliSense, CMake Tools, Python, CMake syntax highlighting
- ``pre-commit`` hooks installed automatically on container creation

After the container starts, follow the normal :ref:`configure and build steps <one-time-setup>`
— all required tools are already present.
