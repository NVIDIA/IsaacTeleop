# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Minimal makefile for Sphinx documentation

SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = build

.PHONY: current-docs
current-docs:
	@rm -rf "$(BUILDDIR)/current"
	@$(SPHINXBUILD) -W --keep-going "$(SOURCEDIR)" "$(BUILDDIR)/current" $(SPHINXOPTS)
	@touch "$(BUILDDIR)/current/.nojekyll"
