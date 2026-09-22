# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# A sys.meta_path finder is invisible to a type checker. Any-typed: the alias
# promises runtime identity, not types.
from typing import Any

def __getattr__(name: str) -> Any: ...
