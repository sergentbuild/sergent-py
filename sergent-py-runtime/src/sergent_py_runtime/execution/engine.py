"""Execute one bounded run through the Sergent safety pipeline. @sergent/docs/execution-model.md
@sergent-py-runtime/docs/KNOWLEDGE.md"""

from __future__ import annotations

import asyncio
import dataclasses
import typing

import pydantic

import sergent_py_core.errors as core_errors
import sergent_py_core.intent as core_intent
import sergent_py_core.mindbuf as core_mindbuf
import sergent_py_core.proposals.operation_registry as core_operation_registry
import sergent_py_core.patch as core_patch
import sergent_py_core.plan as core_plan
import sergent_py_core.recipe as core_recipe
import sergent_py_core.result as core_result
import sergent_py_core.scene as core_scene
import sergent_py_core.scene_actions as core_scene_actions
import sergent_py_core.target as core_target
import sergent_py_core.identifiers as core_identifiers
import sergent_py_core.model_calls as core_model_calls
import sergent_py_runtime.execution.deterministic as runtime_deterministic
import sergent_py_runtime.execution.errors as runtime_errors
import sergent_py_runtime.execution.rebase as runtime_rebase
import sergent_py_runtime.execution.scene_state as runtime_scene_state
import sergent_py_runtime.run_record.run as runtime_run
import sergent_py_runtime.lifecycle.concurrency as runtime_concurrency
import sergent_py_runtime.lifecycle.observe as runtime_observe
import sergent_py_runtime.proposals._contract as runtime_proposal_contract

SceneT = typing.TypeVar("SceneT")


@dataclasses.dataclass(frozen=True)
class _CommitInput:
    """Carry trusted Intent and Patch evidence into commit. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    intent: object
    patch: core_patch.Patch
    patch_summary: dict[str, object]


@dataclasses.dataclass(frozen=True)
class _RunContext(typing.Generic[SceneT]):
    """Retain the stable Scene, identity, and exact selected Target. @sergent/docs/framework.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    base_scene: SceneT
    identity: core_scene.SceneIdentity
    target: core_target.Target


class SergentRuntime(typing.Generic[SceneT]):
    """Drive one run while retaining sole mutation authority. @sergent/docs/execution-model.md
    @sergent-py-runtime/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        client: core_model_calls.ModelClient,
        scene: core_scene_actions.SceneActions[SceneT],
        recipe: core_recipe.SergentRecipe[SceneT, typing.Any, typing.Any],
        *,
        observers: typing.Iterable[runtime_observe.RunObserver] = (),
    ) -> None:
        self._client = client
        self._scene = scene
        self._recipe = recipe
        self._proposals = runtime_proposal_contract._capture(recipe)
        self._observers = tuple(observers)

    def live_state(
        self,
        scene: SceneT,
        *,
        enforce_embedded_identity: bool = False,
    ) -> runtime_scene_state.SceneState[SceneT]:
        """Create revision-checked shared Scene authority. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return runtime_scene_state.SceneState(
            self._scene.identity,
            self._scene.clone,
            scene,
            enforce_embedded_identity=enforce_embedded_identity,
        )

    async def run(
        self,
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        *,
        model_name: str,
        cancel: runtime_concurrency.CancelToken | None = None,
    ) -> core_result.SergentResult[SceneT]:
        """Return a contained result from the bounded pipeline. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run = self._new_run(model_name)
        return await self._execute(run, source, mindbuf, cancel)

    def start(
        self,
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        *,
        model_name: str,
    ) -> runtime_concurrency.RunHandle[SceneT]:
        """Schedule the pipeline and return its run handle. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run = self._new_run(model_name)
        token = runtime_concurrency.CancelToken()
        task = asyncio.create_task(
            self._execute(run, source, mindbuf, token),
            name=f"sergent-run-{run.run_id}",
        )
        return runtime_concurrency.RunHandle(
            run_id=run.run_id,
            _run=run,
            _task=task,
            _cancel=token,
        )

    def _new_run(self, model_name: str) -> runtime_run.Run[SceneT]:
        """Create one progress and Run Record builder. @sergent-py-runtime/docs/KNOWLEDGE.md"""
        return runtime_run.Run(
            run_id=core_identifiers.new_id("run"),
            model_name=model_name,
        )

    async def _execute(
        self,
        run: runtime_run.Run[SceneT],
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        cancel: runtime_concurrency.CancelToken | None,
    ) -> core_result.SergentResult[SceneT]:
        """Contain ordinary failures and isolate observers. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        observer_errors: list[core_errors.RunError] = []
        self._deliver("progress", run.snapshot(), run.stage, observer_errors)
        try:
            result = await self._drive(run, source, mindbuf, cancel, observer_errors)
        except asyncio.CancelledError:
            base_scene = run.base_scene
            identity = run.identity
            if cancel is None or not cancel.cancelled() or base_scene is None or identity is None:
                raise
            result = run.cancelled(base_scene, checkpoint="task_cancelled", cancel=cancel)
        except Exception as exc:  # containment: ordinary exceptions -> structured failure
            result = run.failure(exc)
        self._deliver("progress", run.snapshot(), run.stage, observer_errors)
        result.observer_errors.extend(observer_errors)
        self._deliver("finished", result, result.stage, result.observer_errors)
        return result

    async def _drive(
        self,
        run: runtime_run.Run[SceneT],
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        cancel: runtime_concurrency.CancelToken | None,
        observer_errors: list[core_errors.RunError],
    ) -> core_result.SergentResult[SceneT]:
        """Sequence proposal and deterministic stages. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        base_scene, identity, target = self._process_input(run, source, mindbuf, observer_errors)
        if target is None:
            return run.no_target(base_scene, self._recipe.no_target_error)
        context = _RunContext(base_scene=base_scene, identity=identity, target=target)
        if cancel is not None and cancel.cancelled():
            return run.cancelled(base_scene, checkpoint="before_intent", cancel=cancel)
        run.open_step("intent", None)
        intent_proposal_type = self._proposals.intent_proposal_type
        intent_schema = self._proposals.intent_schema
        if intent_schema is None:
            intent_proposal = intent_proposal_type()
        else:
            intent_request = self._intent_request(run, context, mindbuf, intent_schema)
            self._advance(run, runtime_observe.Stage.INTENT_CALL, observer_errors)
            intent_response, intent_payload = await self._client.invoke(intent_request)
            try:
                intent_proposal = intent_proposal_type.model_validate(intent_payload)
            except pydantic.ValidationError as exc:
                run.finish_model_call(intent_response, None)
                name = intent_proposal_type.__name__
                raise runtime_errors._ProposalSchemaError(
                    f"invalid {name} proposal: {exc}"
                ) from exc
            run.finish_model_call(intent_response, intent_proposal)
        self._advance(run, runtime_observe.Stage.INTENT, observer_errors)
        intent, flow = self._validated_intent(run, context, intent_proposal)
        if cancel is not None and cancel.cancelled():
            return run.cancelled(base_scene, checkpoint="after_intent_validation", cancel=cancel)
        if flow == "stop":
            return self._intent_stop(run, context, intent)
        run.finish_step("success")
        run.open_step("execution_plan", None)
        plan_request, operation_registry = self._plan_request(run, context, intent, mindbuf)
        self._advance(run, runtime_observe.Stage.PLAN_CALL, observer_errors)
        plan_response, plan_payload = await self._client.invoke(plan_request)
        try:
            plan_proposal = operation_registry.decode_plan_proposal(
                plan_payload,
                max_operations=self._proposals.max_operations,
            )
        except ValueError as exc:
            run.finish_model_call(plan_response, None)
            raise runtime_errors._ProposalSchemaError(str(exc)) from exc
        run.finish_model_call(plan_response, plan_proposal)
        self._advance(run, runtime_observe.Stage.EXECUTION_PLAN, observer_errors)
        plan = self._validated_plan(run, context, intent, plan_proposal)
        self._advance(run, runtime_observe.Stage.PATCH, observer_errors)
        patch, patch_summary = self._compiled_patch(run, context, plan)
        if cancel is not None and cancel.cancelled():
            return run.cancelled(base_scene, checkpoint="before_dry_run", cancel=cancel)
        self._advance(run, runtime_observe.Stage.DRY_RUN, observer_errors)
        self._dry_run_step(run, context, patch)
        if cancel is not None and cancel.cancelled():
            return run.cancelled(base_scene, checkpoint="before_commit", cancel=cancel)
        self._advance(run, runtime_observe.Stage.COMMIT, observer_errors)
        commit_input = _CommitInput(intent, patch, patch_summary)
        return self._commit_step(run, source, context, commit_input)

    def _intent_request(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        proposal_schema: core_model_calls.ProposalSchema,
    ) -> core_model_calls.ModelRequest:
        """Record a model-backed Intent proposal request. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        request = self._recipe.build_intent_request(
            context.base_scene, mindbuf, context.target, run.model_name, proposal_schema
        )
        if request.proposal_schema is not proposal_schema:
            raise AssertionError("build_intent_request must return the provided schema object")
        run.start_model_call(request)
        return request

    def _plan_request(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        intent: typing.Any,
        mindbuf: core_mindbuf.MindBuf,
    ) -> tuple[core_model_calls.ModelRequest, core_operation_registry.OperationRegistry]:
        """Record a continuing Plan proposal request. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        operation_registry = self._proposals.operation_registry
        proposal_schema = self._proposals.plan_schema
        if operation_registry is None or proposal_schema is None:
            raise AssertionError("continue-flow recipe requires operation_registry")
        request = self._recipe.build_plan_request(
            context.base_scene, context.target, intent, mindbuf, run.model_name, proposal_schema
        )
        if request.proposal_schema is not proposal_schema:
            raise AssertionError("build_plan_request must return the provided schema object")
        run.start_model_call(request)
        return request, operation_registry

    def _process_input(
        self,
        run: runtime_run.Run[SceneT],
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        mindbuf: core_mindbuf.MindBuf,
        observer_errors: list[core_errors.RunError],
    ) -> tuple[SceneT, core_scene.SceneIdentity, core_target.Target | None]:
        """Process observation and select one bounded Target. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run.open_step("process_input", {"observation": mindbuf.export()})
        if isinstance(source, runtime_scene_state.SceneState):
            base_scene, identity = source.snapshot()
        else:
            base_scene, identity = self._scene.clone(source), self._scene.identity(source)
        run.begin(base_scene, identity)
        self._advance(run, runtime_observe.Stage.STARTED, observer_errors)
        target = self._scene.select_target(base_scene)
        run.update_step_output(selected_target=target)
        if target is not None:
            run.finish_step("success")
        return base_scene, identity, target

    def _validated_intent(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        intent_proposal: typing.Any,
    ) -> tuple[typing.Any, str]:
        """Derive and validate Intent before reading its flow. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        intent = self._recipe.derive_intent(
            context.base_scene, context.identity, context.target, intent_proposal
        )
        run.update_step_output(derived_intent=intent)
        self._recipe.validate_intent(context.base_scene, context.identity, intent)
        flow = core_intent.intent_flow(intent)
        run.update_step_output(flow=flow)
        return intent, flow

    def _intent_stop(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        intent: typing.Any,
    ) -> core_result.SergentResult[SceneT]:
        """Return unchanged success for a stop Intent. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        terminal_message = core_intent.intent_terminal_message(intent)
        terminal_metadata = core_intent.intent_terminal_metadata(intent)
        run.finish_step("success")
        return run.success_without_patch(
            context.base_scene,
            context.identity,
            terminal_message=terminal_message,
            terminal_metadata=terminal_metadata,
        )

    def _validated_plan(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        intent: typing.Any,
        plan_proposal: core_plan.PlanProposal,
    ) -> core_plan.ExecutionPlan:
        """Derive and validate ExecutionPlan and Operations once. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        plan = self._recipe.derive_plan(
            context.base_scene,
            context.identity,
            context.target,
            intent,
            plan_proposal,
        )
        run.update_step_output(derived_execution_plan=plan)
        runtime_deterministic._validate_operations(
            self._scene,
            context.base_scene,
            intent,
            context.target,
            plan.steps,
        )
        self._recipe.validate_plan(
            context.base_scene, context.identity, context.target, intent, plan
        )
        run.finish_step("success")
        return plan

    def _compiled_patch(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        plan: core_plan.ExecutionPlan,
    ) -> tuple[core_patch.Patch, dict[str, object]]:
        """Compile and validate Patch evidence before rehearsal. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run.open_step("patch", None)
        patch = self._recipe.compile_patch(plan)
        patch_summary = run.patch_summary(patch)
        run.update_step_output(compiled_patch=patch_summary)
        try:
            runtime_deterministic.validate_patch(
                self._scene, context.base_scene, context.identity, context.target, patch
            )
        except runtime_errors.PatchValidationError:
            run.update_step_output(patch_validation={"status": "failure"})
            raise
        return patch, patch_summary

    def _dry_run_step(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        patch: core_patch.Patch,
    ) -> None:
        """Rehearse the Patch without mutation. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        after_dry_run = runtime_deterministic.dry_run(
            self._scene, context.base_scene, context.identity, context.target, patch
        )
        run.update_step_output(
            dry_run={
                "after_identity": self._scene.identity(after_dry_run),
            }
        )
        run.finish_step("success")

    def _commit_step(
        self,
        run: runtime_run.Run[SceneT],
        source: SceneT | runtime_scene_state.SceneState[SceneT],
        context: _RunContext[SceneT],
        commit_input: _CommitInput,
    ) -> core_result.SergentResult[SceneT]:
        """Use the selected plain or shared Scene authority. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run.open_step("commit", None)
        if isinstance(source, runtime_scene_state.SceneState):
            return self._commit_live_step(run, source, context, commit_input)
        return self._commit_plain_step(run, context, commit_input.patch)

    def _commit_live_step(
        self,
        run: runtime_run.Run[SceneT],
        source: runtime_scene_state.SceneState[SceneT],
        context: _RunContext[SceneT],
        commit_input: _CommitInput,
    ) -> core_result.SergentResult[SceneT]:
        """Commit with live authority and optional Scene-owned rebase. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        identity = context.identity
        try:
            result = runtime_rebase._commit_live(
                source,
                self._scene,
                runtime_rebase._PatchRebaseBase(
                    base_scene=context.base_scene,
                    base_identity=identity,
                    target=context.target,
                    patch=commit_input.patch,
                ),
                commit_input.patch_summary,
                commit_input.intent,
            )
        except runtime_errors.PatchValidationError as exc:
            run.finish_step("failure", error=run.error_record(exc))
            raise
        run.update_step_output(
            commit_kind=result.kind,
            metadata=result.metadata,
        )
        run.finish_step("success")
        return run.success(
            result.scene,
            result.identity,
            terminal_metadata=result.metadata,
        )

    def _commit_plain_step(
        self,
        run: runtime_run.Run[SceneT],
        context: _RunContext[SceneT],
        patch: core_patch.Patch,
    ) -> core_result.SergentResult[SceneT]:
        """Commit against the isolated plain Scene snapshot. @sergent/docs/framework.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        identity = context.identity
        committed = runtime_deterministic.commit(
            context.base_scene, context.target, patch, self._scene
        )
        identity_after = core_scene.SceneIdentity(
            scene_id=identity.scene_id,
            revision=identity.revision + 1,
        )
        run.update_step_output(
            commit_kind="plain",
            metadata={},
        )
        run.finish_step("success")
        return run.success(committed, identity_after)

    def _advance(
        self,
        run: runtime_run.Run[SceneT],
        stage: runtime_observe.Stage,
        observer_errors: list[core_errors.RunError],
    ) -> None:
        """Advance and deliver sanitized progress. @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        run.advance(stage)
        self._deliver("progress", run.snapshot(), run.stage, observer_errors)

    def _deliver(
        self,
        callback: typing.Literal["progress", "finished"],
        value: object,
        stage: str,
        observer_errors: list[core_errors.RunError],
    ) -> None:
        """Deliver every observer slot and contain ordinary failures.
        @sergent/docs/execution-model.md
        @sergent-py-runtime/docs/KNOWLEDGE.md"""
        for observer in self._observers:
            try:
                getattr(observer, callback)(value)
            except (asyncio.CancelledError, Exception) as exc:
                error = runtime_observe._observer_error(callback, observer, exc, stage)
                observer_errors.append(error)
