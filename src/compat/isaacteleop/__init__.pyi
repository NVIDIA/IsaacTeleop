# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# A sys.meta_path finder is invisible to a type checker, so without this every
# `isaacteleop.X` is an unresolved-import error with no deprecation warning to
# explain it -- nothing was imported. Any-typed: the alias promises runtime
# identity, not types. Migrate to isaaccapture for real ones.
from typing import Any

def __getattr__(name: str) -> Any: ...
