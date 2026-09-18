from __future__ import annotations

import asyncio
import copy
import inspect
import os
import pathlib
from typing import Literal

import pytest
import sergent_py
import sergent_py.facade as battery_facade
import sergent_py_providers.client as provider_client

from sergent_py import (
    Target,
    ImagePart,
    Intent_Continue,
    JsonlRunRecordWriter,
    ModelRequest,
    ModelResponse,
    Operation,
    ProposalSchema,
    IntentProposal_PassThrough,
    SceneIdentity,
    SergentRuntime,
    StrictModel,
    VerificationReport,
    apply_operations_in_order,
    basic_identity_verifier,
    create_sergent,
    field_identity,
    make_llm_client,
    new_id,
    pydantic_clone,
    whole_scene_has_target,
    whole_scene_target,
)
import sergent_py_core.plan as core_plan


class _NoTargetScene:
    def __init__(self) -> None:
        self.scene_id = new_id("scene")


class _UnusedOperation(Operation, frozen=True):
    """Provide a closed Operation vocabulary for no-target wiring."""

    call: Literal["unused"] = "unused"

    def apply(self, scene: object, _target: Target) -> object:
        return scene


class _Recipe(sergent_py.SergentRecipe[_NoTargetScene, IntentProposal_PassThrough, object]):
    intent_proposal_type = IntentProposal_PassThrough
    operation_registry = sergent_py.OperationRegistry((_UnusedOperation,))
    no_target_error = sergent_py.RunError(kind="no_target", message="no target available")

    def derive_intent(
        self,
        _scene: object,
        _identity: SceneIdentity,
        _target: Target,
        _intent_proposal: IntentProposal_PassThrough,
    ) -> object:
        return object()


class _NoTargetActions:
    def identity(self, scene: _NoTargetScene) -> SceneIdentity:
        return SceneIdentity(scene_id=scene.scene_id, revision=0)

    def clone(self, scene: _NoTargetScene) -> _NoTargetScene:
        return copy.deepcopy(scene)

    def select_target(self, scene: _NoTargetScene) -> None:
        return None

    def has_target(self, scene: _NoTargetScene, target: Target) -> bool:
        return False

    def apply(
        self,
        scene: _NoTargetScene,
        target: Target,
        operations: list[Operation],
    ) -> _NoTargetScene:
        raise AssertionError("no-target runs never apply operations")

    def verify(
        self,
        before: _NoTargetScene,
        after: _NoTargetScene,
        target: Target,
        operations: list[Operation],
    ) -> VerificationReport:
        raise AssertionError("no-target runs never verify")


class _UnusedClient:
    async def invoke(self, request: ModelRequest) -> tuple[ModelResponse, dict[str, object]]:
        raise AssertionError("client must not be invoked")


class _OrderedObserver:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def progress(self, snapshot: object) -> None:
        pass

    def finished(self, result: object) -> None:
        self.events.append(self.name)


def test_make_llm_client_returns_an_unbound_real_client() -> None:
    assert inspect.signature(make_llm_client).parameters == {}
    client = make_llm_client()
    assert type(client) is provider_client.LlmClient


def test_create_sergent_wires_a_runtime() -> None:
    runtime = create_sergent(
        scene=_NoTargetActions(),
        recipe=_Recipe(),
        client=_UnusedClient(),
    )
    assert isinstance(runtime, SergentRuntime)


def test_create_sergent_constructs_a_client_without_model_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def make_client() -> _UnusedClient:
        nonlocal calls
        calls += 1
        return _UnusedClient()

    monkeypatch.setattr(battery_facade, "make_llm_client", make_client)
    runtime = create_sergent(scene=_NoTargetActions(), recipe=_Recipe())

    assert isinstance(runtime, SergentRuntime)
    assert calls == 1


def test_create_sergent_preserves_the_run_boundary_model_name() -> None:
    runtime = create_sergent(
        scene=_NoTargetActions(),
        recipe=_Recipe(),
        client=_UnusedClient(),
    )
    model_name = "ollama/team/qwen3.5:2b-mlx"

    result = asyncio.run(runtime.run(_NoTargetScene(), sergent_py.MindBuf(), model_name=model_name))

    assert result.run_record.model_name == model_name


def test_create_sergent_delivers_observers_in_order_and_preserves_duplicate_slots() -> None:
    def delivered_names(slots: tuple[_OrderedObserver, ...]) -> list[str]:
        events: list[str] = []
        for slot in slots:
            slot.events = events
        runtime = create_sergent(
            scene=_NoTargetActions(),
            recipe=_Recipe(),
            client=_UnusedClient(),
            observers=(slot for slot in slots),
        )
        result = asyncio.run(
            runtime.run(_NoTargetScene(), sergent_py.MindBuf(), model_name="test/fake")
        )
        assert result.status == "failure"
        return events

    first = _OrderedObserver("first", [])
    second = _OrderedObserver("second", [])
    third = _OrderedObserver("third", [])

    assert delivered_names((first,)) == ["first"]
    assert delivered_names((first, second)) == ["first", "second"]
    assert delivered_names((first, second, third)) == ["first", "second", "third"]
    assert delivered_names((first, first)) == ["first", "first"]


def test_run_record_writer_failure_is_contained_by_assembled_runtime(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = JsonlRunRecordWriter(tmp_path, "battery")

    def fail_sync(_descriptor: int) -> None:
        raise OSError("sync failed")

    monkeypatch.setattr(os, "fsync", fail_sync)
    runtime = create_sergent(
        scene=_NoTargetActions(),
        recipe=_Recipe(),
        client=_UnusedClient(),
        observers=(writer,),
    )

    result = asyncio.run(
        runtime.run(_NoTargetScene(), sergent_py.MindBuf(), model_name="test/fake")
    )

    assert result.status == "failure"
    assert len(result.observer_errors) == 1
    error = result.observer_errors[0]
    assert error.kind == "observer_error"
    assert error.metadata["callback"] == "finished"
    assert error.metadata["observer_type"] == (
        "sergent_py_runtime.run_record.run_record_file.JsonlRunRecordWriter"
    )
    writer.close()


def test_curated_reexports_are_present() -> None:
    expected = {
        "SergentRuntime",
        "SceneState",
        "RunHandle",
        "CancelToken",
        "SergentResult",
        "RunObserver",
        "JsonlRunRecordWriter",
        "SceneActions",
        "SergentRecipe",
        "ModelClient",
        "ModelRequest",
        "ProposalSchema",
        "ModelError",
        "ModelIdentity",
        "CallUsage",
        "Target",
        "SceneIdentity",
        "Operation",
        "OperationRegistry",
        "Patch",
        "ExecutionPlan",
        "PlanProposal",
        "IntentProposal_PassThrough",
        "Intent_Continue",
        "RebasedPatch",
        "MergeConflict",
        "PatchRebaseRequest",
        "CommitResult",
        "MergeConflictError",
        "VerificationReport",
        "pydantic_clone",
        "field_identity",
        "apply_operations_in_order",
        "whole_scene_target",
        "whole_scene_has_target",
        "basic_identity_verifier",
        "fan_out",
        "CapturedValue",
        "ModelAttemptRecord",
        "ModelCallRecord",
        "RunRecord",
        "RunStepRecord",
        "ImagePart",
        "ModelSettings",
        "ThinkingEffort",
        "CREDENTIAL_ENV_VARS",
    }
    assert all(hasattr(sergent_py, name) for name in expected)


def test_retired_model_selection_helpers_are_not_public() -> None:
    assert not hasattr(sergent_py, "aliases")
    assert not hasattr(sergent_py, "resolve_alias")


def test_pass_through_intent_is_exported() -> None:
    assert sergent_py.IntentProposal_PassThrough is IntentProposal_PassThrough


def test_proposal_schema_is_exported() -> None:
    assert sergent_py.ProposalSchema is ProposalSchema


def test_continue_intent_is_exported() -> None:
    assert sergent_py.Intent_Continue is Intent_Continue


def test_plan_proposal_is_exported_without_internal_helpers() -> None:
    assert sergent_py.PlanProposal is core_plan.PlanProposal
    assert not hasattr(sergent_py, "execution_plan_from_operations")


def test_image_part_is_exported() -> None:
    assert sergent_py.ImagePart is ImagePart


class _Block(StrictModel):
    block_id: str
    generated: list[str] = []


class _DomainScene(StrictModel):
    scene_id: str = ""
    revision: int = 0
    block: _Block


class _Op(Operation, frozen=True):
    call: Literal["test_append"] = "test_append"
    text: str

    def apply(self, scene: object, _target: Target) -> object:
        if isinstance(scene, _DomainScene):
            scene.block.generated.append(self.text)
        return scene


def _make_scene() -> _DomainScene:
    return _DomainScene(scene_id=new_id("scene"), block=_Block(block_id=new_id("block")))


def test_scene_helper_clone_identity_target_and_apply() -> None:
    scene = _make_scene()
    identity = field_identity("scene_id", "revision")

    clone = pydantic_clone(scene)
    clone.block.generated.append("changed")

    assert clone is not scene
    assert scene.block.generated == []
    assert identity(scene) == SceneIdentity(scene_id=scene.scene_id, revision=0)

    target = whole_scene_target(scene, identity)
    assert target == Target(target_id=scene.scene_id)
    assert whole_scene_target(scene, scene.scene_id) == target
    assert whole_scene_has_target(scene, target, identity)
    assert not whole_scene_has_target(scene, Target(target_id=new_id("scene")), identity)

    updated = apply_operations_in_order(
        pydantic_clone(scene),
        target,
        [_Op(text="first"), _Op(text="second")],
    )
    assert updated.block.generated == ["first", "second"]
    assert scene.block.generated == []

    with pytest.raises(ValueError, match="at least one operation"):
        apply_operations_in_order(scene, target, [])


def test_basic_identity_verifier_reports_identity_issues() -> None:
    scene_id = new_id("scene")
    identity = field_identity("scene_id", "revision")
    before = _DomainScene(
        scene_id=scene_id,
        revision=2,
        block=_Block(block_id=new_id("block")),
    )
    after = before.model_copy(update={"revision": 3})

    assert basic_identity_verifier(before, after, identity) == []

    changed = after.model_copy(update={"scene_id": new_id("scene"), "revision": 5})
    issues = basic_identity_verifier(
        before,
        changed,
        identity,
    )

    assert issues == [
        "scene identity changed",
        "scene revision mismatch",
    ]
