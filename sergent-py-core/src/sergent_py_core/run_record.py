"""Define the authoritative Run Record and its evidence values. @sergent/docs/run-record-spec.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import typing

import pydantic

import sergent_py_core.errors as errors
import sergent_py_core.identifiers as identifiers
import sergent_py_core.model_calls as model_calls
import sergent_py_core.scene as scene
import sergent_py_core.strict_model as strict_model
import sergent_py_core.timing as timing

RunStatus = typing.Literal["success", "failure", "cancelled"]
_RunRecordStatus = typing.Literal["running", "success", "failure", "cancelled"]


class CapturedValue(strict_model.StrictModel):
    """Carry one best-effort captured value and its local capture failure. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    value: object | None = None
    value_type: str
    error: errors.RunError | None = None

    @pydantic.computed_field
    @property
    def status(self) -> typing.Literal["captured", "capture_error"]:
        """Derive capture status from the local error fact. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return "captured" if self.error is None else "capture_error"


class RunTerminalRecord(strict_model.StrictModel):
    """Carry independently captured terminal message and metadata. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    message: CapturedValue
    metadata: CapturedValue


class SceneTransition(strict_model.StrictModel):
    """Carry Scene identity and revisions entering and leaving a Run. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    scene_id: str
    revision_before: int = pydantic.Field(ge=0)
    revision_after: int | None = pydantic.Field(default=None, ge=0)

    @pydantic.field_validator("scene_id")
    @classmethod
    def _scene_id_is_id(cls, value: str) -> str:
        """Admit only framework-shaped Scene identifiers."""
        return identifiers.checked_id(value)

    @classmethod
    def from_identity(cls, identity: scene.SceneIdentity) -> SceneTransition:
        """Open a Scene transition from its entering identity. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return cls(scene_id=identity.scene_id, revision_before=identity.revision)

    def committed(self, revision_after: int) -> SceneTransition:
        """Return a replacement carrying the committed revision. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return SceneTransition(
            scene_id=self.scene_id,
            revision_before=self.revision_before,
            revision_after=revision_after,
        )


class Cancellation(strict_model.StrictModel):
    """Carry cancellation request facts when cancellation was requested. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    requested_at: str
    checkpoint: str | None = None

    @classmethod
    def requested(cls, requested_at: str | None, checkpoint: str | None) -> Cancellation:
        """Create request facts, stamping a missing request time. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return cls(requested_at=requested_at or timing.utc_now(), checkpoint=checkpoint)


class RunOutcome(strict_model.StrictModel):
    """Carry one coherent running or terminal Run verdict. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    status: _RunRecordStatus = "running"
    error: errors.RunError | None = None
    terminal: RunTerminalRecord | None = None

    @pydantic.model_validator(mode="after")
    def _error_and_terminal_match_status(self) -> RunOutcome:
        """Keep status, failure, and terminal success facts coherent."""
        if self.status in {"running", "success"} and self.error is not None:
            msg = f"{self.status} outcome cannot carry an error"
            raise ValueError(msg)
        if self.status in {"failure", "cancelled"} and self.error is None:
            msg = f"{self.status} outcome requires an error"
            raise ValueError(msg)
        if self.status != "success" and self.terminal is not None:
            msg = "terminal data is allowed only on a success outcome"
            raise ValueError(msg)
        return self


class ModelCallPayloads(strict_model.StrictModel):
    """Carry one call's captured payloads apart from typed call facts. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    request: CapturedValue
    raw_response: str | None = None
    parsed_json: dict[str, typing.Any] | None = None
    parsed_proposal: CapturedValue | None = None


class ModelCallRecord(strict_model.StrictModel):
    """Carry one model call's evidence inside a Step Record. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    proposal_schema: model_calls.ProposalSchema
    model_name: str
    identity: model_calls.ModelIdentity | None = None
    payloads: ModelCallPayloads
    usage: model_calls.CallUsage | None = None
    attempts: list[model_calls.ModelAttemptRecord] = pydantic.Field(default_factory=list)


class RunStepRecord(strict_model.StrictModel):
    """Carry one started step's evidence in the Run Record Ledger. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    name: str
    status: _RunRecordStatus
    timing: timing.TimeSpan
    input: CapturedValue | None = None
    output: CapturedValue | None = None
    error: errors.RunError | None = None
    model_call: ModelCallRecord | None = None


class RunRecord(strict_model.StrictModel):
    """Carry the inert authoritative evidence for one Run. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    run_id: str
    model_name: str
    timing: timing.TimeSpan
    scene: SceneTransition | None = None
    steps: list[RunStepRecord] = pydantic.Field(default_factory=list)
    outcome: RunOutcome = pydantic.Field(default_factory=RunOutcome)
    cancellation: Cancellation | None = None

    @pydantic.field_validator("run_id")
    @classmethod
    def _run_record_id_is_run(cls, value: str) -> str:
        """Admit only framework Run identifiers."""
        return identifiers.checked_id(value, "run")

    def model_call_usages(self) -> list[model_calls.CallUsage | None]:
        """Return usage slots for recorded model calls in step order. @sergent/docs/execution-model.md"""
        return [step.model_call.usage for step in self.steps if step.model_call is not None]

    def total_output_tokens(self) -> int | None:
        """Return a complete token total or ``None`` for incomplete usage. @sergent/docs/execution-model.md"""
        total = 0
        for usage in self.model_call_usages():
            if usage is None:
                return None
            output_tokens = usage.output_tokens()
            if output_tokens is None:
                return None
            total += output_tokens
        return total
