# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
TeleopSession - A high-level wrapper for complete teleop pipelines.

This class encapsulates all the boilerplate for setting up DeviceIO sessions,
plugins, and retargeting engines, allowing users to focus on configuration
rather than initialization code.
"""

import logging
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Set

from isaacteleop.retargeting_engine.deviceio_source_nodes import IDeviceIOSource
from isaacteleop.retargeting_engine.interface import BaseRetargeter
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    GraphExecutable,
    GraphTime,
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.execution_events import (
    ExecutionEvents,
    ExecutionState,
)

import isaacteleop.deviceio as deviceio
import isaacteleop.oxr as oxr
import isaacteleop.plugin_manager as pm

from .config import (
    RetargetingExecutionMode,
    SessionMode,
    TeleopSessionConfig,
)
from .async_retarget_runner import (
    AsyncRetargetRunnerStopped,
    AsyncRetargetWorkerError,
    AsyncRetargetRunner,
    RetargetFrame,
    StepRequest,
    snapshot_compute_context,
    snapshot_retargeter_io,
    snapshot_pipeline_inputs,
)
from .teleop_state_manager_types import teleop_control_states


logger = logging.getLogger(__name__)


@dataclass
class RetargetingStepInfo:
    """Age and timing metadata for the most recent ``step()`` return.

    ``returned_frame_id`` and ``submitted_frame_id`` identify which completed
    frame was returned and which request this call submitted. Pipelined callers
    can use ``returned_age_frames`` to observe result age without implying any
    current-frame wait. Counts such as ``dropped_submissions`` and
    ``frame_deadline_miss`` are per-step so apps can accumulate them for
    run-wide debug summaries.
    """

    returned_frame_id: int | None = None
    submitted_frame_id: int | None = None
    returned_age_frames: int | None = None
    returned_age_s: float | None = None
    compute_duration_s: float | None = None
    dropped_submissions: int = 0
    ran_synchronously: bool = False
    frame_deadline_miss: bool = False
    worker_exception: BaseException | None = None


class TeleopSession:
    """High-level teleop session manager with RAII pattern.

    This class manages the complete lifecycle of a teleop session using
    Python's context manager protocol.

    The session handles:
    1. Creating OpenXR session with required extensions
    2. Creating DeviceIO session with trackers
    3. Initializing plugins
    4. Running retargeting pipeline via step() method
    5. Cleanup on exit

    Pipelines may contain leaf nodes that are DeviceIO sources (auto-polled from
    hardware trackers) and/or leaf nodes that are regular retargeters requiring
    external inputs. External inputs are provided by the caller when calling step().

    Usage with DeviceIO-only pipeline:
        controllers = ControllersSource(name="controllers")
        gripper = GripperRetargeter(name="gripper")
        pipeline = gripper.connect({
            "controller_left": controllers.output("controller_left"),
            "controller_right": controllers.output("controller_right")
        })

        config = TeleopSessionConfig(app_name="MyApp", pipeline=pipeline)
        with TeleopSession(config) as session:
            while True:
                result = session.step()
                left = result["gripper_left"][0]

    Usage with external (non-DeviceIO) inputs via ValueInput:
        controllers = ControllersSource(name="controllers")
        ee_state = ValueInput("ee_state", RobotEEState())  # external leaf
        pipeline = combiner.connect({
            "controller_left": controllers.output("controller_left"),
            "ee_pos": ee_state.output("value"),
        })

        config = TeleopSessionConfig(app_name="MyApp", pipeline=pipeline)
        with TeleopSession(config) as session:
            ext_specs = session.get_external_input_specs()
            # ext_specs == {"ee_state": {"value": TensorGroupType(...)}}

            while True:
                ee_tg = TensorGroup(RobotEEState())
                ee_tg[0] = get_ee_position()

                result = session.step(external_inputs={
                    "ee_state": {"value": ee_tg}
                })

    Any BaseRetargeter that is a leaf (not connected to a DeviceIO source)
    automatically becomes an external input -- ValueInput is just a shortcut
    for the common single-value passthrough case. See external_inputs_example.py.
    """

    def __init__(self, config: TeleopSessionConfig):
        """Initialize the teleop session.

        Discovers sources and trackers from the pipeline and prepares for session creation.
        Actual resource creation happens in __enter__.

        Args:
            config: Complete configuration including pipeline (trackers auto-discovered)
        """
        self.config = config
        self.pipeline: GraphExecutable = config.pipeline
        self.teleop_control_pipeline: Optional[GraphExecutable] = (
            config.teleop_control_pipeline
        )

        # Core components (will be created in __enter__)
        self._oxr_session: Optional[oxr.OpenXRSession] = None
        self.deviceio_session: Optional[Any] = None
        self.plugin_managers: List[pm.PluginManager] = []
        self.plugin_contexts: List[Any] = []

        # Exit stack for RAII resource management
        self._exit_stack = ExitStack()

        # Auto-discovered sources
        self._sources: List[IDeviceIOSource] = []

        # External (non-DeviceIO) leaf nodes that require caller-provided inputs
        self._external_leaves: List[BaseRetargeter] = []

        # Cached leaf name sets for filtering pipeline inputs
        self._main_leaf_names: Set[str] = set()
        self._control_leaf_names: Set[str] = set()

        # Runtime state
        self.frame_count: int = 0
        self.start_time: float = 0.0
        self._last_context: Optional[ComputeContext] = None
        self._last_step_info = RetargetingStepInfo()
        self._last_execution_state: Optional[ExecutionState] = None
        self._async_runner: Optional[AsyncRetargetRunner] = None
        self._active_retargeting_execution_mode: Optional[RetargetingExecutionMode] = (
            None
        )
        self._setup_complete: bool = False
        # Discover sources and external leaves from pipeline
        self._discover_sources()

    @property
    def oxr_session(self) -> Optional[oxr.OpenXRSession]:
        """The internal OpenXR session, or ``None`` when using external handles (read-only)."""
        return self._oxr_session

    @property
    def last_context(self) -> Optional[ComputeContext]:
        """Most recent ComputeContext produced by ``step()``, or ``None`` before first step."""
        return self._last_context

    @property
    def last_step_info(self) -> RetargetingStepInfo:
        """Age and timing metadata for the most recent ``step()`` return."""
        return self._last_step_info

    def _discover_sources(self) -> None:
        """Discover DeviceIO source modules and external leaf nodes from the pipeline.

        Traverses the pipeline to find all leaf nodes, partitioning them into:
        - IDeviceIOSource instances (auto-polled from hardware trackers)
        - External leaves (non-DeviceIO leaves with non-empty input_spec() that
          require caller-provided inputs in step()). Leaves with empty input_spec()
          (e.g. fixed-command retargeters) are not treated as external and do not
          require external_inputs.
        """
        main_leaf_nodes = self.pipeline.get_leaf_nodes()
        control_leaf_nodes: List[BaseRetargeter] = []
        if self.teleop_control_pipeline is not None:
            control_leaf_nodes = self.teleop_control_pipeline.get_leaf_nodes()

        leaf_nodes = main_leaf_nodes + control_leaf_nodes
        main_leaf_ids = {id(node) for node in main_leaf_nodes}
        control_leaf_ids = {id(node) for node in control_leaf_nodes}

        # Cache leaf name sets for filtering pipeline inputs
        self._main_leaf_names = {node.name for node in main_leaf_nodes}
        self._control_leaf_names = {node.name for node in control_leaf_nodes}

        # Leaf names must be unique across main and control pipelines because
        # they are used as top-level keys in collected pipeline inputs.
        seen_name_to_id: Dict[str, int] = {}
        for node in leaf_nodes:
            existing_id = seen_name_to_id.get(node.name)
            if existing_id is not None and existing_id != id(node):
                raise ValueError(
                    "Duplicate leaf node name detected across pipeline and "
                    "teleop_control_pipeline: "
                    f"'{node.name}' (node ids: {existing_id}, {id(node)})"
                )
            seen_name_to_id[node.name] = id(node)

        self._sources = []
        self._external_leaves = []
        visited_nodes = set()
        for node in leaf_nodes:
            if id(node) in visited_nodes:
                continue
            visited_nodes.add(id(node))
            if isinstance(node, IDeviceIOSource):
                self._sources.append(node)
            elif node.input_spec():
                if id(node) in control_leaf_ids and id(node) not in main_leaf_ids:
                    raise ValueError(
                        "teleop_control_pipeline contains an external-input leaf "
                        f"'{node.name}', which is not supported. Control pipeline "
                        "inputs must come from DeviceIO sources (or be no-input nodes)."
                    )
                self._external_leaves.append(node)

        # Create tracker-to-source mapping for efficient lookup
        self._tracker_to_source: Dict[Any, Any] = {}
        for source in self._sources:
            tracker = source.get_tracker()
            self._tracker_to_source[id(tracker)] = source

    def get_external_input_specs(self) -> Dict[str, RetargeterIOType]:
        """Get the input specifications for all external leaf nodes that need inputs.

        Only includes non-DeviceIO leaves with non-empty input_spec(). Leaves with
        empty input_spec() (e.g. fixed-command retargeters) are not included.

        Returns:
            Dict mapping leaf node name to its input_spec (Dict[str, TensorGroupType]).
            Empty dict if no leaves require caller-provided inputs.

        Example:
            specs = session.get_external_input_specs()
            # specs == {"sim_state": {"joint_positions": TensorGroupType(...)}}
        """
        return {leaf.name: leaf.input_spec() for leaf in self._external_leaves}

    def has_external_inputs(self) -> bool:
        """Check whether this pipeline requires caller-provided external inputs.

        Returns True only if there are leaf nodes that are not DeviceIO sources
        and have a non-empty input_spec() (i.e. they need inputs in step()).
        """
        return len(self._external_leaves) > 0

    def step(
        self,
        *,
        external_inputs: Optional[Dict[str, RetargeterIO]] = None,
        graph_time: Optional[GraphTime] = None,
        execution_events: Optional[ExecutionEvents] = None,
    ):
        """Execute a single step of the teleop session.

        In sync mode, updates DeviceIO session, polls tracker data, merges any
        caller-provided external inputs, and executes the retargeting pipeline
        before returning. In pipelined mode after the seed frame, this call
        submits that work to the retarget worker and returns the latest
        completed output; an unstarted pending request may be replaced by a
        newer submission.

        ``TeleopSession.step()`` is single-caller application-loop API. The
        async runner serializes retarget work internally, but session fields
        such as ``frame_count`` and ``last_step_info`` are intentionally owned
        by the application thread that calls ``step()``.

        Args:
            external_inputs: Optional dict mapping external leaf node names to their
                input data (Dict[str, TensorGroup]). Required when the pipeline has
                leaf nodes that require caller-provided inputs. Use get_external_input_specs()
                to discover what external inputs are expected. Keys that do not correspond
                to an external leaf node or a DeviceIO source name are silently ignored.
                Within each external leaf, keys not declared by that leaf's input_spec()
                are silently ignored.
                Keys that collide with a DeviceIO source name are invalid and cause
                validation to raise.
            graph_time: Optional ``GraphTime`` for this step. When omitted,
                both sim/real time are initialized from the current monotonic clock.
            execution_events: Optional externally-specified execution control events.
                When provided, these values are injected into ``ComputeContext`` and
                the session will skip running ``teleop_control_pipeline`` for this step.

        Returns:
            Dict[str, TensorGroup] - Output from the retargeting pipeline. The
            per-step context is available via ``session.last_context``. In
            pipelined mode this is the latest completed retarget result, which
            can be older than the current submitted frame; age/timing metadata is
            available via ``session.last_step_info``.

        Raises:
            ValueError: If external leaves exist but external_inputs is missing or
                incomplete, or if external_inputs contains keys that collide with
                DeviceIO source names.
            RuntimeError: If a critical DeviceIO/tracker/runtime failure occurs
                while updating the session. This is a fatal condition; the
                application is expected to terminate rather than continue.
        """
        if self.frame_count % 60 == 0:
            self._check_plugin_health()

        execution_mode = (
            self._active_retargeting_execution_mode
            or self.config.retargeting_execution.mode
        )
        # Latch sync vs. pipelined for the active context-manager run. The
        # config object is mutable, but switching modes while a worker is live
        # could otherwise execute the same graph concurrently.
        if execution_mode == RetargetingExecutionMode.PIPELINED:
            return self._step_pipelined(
                external_inputs=external_inputs,
                graph_time=graph_time,
                execution_events=execution_events,
            )

        return self._step_sync(
            external_inputs=external_inputs,
            graph_time=graph_time,
            execution_events=execution_events,
        )

    def _build_step_request(
        self,
        *,
        external_inputs: Optional[Dict[str, RetargeterIO]],
        graph_time: Optional[GraphTime],
        execution_events: Optional[ExecutionEvents],
        snapshot_external_inputs: bool = True,
    ) -> StepRequest:
        """Snapshot caller-owned step arguments into a worker request.

        The whole-step worker polls DeviceIO itself, so only explicit
        ``external_inputs`` cross the thread boundary. Those inputs, along with
        optional graph time and explicit execution events, are filtered to the
        external leaf specs before optionally being copied here so the
        application can safely reuse or mutate its objects after ``step()``
        returns. Sync mode disables the snapshot and uses this same request
        shape only to avoid duplicating the step execution path.
        """
        self._validate_external_inputs(external_inputs)
        external_inputs = self._filter_external_inputs(external_inputs)
        request_external_inputs = None
        if external_inputs:
            request_external_inputs = (
                snapshot_pipeline_inputs(external_inputs)
                if snapshot_external_inputs
                else external_inputs
            )

        return StepRequest(
            frame_id=self.frame_count,
            external_inputs=request_external_inputs,
            graph_time=GraphTime(
                sim_time_ns=graph_time.sim_time_ns,
                real_time_ns=graph_time.real_time_ns,
            )
            if graph_time is not None
            else None,
            execution_events=ExecutionEvents(
                reset=bool(execution_events.reset),
                execution_state=ExecutionState(execution_events.execution_state),
            )
            if execution_events is not None
            else None,
            submitted_time_s=time.monotonic(),
        )

    def _execute_step_request(
        self,
        request: StepRequest,
    ) -> tuple[RetargeterIO, ComputeContext]:
        """Execute one normal synchronous step for ``request``.

        Pipelined mode deliberately moves this whole method to the worker
        thread. Keeping DeviceIO polling, control decoding, and graph execution
        together preserves the old synchronous ordering and avoids passing raw
        DeviceIO source state across threads. Sync mode calls the same method
        directly so the behavioral core stays in one place.
        """
        self.deviceio_session.update()
        pipeline_inputs = self._collect_tracker_data()

        if request.external_inputs:
            pipeline_inputs.update(request.external_inputs)

        now_ns = time.monotonic_ns()
        graph_time = request.graph_time
        if graph_time is None:
            graph_time = GraphTime(sim_time_ns=now_ns, real_time_ns=now_ns)

        execution_events = request.execution_events
        if execution_events is None and self.teleop_control_pipeline is not None:
            control_inputs = {
                k: v
                for k, v in pipeline_inputs.items()
                if k in self._control_leaf_names
            }
            control_outputs = self.teleop_control_pipeline.execute_pipeline(
                control_inputs
            )
            execution_events = self._decode_teleop_control_events(control_outputs)
        elif execution_events is None:
            # Auto-fire START on the first step when no control pipeline is configured
            execution_events = ExecutionEvents(
                reset=False, execution_state=ExecutionState.RUNNING
            )

        context = ComputeContext(
            graph_time=GraphTime(
                sim_time_ns=graph_time.sim_time_ns,
                real_time_ns=graph_time.real_time_ns,
            ),
            execution_events=ExecutionEvents(
                reset=bool(execution_events.reset),
                execution_state=ExecutionState(execution_events.execution_state),
            ),
        )

        # Filter pipeline_inputs to only main leaf inputs
        main_inputs = {
            k: v for k, v in pipeline_inputs.items() if k in self._main_leaf_names
        }
        return self.pipeline.execute_pipeline(main_inputs, context), context

    def _make_retarget_frame(
        self,
        request: StepRequest,
        outputs: RetargeterIO,
        context: ComputeContext,
        *,
        started_time_s: float,
        completed_time_s: float,
    ) -> RetargetFrame:
        """Package one completed request as an owned cached frame.

        The first pipelined call runs on the application thread as a seed frame
        before the worker exists. It still enters the same latest-frame cache,
        so it must follow the worker invariant: cached outputs/context are
        owned by IsaacTeleop and can be returned later without aliasing
        retargeter-owned reusable buffers.
        """
        return RetargetFrame(
            frame_id=request.frame_id,
            outputs=snapshot_retargeter_io(outputs),
            context=snapshot_compute_context(context),
            submitted_time_s=request.submitted_time_s,
            started_time_s=started_time_s,
            completed_time_s=completed_time_s,
            compute_duration_s=completed_time_s - started_time_s,
        )

    def _step_sync(
        self,
        *,
        external_inputs: Optional[Dict[str, RetargeterIO]],
        graph_time: Optional[GraphTime],
        execution_events: Optional[ExecutionEvents],
    ) -> RetargeterIO:
        """Execute retargeting synchronously for exact current-frame behavior.

        This is both the escape hatch for users that cannot accept older-frame
        actions and the reference behavior that pipelined mode overlaps with
        the application loop.
        """
        request = self._build_step_request(
            external_inputs=external_inputs,
            graph_time=graph_time,
            execution_events=execution_events,
            snapshot_external_inputs=False,
        )
        started = time.monotonic()
        result, context = self._execute_step_request(request)
        completed = time.monotonic()

        self._last_context = context
        self._last_execution_state = context.execution_events.execution_state
        self._last_step_info = RetargetingStepInfo(
            returned_frame_id=request.frame_id,
            submitted_frame_id=request.frame_id,
            returned_age_frames=0,
            returned_age_s=completed - request.submitted_time_s,
            compute_duration_s=completed - started,
            ran_synchronously=True,
        )

        self.frame_count += 1
        return result

    def _step_pipelined(
        self,
        *,
        external_inputs: Optional[Dict[str, RetargeterIO]],
        graph_time: Optional[GraphTime],
        execution_events: Optional[ExecutionEvents],
    ) -> RetargeterIO:
        """Submit a full sync step and return the latest completed output.

        Public ``step()`` remains a normal function returning ``RetargeterIO``.
        In pipelined mode it acts as a small scheduler: submit the current
        application-frame request, then return the latest completed frame.
        """
        if self._async_runner is None:
            return self._step_pipelined_seed(
                external_inputs=external_inputs,
                graph_time=graph_time,
                execution_events=execution_events,
            )

        runner = self._async_runner
        try:
            runner.raise_if_failed()
            request = self._build_step_request(
                external_inputs=external_inputs,
                graph_time=graph_time,
                execution_events=execution_events,
            )

            dropped = runner.submit(request)
            frame = runner.latest()
            if frame is None:
                raise AsyncRetargetRunnerStopped(
                    "Async retarget runner has no completed frame to return"
                )
            return self._return_pipelined_frame(
                frame,
                submitted_frame_id=request.frame_id,
                dropped_submissions=dropped,
                ran_synchronously=False,
            )
        except AsyncRetargetWorkerError as exc:
            self._last_step_info = RetargetingStepInfo(worker_exception=exc)
            raise

    def _step_pipelined_seed(
        self,
        *,
        external_inputs: Optional[Dict[str, RetargeterIO]],
        graph_time: Optional[GraphTime],
        execution_events: Optional[ExecutionEvents],
    ) -> RetargeterIO:
        """Run the first pipelined frame synchronously, then start the worker.

        The first call has no previous action to return, so it runs exactly
        once on the application thread. Publishing that seed frame lets later
        calls use the latest-completed path without changing the public return
        type.
        """
        request = self._build_step_request(
            external_inputs=external_inputs,
            graph_time=graph_time,
            execution_events=execution_events,
        )
        started = time.monotonic()
        outputs, context = self._execute_step_request(request)
        completed = time.monotonic()
        frame = self._make_retarget_frame(
            request,
            outputs,
            context,
            started_time_s=started,
            completed_time_s=completed,
        )

        runner = self._ensure_async_runner()
        runner.publish_seed(frame)
        return self._return_pipelined_frame(
            frame,
            submitted_frame_id=request.frame_id,
            dropped_submissions=0,
            ran_synchronously=True,
        )

    def _ensure_async_runner(self) -> AsyncRetargetRunner:
        """Create and start the pipelined retarget worker lazily.

        The worker is session-scoped rather than construction-scoped because
        DeviceIO/OpenXR resources only exist inside the context manager.
        """
        if self._async_runner is None:
            self._async_runner = AsyncRetargetRunner(
                self._execute_step_request,
                self.config.retargeting_execution,
            )
            self._async_runner.start()
        return self._async_runner

    def _return_pipelined_frame(
        self,
        frame: RetargetFrame,
        *,
        submitted_frame_id: int,
        dropped_submissions: int,
        ran_synchronously: bool,
    ) -> RetargeterIO:
        """Publish metadata/context for a pipelined result and finish the step.

        ``last_context`` must always describe the output returned from this
        call, not the request just submitted. The returned output is copied so
        user mutation cannot corrupt the cached latest frame; uncopyable
        outputs should implement ``create_snapshot()`` or use sync mode.
        """
        returned_outputs = snapshot_retargeter_io(frame.outputs)
        returned_context = snapshot_compute_context(frame.context)
        now = time.monotonic()
        returned_age_frames = submitted_frame_id - frame.frame_id
        frame_deadline_miss = returned_age_frames > 1
        self._last_context = returned_context
        self._last_execution_state = returned_context.execution_events.execution_state
        self._last_step_info = RetargetingStepInfo(
            returned_frame_id=frame.frame_id,
            submitted_frame_id=submitted_frame_id,
            returned_age_frames=returned_age_frames,
            returned_age_s=max(0.0, now - frame.submitted_time_s),
            compute_duration_s=frame.compute_duration_s,
            dropped_submissions=dropped_submissions,
            ran_synchronously=ran_synchronously,
            frame_deadline_miss=frame_deadline_miss,
        )
        self.frame_count += 1
        return returned_outputs

    def _decode_teleop_control_events(
        self, control_outputs: RetargeterIO
    ) -> ExecutionEvents:
        """Decode teleop control pipeline outputs into ``ExecutionEvents``."""
        if "teleop_state" not in control_outputs:
            raise ValueError(
                "teleop_control_pipeline must output 'teleop_state' "
                "(one-hot stopped/paused/running)"
            )
        if "reset_event" not in control_outputs:
            raise ValueError(
                "teleop_control_pipeline must output 'reset_event' (single bool pulse)"
            )

        state_group = control_outputs["teleop_state"]
        reset_group = control_outputs["reset_event"]

        expected_states: Set[ExecutionState] = set(teleop_control_states())
        if len(reset_group) != 1:
            raise ValueError(
                "teleop_control_pipeline output 'reset_event' must have 1 bool slot"
            )

        state_flags: Dict[ExecutionState, bool] = {}
        for idx, tensor_type in enumerate(state_group.group_type.types):
            try:
                channel_state = ExecutionState(tensor_type.name)
            except ValueError as exc:
                raise ValueError(
                    "teleop_control_pipeline output 'teleop_state' contains unknown "
                    f"channel '{tensor_type.name}'. Channels must match ExecutionState."
                ) from exc
            if channel_state in state_flags:
                raise ValueError(
                    "teleop_control_pipeline output 'teleop_state' contains duplicate "
                    f"channel '{channel_state.value}'"
                )
            state_flags[channel_state] = bool(state_group[idx])

        if set(state_flags.keys()) != expected_states:
            missing = sorted(
                state.value for state in (expected_states - set(state_flags))
            )
            raise ValueError(
                "teleop_control_pipeline output 'teleop_state' missing required "
                f"ExecutionState channels: {missing}"
            )

        active_states = [state for state, is_active in state_flags.items() if is_active]
        if len(active_states) != 1:
            raise ValueError(
                "teleop_control_pipeline output 'teleop_state' must be one-hot "
                f"(got {state_flags})"
            )
        return ExecutionEvents(
            execution_state=active_states[0],
            reset=bool(reset_group[0]),
        )

    def _validate_external_inputs(
        self,
        external_inputs: Optional[Dict[str, RetargeterIO]],
    ) -> None:
        """Validate that all required external inputs are provided.

        Checks that:
        1. No external input name collides with a DeviceIO source name (always).
        2. If external leaves exist: all required leaf names and keys are present.

        Args:
            external_inputs: The external inputs provided by the caller.

        Raises:
            ValueError: If external input names collide with source names, or if
                external leaves exist but inputs are missing or incomplete.
        """
        if external_inputs:
            source_names = {source.name for source in self._sources}
            provided_names = set(external_inputs.keys())
            collisions = provided_names & source_names
            if collisions:
                raise ValueError(
                    f"External input names collide with DeviceIO source names: {collisions}. "
                    f"Do not provide external inputs for source nodes; they are polled from hardware."
                )

        if not self._external_leaves:
            return

        expected_names = {leaf.name for leaf in self._external_leaves}

        if external_inputs is None:
            raise ValueError(
                f"Pipeline has external (non-DeviceIO) leaf nodes that require inputs: "
                f"{expected_names}. Pass external_inputs to step(). "
                f"Use get_external_input_specs() to discover required inputs."
            )

        provided_names = set(external_inputs.keys())
        missing = expected_names - provided_names
        if missing:
            raise ValueError(
                f"Missing external inputs for leaf nodes: {missing}. "
                f"Expected inputs for: {expected_names}. "
                f"Use get_external_input_specs() to discover required inputs."
            )

        # Validate per-leaf input keys
        for leaf in self._external_leaves:
            leaf_data = external_inputs[leaf.name]
            expected_keys = set(leaf.input_spec().keys())
            provided_keys = set(leaf_data.keys())
            missing_keys = expected_keys - provided_keys
            if missing_keys:
                raise ValueError(
                    f"External input '{leaf.name}' is missing input keys: {missing_keys}. "
                    f"Expected keys: {expected_keys}. "
                    f"Use get_external_input_specs() to discover required inputs."
                )

    def _filter_external_inputs(
        self,
        external_inputs: Optional[Dict[str, RetargeterIO]],
    ) -> Optional[Dict[str, RetargeterIO]]:
        """Drop allowed-but-unused external leaf names and per-leaf input keys.

        The public API has historically ignored extra external leaf names. This
        filtering also keeps sync and pipelined mode aligned when callers pass
        extra per-leaf values. Keep required input names, ignore extras.
        """
        if not external_inputs:
            return None
        leaves_by_name = {leaf.name: leaf for leaf in self._external_leaves}
        filtered_inputs: Dict[str, RetargeterIO] = {}
        for name, values in external_inputs.items():
            leaf = leaves_by_name.get(name)
            if leaf is None:
                continue
            expected_keys = set(leaf.input_spec().keys())
            filtered_inputs[name] = {
                input_name: value
                for input_name, value in values.items()
                if input_name in expected_keys
            }
        return filtered_inputs or None

    def _collect_tracker_data(self) -> Dict[str, Any]:
        """Collect raw tracking data from all sources and map to module names.

        Each source polls its own tracker via poll_tracker() and returns
        a RetargeterIO dict matching its input_spec().

        Returns:
            Dict mapping source module names to their complete input dictionaries.
            Each input dictionary maps input names to TensorGroups containing raw data.
        """
        return {
            source.name: source.poll_tracker(self.deviceio_session)
            for source in self._sources
        }

    def _check_plugin_health(self):
        """Check health of all running plugins."""
        for plugin_context in self.plugin_contexts:
            plugin_context.check_health()

    def get_elapsed_time(self) -> float:
        """Get elapsed time since session started."""
        return time.time() - self.start_time

    # ========================================================================
    # Context manager protocol
    # ========================================================================

    def __enter__(self):
        """Enter the context - create sessions and resources.

        Creates OpenXR session (unless external handles were provided),
        DeviceIO session, plugins, and UI. All preparation was done in __init__.

        When ``config.mode`` is ``SessionMode.REPLAY``, an OpenXR session is **not**
        created; instead a replay DeviceIO session is opened from ``config.mcap_config``.

        When ``config.oxr_handles`` is set (live mode), the provided handles are passed
        directly to ``DeviceIOSession.run()`` and no internal OpenXR session
        is created.  The caller is responsible for the external session lifetime.

        Returns:
            self for context manager protocol
        """
        # Reset run-scoped plugin containers on each context entry.
        self.plugin_managers = []
        self.plugin_contexts = []

        # Auto-populate mcap_config from pipeline sources if recording or replaying.
        mcap_config = None
        if self.config.mcap_config is not None:
            mcap_tracker_names = [
                (source.get_tracker(), source.name) for source in self._sources
            ]
            mcap_tracker_names.extend(self.config.mcap_config.get_tracker_names())
            if self.config.mode == SessionMode.REPLAY:
                mcap_config = deviceio.McapReplayConfig(
                    self.config.mcap_config.filename,
                    mcap_tracker_names,
                )
            else:
                mcap_config = deviceio.McapRecordingConfig(
                    self.config.mcap_config.filename,
                    mcap_tracker_names,
                )

        if self.config.mode == SessionMode.REPLAY:
            self.deviceio_session = self._exit_stack.enter_context(
                deviceio.ReplaySession.run(mcap_config)
            )
        else:
            # Collect trackers from source nodes and config
            trackers = [source.get_tracker() for source in self._sources]
            if self.config.trackers:
                trackers.extend(self.config.trackers)

            # Get required extensions from all trackers
            required_extensions = deviceio.DeviceIOSession.get_required_extensions(
                trackers
            )

            # Resolve OpenXR handles
            if self.config.oxr_handles is not None:
                handles = self.config.oxr_handles
            else:
                self._oxr_session = self._exit_stack.enter_context(
                    oxr.OpenXRSession(self.config.app_name, required_extensions)
                )
                handles = self._oxr_session.get_handles()

            # Create DeviceIO session with all trackers
            self.deviceio_session = self._exit_stack.enter_context(
                deviceio.DeviceIOSession.run(trackers, handles, mcap_config)
            )

        # Initialize plugins (if any)
        if self.config.plugins:
            for plugin_config in self.config.plugins:
                if not plugin_config.enabled:
                    continue

                # Validate search paths
                valid_paths = [p for p in plugin_config.search_paths if p.exists()]
                if not valid_paths:
                    continue

                # Create plugin manager
                manager = pm.PluginManager([str(p) for p in valid_paths])
                self.plugin_managers.append(manager)

                # Check if plugin exists
                plugins = manager.get_plugin_names()
                if plugin_config.plugin_name not in plugins:
                    continue

                # Start plugin and add to exit stack
                context = manager.start(
                    plugin_config.plugin_name,
                    plugin_config.plugin_root_id,
                    plugin_config.plugin_args,
                )
                self._exit_stack.enter_context(context)
                self.plugin_contexts.append(context)

        # Initialize runtime state
        self.frame_count = 0
        self.start_time = time.time()
        self._last_context = None
        self._last_step_info = RetargetingStepInfo()
        self._last_execution_state = None
        self._async_runner = None
        self._active_retargeting_execution_mode = self.config.retargeting_execution.mode

        self._setup_complete = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context - cleanup resources."""
        if not self._setup_complete:
            return False

        runner_error = None
        if self._async_runner is not None:
            runner = self._async_runner
            runner.stop()
            try:
                runner.raise_if_failed(only_unreported=True)
            except BaseException as err:
                if exc_type is None:
                    runner_error = err
                else:
                    logger.error(
                        "Async retarget worker failed during TeleopSession cleanup",
                        exc_info=(type(err), err, err.__traceback__),
                    )
            self._async_runner = None
        self._active_retargeting_execution_mode = None

        # ExitStack automatically cleans up all managed contexts in reverse order.
        # Preserve TeleopSession's historical behavior of not suppressing
        # exceptions from the user body, even if a child context manager would.
        self._exit_stack.__exit__(exc_type, exc_val, exc_tb)
        self._exit_stack = ExitStack()

        if runner_error is not None:
            raise runner_error

        return False
