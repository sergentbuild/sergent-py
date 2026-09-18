"""Self-contained demo domain that exercises every runtime interface."""

from __future__ import annotations

import asyncio
import collections.abc as cabc
import copy
import json
import typing

import pydantic
import sergent_py_core.errors as core_errors
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.model_calls as core_model_calls
import sergent_py_core.operation as core_operation
import sergent_py_core.patch as core_patch
import sergent_py_core.recipe as core_recipe
import sergent_py_core.result as core_result
import sergent_py_core.scene as core_scene
import sergent_py_core.scene_actions as core_scene_actions
import sergent_py_core.strict_model as core_strict_model
import sergent_py_core.target as core_target
import sergent_py_core.timing as core_timing
import sergent_py_core.identifiers as identifiers
import sergent_py_core.model_calls as model_calls
import sergent_py_core.proposals.operation_registry as operation_registry
import sergent_py_runtime.lifecycle.observe as observe
import sergent_py_runtime.proposals.intent_proposals as intent_proposals


class DemoBlock(core_strict_model.StrictModel):
    block_id: str
    text: str
    generated: list[str] = []


class DemoScene(core_strict_model.StrictModel):
    scene_id: str = ""
    blocks: list[DemoBlock] = []
    selected_block_id: str | None = None

    @pydantic.model_validator(mode="after")
    def _default_scene_id(self) -> DemoScene:
        if not self.scene_id:
            object.__setattr__(self, "scene_id", identifiers.new_id("scene"))
        return self


class DemoIntentProposal(core_strict_model.StrictModel):
    pass


class DemoModelSettings(core_strict_model.StrictModel):
    thinking_effort: str = "high"
    max_output_tokens: int = 4096


class DemoIntent(core_strict_model.StrictModel):
    base_scene_id: str
    base_revision: int


class DemoOperation(core_operation.Operation, frozen=True):
    call: typing.Literal["demo_append"] = "demo_append"
    text: str

    def validate_for(
        self,
        scene: object,
        intent: object,
        target: core_target.Target,
    ) -> None:
        if not isinstance(scene, DemoScene) or not isinstance(intent, DemoIntent):
            msg = "demo operation validation received wrong domain objects"
            raise ValueError(msg)
        if not any(block.block_id == target.target_id for block in scene.blocks):
            msg = "demo operation target missing"
            raise ValueError(msg)

    def apply(self, scene: object, target: core_target.Target) -> DemoScene:
        if not isinstance(scene, DemoScene):
            msg = "demo operation apply received wrong scene"
            raise ValueError(msg)
        for block in scene.blocks:
            if block.block_id == target.target_id:
                block.generated.append(self.text)
                scene.selected_block_id = target.target_id
                return scene
        msg = f"unknown target block: {target.target_id}"
        raise ValueError(msg)


_DEMO_OPERATION_REGISTRY = operation_registry.OperationRegistry((DemoOperation,))
DemoPatch = core_patch.Patch


def make_scene(*, block_count: int = 1, selected: bool = True) -> DemoScene:
    """Build a demo scene with ``block_count`` blocks, optionally pre-selected."""
    blocks = [
        DemoBlock(block_id=identifiers.new_id("block"), text=f"block-{index}")
        for index in range(block_count)
    ]
    selected_id = blocks[0].block_id if (selected and blocks) else None
    return DemoScene(blocks=blocks, selected_block_id=selected_id)


class DemoActions:
    """Deterministic authority over a :class:`DemoScene`.

    Implements the ``SceneActions[DemoScene]`` protocol. ``apply``
    only ever appends to ``generated`` and updates ``selected_block_id``; the
    block ``text`` is immutable, which lets ``verify`` fail closed on tampering.
    """

    def identity(self, scene: DemoScene) -> core_scene.SceneIdentity:
        # Revision 0: ``SceneState`` owns the authoritative advancing counter for
        # the live path. Plain runs advance via the engine's +1.
        return core_scene.SceneIdentity(scene_id=scene.scene_id, revision=0)

    def clone(self, scene: DemoScene) -> DemoScene:
        return copy.deepcopy(scene)

    def select_target(self, scene: DemoScene) -> core_target.Target | None:
        if scene.selected_block_id is None:
            return None
        return core_target.Target(target_id=scene.selected_block_id)

    def has_target(self, scene: DemoScene, target: core_target.Target) -> bool:
        return any(block.block_id == target.target_id for block in scene.blocks)

    def apply(
        self,
        scene: DemoScene,
        target: core_target.Target,
        operations: list[core_operation.Operation],
    ) -> DemoScene:
        updated = scene
        for operation in operations:
            updated = operation.apply(updated, target)
        return updated

    def verify(
        self,
        before: DemoScene,
        after: DemoScene,
        target: core_target.Target,
        operations: list[core_operation.Operation],
    ) -> core_scene.VerificationReport:
        issues: list[str] = []
        before_block = self._find(before, target.target_id)
        after_block = self._find(after, target.target_id)
        if after_block is None:
            issues.append("target block missing after apply")
            return core_scene.VerificationReport(issues=issues)
        if before_block is not None and after_block.text != before_block.text:
            issues.append("target block text changed")
        before_count = len(before_block.generated) if before_block is not None else 0
        if len(after_block.generated) != before_count + len(operations):
            issues.append("generated count mismatch")
        return core_scene.VerificationReport(issues=issues)

    @staticmethod
    def _find(scene: DemoScene, block_id: str) -> DemoBlock | None:
        for block in scene.blocks:
            if block.block_id == block_id:
                return block
        return None


def _request(
    target: core_target.Target,
    model_name: str,
    proposal_schema: model_calls.ProposalSchema,
) -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[
            model_calls.ModelMessage(role="system", content="demo"),
            model_calls.ModelMessage(role="user", content=f"target={target.target_id}"),
        ],
        model_settings=DemoModelSettings(),
        proposal_schema=proposal_schema,
    )


def _intent(identity: core_scene.SceneIdentity) -> DemoIntent:
    return DemoIntent(
        base_scene_id=identity.scene_id,
        base_revision=identity.revision,
    )


class DemoRecipe(core_recipe.SergentRecipe[DemoScene, DemoIntentProposal, DemoIntent]):
    """Intent proposal -> intent -> Plan proposal -> plan -> patch.

    Each stage threads only the data the next stage needs; the load-bearing
    validation is in the core ``Patch`` and the runtime's ``validate_patch``.
    """

    intent_proposal_type = DemoIntentProposal
    operation_registry = _DEMO_OPERATION_REGISTRY
    no_target_error = core_errors.RunError(
        kind="no_target",
        message="no target available",
        metadata={"target_selection": {"status": "missing"}},
    )

    def build_intent_request(
        self,
        _scene: DemoScene,
        _mindbuf: core_mindbuf.MindBuf,
        target: core_target.Target,
        model_name: str,
        proposal_schema: model_calls.ProposalSchema,
    ) -> model_calls.ModelRequest:
        return _request(target, model_name, proposal_schema)

    def derive_intent(
        self,
        _scene: DemoScene,
        identity: core_scene.SceneIdentity,
        _target: core_target.Target,
        _intent_proposal: DemoIntentProposal,
    ) -> DemoIntent:
        return _intent(identity)

    def build_plan_request(
        self,
        _scene: DemoScene,
        target: core_target.Target,
        _intent: DemoIntent,
        _mindbuf: core_mindbuf.MindBuf,
        model_name: str,
        proposal_schema: model_calls.ProposalSchema,
    ) -> model_calls.ModelRequest:
        return _request(target, model_name, proposal_schema)


class PassThroughDemoRecipe(
    core_recipe.SergentRecipe[
        DemoScene,
        intent_proposals.IntentProposal_PassThrough,
        DemoIntent,
    ]
):
    """Derives Intent without an Intent provider call."""

    intent_proposal_type = intent_proposals.IntentProposal_PassThrough
    operation_registry = _DEMO_OPERATION_REGISTRY
    no_target_error = core_errors.RunError(kind="no_target", message="no target available")

    def derive_intent(
        self,
        _scene: DemoScene,
        identity: core_scene.SceneIdentity,
        _target: core_target.Target,
        _intent_proposal: intent_proposals.IntentProposal_PassThrough,
    ) -> DemoIntent:
        return _intent(identity)

    def build_plan_request(
        self,
        _scene: DemoScene,
        target: core_target.Target,
        _intent: DemoIntent,
        _mindbuf: core_mindbuf.MindBuf,
        model_name: str,
        proposal_schema: model_calls.ProposalSchema,
    ) -> model_calls.ModelRequest:
        return _request(target, model_name, proposal_schema)


class TamperingActions(DemoActions):
    """Scene actions whose ``apply`` mutation makes ``verify`` reject the result.

    Used to drive the dry-run verification-failure path.
    """

    def apply(
        self,
        scene: DemoScene,
        target: core_target.Target,
        operations: list[core_operation.Operation],
    ) -> DemoScene:
        scene = super().apply(scene, target, operations)
        for block in scene.blocks:
            block.text = block.text + "!"
        return scene


def _response(output: dict[str, object], *, request_id: str) -> model_calls.ModelResponse:
    response = model_calls.ModelResponse(
        identity=core_model_calls.ModelIdentity(provider="fake", model="fake-model"),
        raw_output=json.dumps(output),
        usage=core_model_calls.CallUsage(
            latency_ms=7,
            tokens={"input": 3, "output": 5},
            request_id=request_id,
        ),
    )
    return response.model_copy(update={"parsed_json": output})


def _intent_response() -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
    payload: dict[str, typing.Any] = {}
    return (_response(payload, request_id="req-intent"), payload)


def _plan_response(
    labels: list[str],
) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
    operations = [DemoOperation(text=f"note:{label}") for label in labels]
    payload: dict[str, object] = {
        "operations": [operation.model_dump(mode="json") for operation in operations]
    }
    return (_response(payload, request_id="req-plan"), payload)


class StaticClient:
    """Returns canned proposal objects built from fixed labels."""

    def __init__(
        self,
        labels: list[str] | None = None,
        *,
        model_backed_intent: bool = True,
    ) -> None:
        self._labels = labels if labels is not None else ["alpha"]
        self._model_backed_intent = model_backed_intent
        self.requests: list[model_calls.ModelRequest] = []

    async def invoke(
        self, request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        self.requests.append(request)
        if self._model_backed_intent and len(self.requests) % 2 == 1:
            return _intent_response()
        return _plan_response(list(self._labels))


class ErrorClient:
    """Raises a supplied :class:`ModelError` instead of returning a proposal."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def invoke(
        self, _request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        raise self._error


class _CancellingClient(StaticClient):
    cancel_call_number: int

    def __init__(self) -> None:
        super().__init__(["alpha"])
        self.cancel: cabc.Callable[[], None] | None = None

    async def invoke(
        self, request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        response, payload = await super().invoke(request)
        if len(self.requests) == self.cancel_call_number and self.cancel is not None:
            response = response.model_copy(
                update={
                    "attempts": [
                        core_model_calls.ModelAttemptRecord(
                            timing=core_timing.TimeSpan(
                                started_at="2026-01-01T00:00:00.000000Z",
                                finished_at="2026-01-01T00:00:00.001000Z",
                                duration_ms=1,
                            ),
                            status="success",
                        )
                    ]
                }
            )
            self.cancel()
        return response, payload


class CancellingIntentClient(_CancellingClient):
    """Requests cancellation after returning the Intent proposal."""

    cancel_call_number = 1


class CancellingPlanClient(_CancellingClient):
    """Requests cancellation after returning the Plan proposal."""

    cancel_call_number = 2


class ControlledCallGate:
    """Own one deterministic model-call park and release gate."""

    def __init__(self) -> None:
        self._gate = asyncio.Event()
        self._arrived = asyncio.Event()

    async def park(self) -> None:
        self._arrived.set()
        await self._gate.wait()

    async def wait_called(self) -> None:
        await self._arrived.wait()

    def release(self) -> None:
        self._gate.set()


class ControlledClient:
    """Parks at the model call until released; records every request.

    ``release()`` lets a parked invocation proceed. ``wait_called()`` blocks until
    at least one invocation has reached the gate, which makes concurrency,
    interleave, and cancel tests deterministic.
    """

    def __init__(self, labels: list[str] | None = None) -> None:
        self._labels = labels if labels is not None else ["alpha"]
        self._control = ControlledCallGate()
        self.requests: list[model_calls.ModelRequest] = []

    def release(self) -> None:
        """Allow any parked (and future) invocation to proceed."""
        self._control.release()

    async def wait_called(self) -> None:
        """Wait until at least one invocation has reached the gate."""
        await self._control.wait_called()

    async def invoke(
        self, request: model_calls.ModelRequest
    ) -> tuple[model_calls.ModelResponse, dict[str, typing.Any]]:
        self.requests.append(request)
        await self._control.park()
        if len(self.requests) % 2 == 1:
            return _intent_response()
        return _plan_response(list(self._labels))


class CapturingObserver:
    """Collects every progress snapshot and the single terminal result."""

    def __init__(self) -> None:
        self.snapshots: list[observe.ProgressSnapshot] = []
        self.finished_results: list[core_result.SergentResult[DemoScene]] = []
        self.finished_error_counts: list[int] = []

    def progress(self, snapshot: observe.ProgressSnapshot) -> None:
        self.snapshots.append(snapshot)

    def finished(self, result: core_result.SergentResult[DemoScene]) -> None:
        self.finished_results.append(result)
        self.finished_error_counts.append(len(result.observer_errors))


# Static type assertions: these instances must satisfy the core protocols.
if typing.TYPE_CHECKING:
    _actions: core_scene_actions.SceneActions = DemoActions()
    _recipe: core_recipe.SergentRecipe = DemoRecipe()
    _client: model_calls.ModelClient = StaticClient()
