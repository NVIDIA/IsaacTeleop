cmake_minimum_required(VERSION 3.20)
project(teleop_ros2_examples)

# Python examples don't need CMake - they use uv
install(DIRECTORY python/
    DESTINATION examples/teleop_ros2/python
    FILES_MATCHING
        PATTERN "*.py"
        PATTERN "*.toml"
        PATTERN "*.md"
    PATTERN ".venv" EXCLUDE
    PATTERN "__pycache__" EXCLUDE
    PATTERN "*.pyc" EXCLUDE
)

install(FILES README.md Dockerfile
    DESTINATION examples/teleop_ros2
)
