"""Build progress, RunRecord, and terminal results. @sergent/docs/run-record-spec.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import dataclasses
import time
import typing

import sergent_py_core.errors as core_errors
import sergent_py_core.patch as core_patch
import sergent_py_core.result as core_result
import sergent_py_core.run_record as core_run_record
import sergent_py_core.scene as core_scene
import sergent_py_core.timing as core_timing
import sergent_py_core.model_calls as core_model_calls
import sergent_py_runtime.run_record.run_capture as runtime_capture
import sergent_py_runtime.lifecycle.observe as runtime_observe

if typing.TYPE_CHECKING:
    import sergent_py_runtime.lifecycle.concurrency as runtime_concurrency

SceneT = typing.TypeVar("SceneT")


@dataclasses.dataclass(frozen=True)
class _Outcome(typing.Generic[SceneT]):
    """Carry the facts required to close one Run. @sergent-py-runtime/docs/KNOWLEDGE.md"""

    status: core_run_record.RunStatus
    scene: SceneT
    revision_after: int | None
    error: core_errors.RunError | None
    terminal_message: str | None
    terminal_metadata: dict[str, object]


@dataclasses.dataclass
class _ActiveCall:
    """Track the open model call record for one step."""

    record: core_run_record.ModelCallRecord


@dataclasses.dataclass
class _ActiveStep:
    """Track mutable evidence while one Step Record is open."""

    step: core_run_record.RunStepRecord
    started_perf: float = dataclasses.field(default_factory=time.perf_counter)
    output: dict[str, object] = dataclasses.field(default_factory=dict)
    call: _ActiveCall | None = None

    def begin_call(self, record: core_run_record.ModelCallRecord) -> None:
        """Attach one open model call to the active Step Record."""
        self.call = _ActiveCall(record)
        self.step.model_call = record

    def end_call(self) -> None:
        """Clear the active model call after its evidence closes."""
        self.call = None

    def elapsed_ms(self) -> int:
        """Return elapsed whole milliseconds for the active step."""
        return int((time.perf_counter() - self.started_perf) * 1000)


class Run(typing.Generic[SceneT]):
    """Build progress and the Run Record for one run. @sergent/docs/run-record-spec.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(self, *, run_id: str, model_name: str) -> None:
        self.run_id = run_id
        self.model_name = model_name
        self.stage: str = runtime_observe.Stage.QUEUED
        self.status: runtime_observe.ProgressStatus = runtime_observe.Stage.QUEUED.value
        self.base_scene: SceneT | None = None
        self.identity: core_scene.SceneIdentity | None = None
        self._started_perf = time.perf_counter()
        self.run_record = core_run_record.RunRecord(
            run_id=run_id,
            model_name=model_name,
            timing=core_timing.TimeSpan.begin(),
        )
        self._active: _ActiveStep | None = None

    def begin(self, base_scene: SceneT, identity: core_scene.SceneIdentity) -> None:
        """Bind base Scene facts to the Run Record. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self.base_scene = base_scene
        self.identity = identity
        self.run_record.scene = core_run_record.SceneTransition.from_identity(identity)

    def advance(self, stage: runtime_observe.Stage) -> None:
        """Advance sanitized progress to one stage. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self.stage = stage
        self.status = "running"

    def snapshot(self) -> runtime_observe.ProgressSnapshot:
        """Return progress without model or Scene content. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return runtime_observe.ProgressSnapshot(
            run_id=self.run_id,
            scene_id=self.identity.scene_id if self.identity is not None else None,
            stage=self.stage,
            status=self.status,
            revision=self.identity.revision if self.identity is not None else 0,
        )

    def open_step(self, name: str, input_value: object | None) -> None:
        """Open the next Step Record with captured input. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        step = core_run_record.RunStepRecord(
            name=name,
            status="running",
            timing=core_timing.TimeSpan.begin(),
            input=self.capture_value(input_value) if input_value is not None else None,
        )
        self.run_record.steps.append(step)
        self._active = _ActiveStep(step)

    def update_step_output(self, **values: object) -> None:
        """Merge captured output into the active Step Record. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None:
            return
        active.output.update(values)
        active.step.output = self.capture_value(active.output)

    def finish_step(
        self,
        status: core_run_record.RunStatus,
        *,
        output: object | None = None,
        error: core_errors.RunError | None = None,
    ) -> None:
        """Close the active Step Record with its verdict. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None:
            return
        step = active.step
        step.status = status
        step.timing = step.timing.closed_now(active.elapsed_ms())
        if output is not None:
            step.output = self.capture_value(output)
        step.error = error
        self._active = None

    def capture_value(self, value: object) -> core_run_record.CapturedValue:
        """Capture one value for the Run Record. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return runtime_capture.capture_value(value)

    def start_model_call(self, request: core_model_calls.ModelRequest) -> None:
        """Attach request evidence to the active model call. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None:
            return
        active.begin_call(
            core_run_record.ModelCallRecord(
                proposal_schema=request.proposal_schema,
                model_name=request.model_name,
                payloads=core_run_record.ModelCallPayloads(request=self.capture_value(request)),
            )
        )

    def finish_model_call(
        self, response: core_model_calls.ModelResponse, proposal: object | None
    ) -> None:
        """Close the active call with returned evidence. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None or active.call is None:
            return
        self._complete_model_call(active.call, response, proposal)
        active.end_call()

    def _fail_model_call(self, error: core_model_calls.ModelError) -> None:
        """Close the active call from authoritative failure facts.

        @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None or active.call is None:
            return
        self._complete_model_call(active.call, error, None)
        active.end_call()

    def _complete_model_call(
        self,
        call: _ActiveCall,
        outcome: core_model_calls.ModelResponse | core_model_calls.ModelError,
        proposal: object | None,
    ) -> None:
        """Store a call outcome without invented attempt evidence. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        response = outcome.response if isinstance(outcome, core_model_calls.ModelError) else outcome
        call.record.identity = outcome.identity
        call.record.payloads = core_run_record.ModelCallPayloads(
            request=call.record.payloads.request,
            raw_response=response.raw_output if response is not None else None,
            parsed_json=response.parsed_json if response is not None else None,
            parsed_proposal=self.capture_value(proposal) if proposal is not None else None,
        )
        call.record.usage = response.usage if response is not None else None
        call.record.attempts = list(outcome.attempts)

    def success(
        self,
        scene: SceneT,
        identity_after: core_scene.SceneIdentity,
        *,
        terminal_metadata: dict[str, object] | None = None,
    ) -> core_result.SergentResult[SceneT]:
        """Close a committed run at its resulting revision. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._finish(
            _Outcome(
                status="success",
                scene=scene,
                revision_after=identity_after.revision,
                error=None,
                terminal_message=None,
                terminal_metadata=dict(terminal_metadata or {}),
            )
        )

    def success_without_patch(
        self,
        scene: SceneT,
        identity: core_scene.SceneIdentity,
        *,
        terminal_message: str | None = None,
        terminal_metadata: dict[str, object] | None = None,
    ) -> core_result.SergentResult[SceneT]:
        """Close a stop run without mutation or revision advance. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._finish(
            _Outcome(
                status="success",
                scene=scene,
                revision_after=identity.revision,
                error=None,
                terminal_message=terminal_message,
                terminal_metadata=dict(terminal_metadata or {}),
            )
        )

    def failure(self, error: BaseException) -> core_result.SergentResult[SceneT]:
        """Contain ordinary failure after Scene facts exist. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run_error = self._error_record(error)
        if isinstance(error, core_model_calls.ModelError):
            self._fail_model_call(error)
        scene = self.base_scene
        identity = self.identity
        if scene is None or identity is None:
            # Before ``begin`` no scene facts exist; the failure cannot be contained.
            raise error
        return self._finish(
            _Outcome(
                status="failure",
                scene=scene,
                revision_after=None,
                error=run_error,
                terminal_message=run_error.message,
                terminal_metadata=dict(run_error.metadata),
            )
        )

    def error_record(self, error: BaseException) -> core_errors.RunError:
        """Capture an exception in the Run Record. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return self._error_record(error)

    def cancelled(
        self,
        scene: SceneT,
        *,
        checkpoint: str | None = None,
        cancel: runtime_concurrency.CancelToken,
    ) -> core_result.SergentResult[SceneT]:
        """Close pre-commit cancellation with its original Scene. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self.run_record.cancellation = core_run_record.Cancellation.requested(
            cancel.requested_at, checkpoint
        )
        run_error = core_errors.RunError(kind="cancelled", message="run cancelled before commit")
        self._cancel_current_model_call()
        return self._finish(
            _Outcome(
                status="cancelled",
                scene=scene,
                revision_after=None,
                error=run_error,
                terminal_message=run_error.message,
                terminal_metadata={},
            )
        )

    def _cancel_current_model_call(self) -> None:
        """Detach an interrupted call without invented attempts.

        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        active = self._active
        if active is None:
            return
        call = active.call
        if call is None:
            return
        active.end_call()

    def no_target(
        self,
        scene: SceneT,
        error: core_errors.RunError,
    ) -> core_result.SergentResult[SceneT]:
        """Close target failure against the unchanged Scene. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        error = error.model_copy(deep=True)
        return self._finish(
            _Outcome(
                status="failure",
                scene=scene,
                revision_after=None,
                error=error,
                terminal_message=error.message,
                terminal_metadata=dict(error.metadata),
            )
        )

    def _finish(self, outcome: _Outcome[SceneT]) -> core_result.SergentResult[SceneT]:
        """Close timing, Run Record, and result from one verdict. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        self.status = outcome.status
        if self._active is not None:
            self.finish_step(outcome.status, error=outcome.error)
        terminal = self._capture_terminal(outcome)
        self.run_record.outcome = core_run_record.RunOutcome(
            status=outcome.status, error=outcome.error, terminal=terminal
        )
        duration_ms = int((time.perf_counter() - self._started_perf) * 1000)
        self.run_record.timing = self.run_record.timing.closed_now(duration_ms)
        if outcome.revision_after is not None and self.run_record.scene is not None:
            self.run_record.scene = self.run_record.scene.committed(outcome.revision_after)
        return core_result.SergentResult(
            stage=self.stage,
            scene=outcome.scene,
            run_record=self.run_record,
            terminal_message=outcome.terminal_message,
            terminal_metadata=dict(outcome.terminal_metadata),
        )

    def _capture_terminal(
        self, outcome: _Outcome[SceneT]
    ) -> core_run_record.RunTerminalRecord | None:
        """Capture optional terminal success facts. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        if outcome.status != "success" or (
            outcome.terminal_message is None and not outcome.terminal_metadata
        ):
            return None
        return core_run_record.RunTerminalRecord(
            message=self.capture_value(outcome.terminal_message),
            metadata=self.capture_value(dict(outcome.terminal_metadata)),
        )

    def _error_record(self, error: BaseException) -> core_errors.RunError:
        """Build failure data with current step context.

        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        step_name = self._active.step.name if self._active else None
        return runtime_capture.error_record(error, current_step=step_name)

    def patch_summary(self, patch: core_patch.Patch) -> dict[str, object]:
        """Return Patch evidence for the Run Record. @sergent/docs/run-record-spec.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return runtime_capture.patch_summary(patch)
