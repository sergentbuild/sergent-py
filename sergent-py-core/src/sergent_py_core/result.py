"""Define the terminal return from one Sergent Run. @sergent/docs/execution-model.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import typing

import pydantic

import sergent_py_core.errors as errors
import sergent_py_core.run_record as run_record_values
import sergent_py_core.scene as scene
import sergent_py_core.strict_model as strict_model

SceneT = typing.TypeVar("SceneT")


class SergentResult(strict_model.StrictModel, typing.Generic[SceneT]):
    """Return terminal Scene, closed Run Record, and observer failures. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    stage: str
    scene: SceneT
    run_record: run_record_values.RunRecord
    terminal_message: str | None = None
    terminal_metadata: dict[str, object] = pydantic.Field(default_factory=dict)
    observer_errors: list[errors.RunError] = pydantic.Field(default_factory=list)

    @pydantic.computed_field
    @property
    def status(self) -> run_record_values.RunStatus:
        """Return the terminal status from the Run Record. @sergent/docs/run-record-spec.md"""
        status = self.run_record.outcome.status
        assert status != "running"
        return status

    @pydantic.computed_field
    @property
    def identity(self) -> scene.SceneIdentity:
        """Return entering or committed Scene identity from the Run Record. @sergent/docs/run-record-spec.md"""
        transition = self.run_record.scene
        assert transition is not None
        revision = transition.revision_after
        if revision is None:
            revision = transition.revision_before
        return scene.SceneIdentity(scene_id=transition.scene_id, revision=revision)

    @pydantic.computed_field
    @property
    def error(self) -> errors.RunError | None:
        """Return the terminal failure from the Run Record. @sergent/docs/run-record-spec.md"""
        return self.run_record.outcome.error
