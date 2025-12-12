# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Retargeting Engine Python Module

# Custom target to run type checking using mypy
add_custom_target(typecheck_retargeting_engine ALL
    COMMAND uv run --python ${TELEOPCORE_PYTHON_VERSION} --with mypy mypy .
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Running type checking with mypy on retargeting engine (Python ${TELEOPCORE_PYTHON_VERSION})"
)

# Custom target to run tests using uv with the correct Python version
# Runtime dependencies (numpy) from pyproject.toml, pytest via --with
# pytest.ini_options.pythonpath in pyproject.toml adds current dir to path
add_custom_target(test_retargeting_engine
    COMMAND uv run --python ${TELEOPCORE_PYTHON_VERSION} --with pytest pytest
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    COMMENT "Running retargeting engine tests with Python ${TELEOPCORE_PYTHON_VERSION}"
    DEPENDS typecheck_retargeting_engine
)

# Install main __init__.py
install(FILES
    __init__.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine
)

# Install interface files
install(FILES
    interface/tensor_type.py
    interface/tensor.py
    interface/tensor_collection.py
    interface/tensor_group.py
    interface/input_node.py
    interface/retargeter_node.py
    interface/output_selector.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/interface
)

# Install tensor_types subdirectory
install(FILES
    tensor_types/__init__.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/tensor_types
)

# Install tensor_types/examples subdirectory
install(FILES
    tensor_types/examples/__init__.py
    tensor_types/examples/scalar_types.py
    tensor_types/examples/numpy_types.py
    tensor_types/examples/pytorch_types.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/tensor_types/examples
)

# Install executor subdirectory
install(FILES
    executor/__init__.py
    executor/retargeter_executor.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/executor
)

# Install xrio subdirectory
install(FILES
    xrio/__init__.py
    xrio/hands_input.py
    xrio/controllers_input.py
    xrio/head_input.py
    xrio/xrio_update_node.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/xrio
)

# Install interface __init__.py
install(FILES
    interface/__init__.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/interface
)

# Install retargeters subdirectory
install(FILES
    retargeters/__init__.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/retargeters
)

# Install holoscan_utils subdirectory
install(FILES
    holoscan_utils/__init__.py
    holoscan_utils/retargeter_operator.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/holoscan_utils
)

# Install retargeters/examples subdirectory
install(FILES
    retargeters/examples/__init__.py
    retargeters/examples/sample_retargeter.py
    retargeters/examples/gripper_retargeter.py
    DESTINATION ${CMAKE_INSTALL_PREFIX}/lib/python3/dist-packages/teleopcore/retargeting_engine/retargeters/examples
)

