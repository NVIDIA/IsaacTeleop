# Running Tests for Retargeting Engine

## Quick Start

From the `TeleopCore/src/core/retargeting_engine/python` directory:

```bash
# Run all tests
uv run --python 3.10 --with pytest pytest -v

# Run specific test file
uv run --python 3.10 --with pytest pytest tests/test_basic_modules.py -v

# Run specific test
uv run --python 3.10 --with pytest pytest tests/test_basic_modules.py::test_simple_connection -v

# Run with verbose output
uv run --python 3.10 --with pytest pytest -vv

# Run type checking
uv run --python 3.10 --with mypy mypy --ignore-missing-imports .
```

## Using CMake

From the build directory:

```bash
# Build the project
cmake --build . --target retargeting_engine_python

# Run tests
cmake --build . --target test_retargeting_engine

# Run type checking
cmake --build . --target typecheck_retargeting_engine
```

## Test Files

- `test_scalar_types.py` - Tests for FloatType, IntType, BoolType
- `test_basic_modules.py` - Tests for module connections and chaining
- `test_execution_caching.py` - Tests for diamond patterns and caching optimization

## Requirements

The tests use `pytest` which is automatically installed via `--with pytest` when using `uv run`.
No additional dependencies needed for basic scalar type tests.

