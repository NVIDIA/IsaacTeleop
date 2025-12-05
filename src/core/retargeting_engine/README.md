# Simplified Retargeting Engine

This directory contains the simplified retargeting engine that replaces the old retargeting_engine_old system.

## Overview

The new retargeting engine provides an extremely simple, modular interface based on composable `RetargetingModule` objects. The key innovation is that calling `connect()` immediately returns a new retargeter - no graph traversal, no executor, no instantiation step needed!

## Key Concepts

### RetargetingModule

The abstract base class for all retargeting modules. A module defines:
- **Inputs**: List of `TensorCollection` objects describing what data it needs
- **Outputs**: List of `TensorCollection` objects describing what data it produces  
- **Compute**: The transformation logic from inputs to outputs

```python
class MyRetargeter(RetargetingModule):
    def define_inputs(self) -> List[TensorCollection]:
        # Define what inputs this module needs
        return [TensorCollection("hand_data", [...])]
    
    def define_outputs(self) -> List[TensorCollection]:
        # Define what outputs this module produces
        return [TensorCollection("gripper_commands", [...])]
    
    def compute(self, inputs: List[TensorGroup], outputs: List[TensorGroup]) -> None:
        # Transform inputs to outputs
        # Read from inputs[i][j] and write to outputs[i][j]
        pass
```

### Module Composition - The Simple Way!

Just call `connect()` and get back a new retargeter immediately:

```python
# Create modules
source_module = HandTrackingModule("hand_tracker")
retargeter = GripperRetargeter("gripper")
post_processor = SmoothingModule("smoother")

# Connect them - each call returns a new RetargetingModule
step1 = retargeter.connect(source_module, 0)  # or just: retargeter.connect(source_module)
final = post_processor.connect(step1, 0)

# Use it directly!
outputs = final(input_group)
```

That's it! No `instantiate()`, no executor, no graph compilation. Just connect and use.

### How It Works

When you call `connect()`:
1. Type compatibility is checked immediately
2. A `ConnectedModule` is created that wraps both modules
3. The ConnectedModule implements the same RetargetingModule interface
4. You can call `connect()` on it again to chain more modules

The inputs of a ConnectedModule are the combined inputs of all source modules.
The outputs are the outputs of the target module.

**Execution Optimization**: If the same module appears multiple times in a pipeline (e.g., one source feeding multiple downstream modules), `ConnectedModule` automatically caches outputs during execution. Each module is executed at most once per call, avoiding redundant computation.

Example of automatic caching:
```python
source = DataSource()
processor1 = Processor1().connect(source)  # Uses source
processor2 = Processor2().connect(source)  # Also uses source

# Use OutputLayer to gather outputs with custom names
combined = OutputLayer({
    "output1": processor1.output("result"),
    "output2": processor2.output("result")
})

# When combined is called, source executes only once!
# Its output is cached and reused for both processor1 and processor2
outputs = combined()
output1 = outputs["output1"]
output2 = outputs["output2"]
```

### OutputLayer Helper

The `OutputLayer` module combines outputs from multiple modules with custom names:

```python
left_retargeter = LeftArmRetargeter(name="left")
right_retargeter = RightArmRetargeter(name="right")

# Gather their outputs with custom names
output_layer = OutputLayer({
    "left_arm_pose": left_retargeter.output("pose"),
    "right_arm_pose": right_retargeter.output("pose")
})

# Use it like any other retargeting module
result = output_layer(inputs)
left_pose = result["left_arm_pose"]
right_pose = result["right_arm_pose"]

# Can also connect to other modules
next_module = NextModule(name="next")
connected = next_module.connect({
    "left": output_layer.output("left_arm_pose"),
    "right": output_layer.output("right_arm_pose")
})
```

## Architecture - Why It's Better

### What Makes This Design Superior

**No Graph Traversal**: Each `connect()` call directly combines modules. No need to traverse a graph later.

**No Executor**: Modules execute themselves. The `ConnectedModule` simply calls its sources, then calls the target.

**No Instantiation Step**: Every module (including `ConnectedModule`) implements the same interface and can be called directly.

**Immediate Feedback**: Type errors are caught at connection time, not later during compilation.

**Infinite Composition**: Since `ConnectedModule` is a `RetargetingModule`, you can keep connecting indefinitely.

**Automatic Caching**: If the same module is used by multiple downstream modules, it's executed only once per call. Outputs are automatically cached and reused.

### Old System vs New System

**Old System (retargeting_engine_old):**
- Create modules
- Call `set_input()` to connect them
- Create `RetargeterExecutor` with output nodes
- Executor discovers graph and builds execution order
- Call `executor.execute()`

**New System:**
- Create modules
- Call `connect()` - get back a new module immediately
- Call it: `outputs = module(inputs)`

That's 3 steps vs 5, and much more intuitive!

## Directory Structure

```
retargeting_engine/
├── CMakeLists.txt
├── README.md (comprehensive documentation)
└── python/
    ├── __init__.py
    ├── interface/
    │   ├── retargeting_module.py       # Base class with connect()
    │   ├── connected_module.py         # Result of connect()
    │   ├── tensor_collection.py
    │   ├── tensor_group.py
    │   ├── tensor.py
    │   └── tensor_type.py
    └── modules/
        ├── __init__.py
        └── concatenate.py              # Concatenation helper
```

## Usage Example

```python
from teleopcore.retargeting_engine import (
    RetargetingModule,
    TensorCollection,
    TensorGroup,
    OutputLayer,
    FloatType,
    IntType,
    BoolType
)

# Define your retargeters
class SourceModule(RetargetingModule):
    def define_inputs(self):
        return []  # No inputs - this is a source
    
    def define_outputs(self):
        return [TensorCollection("data", [FloatType("x"), FloatType("y")])]
    
    def compute(self, inputs, outputs):
        # Get data from somewhere
        outputs[0][0] = 3.0
        outputs[0][1] = 4.0

class ProcessorModule(RetargetingModule):
    def define_inputs(self):
        return [TensorCollection("data", [FloatType("x"), FloatType("y")])]
    
    def define_outputs(self):
        return [TensorCollection("result", [FloatType("sum")])]
    
    def compute(self, inputs, outputs):
        outputs[0][0] = inputs[0][0] + inputs[0][1]

# Create and connect - super simple!
source = SourceModule("source")
processor = ProcessorModule("processor")

# Connect returns a new module
pipeline = processor.connect(source)

# Use it!
outputs = pipeline()
print(outputs[0][0])  # 7.0

# Can keep connecting
class DoublerModule(RetargetingModule):
    def define_inputs(self):
        return [TensorCollection("result", [FloatType("sum")])]
    
    def define_outputs(self):
        return [TensorCollection("doubled", [FloatType("value")])]
    
    def compute(self, inputs, outputs):
        outputs[0][0] = inputs[0][0] * 2

doubler = DoublerModule("doubler")
full_pipeline = doubler.connect(pipeline)

outputs = full_pipeline()
print(outputs[0][0])  # 14.0
```

## Migration from Old System

If you have existing retargeters using the old system:

1. Change base class from `RetargeterNode` to `RetargetingModule`
2. Rename `_define_inputs()` to `define_inputs()` (no underscore)
3. Rename `_define_outputs()` to `define_outputs()` (no underscore)
4. Rename `execute()` to `compute()` (remove `output_mask` parameter)
5. Replace connection code:
   - **Old**: `module.connect([source1.output(0), source2.output(0)])`
   - **New**: `combined = module.connect((source1, 0), (source2, 0))`
6. Remove `RetargeterExecutor` - just call the module directly
7. `InputNode` → just make a module with no inputs (empty `define_inputs()`)

## Benefits

- **Simpler API**: Just call `connect()` and get a module back
- **No Executor**: Modules are directly callable
- **No Graph Compilation**: Happens automatically as you connect
- **Immediate Type Checking**: Errors caught at connection time
- **Same Performance**: Still uses index-based execution with pre-allocated buffers
- **Infinitely Composable**: Keep connecting modules forever
- **Smart Caching**: Shared modules execute only once per call

## Execution Caching Details

The caching system works for **arbitrarily complex graphs** where modules are reused anywhere in the pipeline.

### Simple Example: Shared Source

```python
# One source feeds two processors
source = HandTracker()
left_processor = LeftArmProcessor().connect(source)
right_processor = RightArmProcessor().connect(source)
output_layer = OutputLayer({
    "left": left_processor.output("result"),
    "right": right_processor.output("result")
})

# Execution flow when output_layer() is called:
# 1. source.compute() - executed ONCE, output cached
# 2. left_processor.compute(cached_source_output) 
# 3. right_processor.compute(cached_source_output) - reuses cached output!
# 4. Results gathered into {"left": ..., "right": ...}
```

### Complex Example: Diamond Graph

```python
# Diamond dependency pattern:
#       A
#      / \
#     B   C
#      \ /
#       D

module_a = ModuleA()
module_b = ModuleB().connect(module_a)
module_c = ModuleC().connect(module_a)
module_d = ModuleD().connect((module_b, 0), (module_c, 0))

# When module_d() is called:
# 1. Execution context created
# 2. module_b needs module_a → execute module_a, cache result
# 3. module_b executes with cached module_a output
# 4. module_c needs module_a → found in cache, reuse!
# 5. module_c executes with cached module_a output  
# 6. module_d executes with module_b and module_c outputs
# Result: module_a executed ONCE despite being needed twice
```

### Even More Complex: Nested Diamonds

```python
# Multiple levels of sharing:
#         A
#        / \
#       B   C
#      / \ / \
#     D   E   F
#      \ | /
#        G

# Every module is executed at most once, no matter how complex the graph!
```

### How It Works

The `ExecutionContext` is:
- **Created** once at the top-level `compute()` call
- **Propagated** through all recursive `_compute_with_context()` calls
- **Shared** across the entire execution tree
- **Discarded** when the top-level call completes

This means:
- Any module that appears anywhere in the graph is cached on first execution
- All subsequent uses in that same call tree will reuse the cached output
- Works for arbitrarily deep and complex graph structures
- Handles diamonds, DAGs, and any other acyclic patterns

The optimization is:
- **Automatic**: No code changes needed
- **Transparent**: Works across all nested ConnectedModules
- **Complete**: Handles any DAG structure
- **Per-call**: Cache is created fresh for each top-level call
- **Memory-efficient**: Cache is discarded after the call completes
