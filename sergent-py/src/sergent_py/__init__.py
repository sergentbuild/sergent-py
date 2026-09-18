"""Expose batteries-included wiring and curated application re-exports.
@sergent-py/docs/KNOWLEDGE.md"""

from __future__ import annotations

from sergent_py_core.errors import RunError as RunError
from sergent_py_core.identifiers import (
    checked_id as checked_id,
    new_id as new_id,
)
from sergent_py_core.mindbuf import MindBuf as MindBuf
from sergent_py_core.model_calls import (
    CallUsage as CallUsage,
    ImagePart as ImagePart,
    ModelAttemptRecord as ModelAttemptRecord,
    ModelClient as ModelClient,
    ModelError as ModelError,
    ModelIdentity as ModelIdentity,
    ModelMessage as ModelMessage,
    ModelRequest as ModelRequest,
    ModelResponse as ModelResponse,
    ProposalSchema as ProposalSchema,
)
from sergent_py_core.operation import (
    Operation as Operation,
    OperationTrace as OperationTrace,
)
from sergent_py_core.proposals.operation_registry import OperationRegistry as OperationRegistry
from sergent_py_core.patch import (
    MergeConflict as MergeConflict,
    Patch as Patch,
    PatchRebaseRequest as PatchRebaseRequest,
    RebasedPatch as RebasedPatch,
)
from sergent_py_core.plan import (
    ExecutionPlan as ExecutionPlan,
    PlanProposal as PlanProposal,
)
from sergent_py_core.recipe import SergentRecipe as SergentRecipe
from sergent_py_core.result import SergentResult as SergentResult
from sergent_py_core.run_record import (
    CapturedValue as CapturedValue,
    ModelCallRecord as ModelCallRecord,
    RunRecord as RunRecord,
    RunStatus as RunStatus,
    RunStepRecord as RunStepRecord,
    RunTerminalRecord as RunTerminalRecord,
)
from sergent_py_core.scene import (
    SceneIdentity as SceneIdentity,
    VerificationReport as VerificationReport,
)
from sergent_py_core.scene_actions import SceneActions as SceneActions
from sergent_py_core.strict_model import (
    StrictModel as StrictModel,
    strip_non_empty as strip_non_empty,
)
from sergent_py_core.target import Target as Target
from sergent_py_providers.settings import (
    ModelSettings as ModelSettings,
    ThinkingEffort as ThinkingEffort,
)
from sergent_py_providers.perplexity_agent import (
    PerplexityAgentClient as PerplexityAgentClient,
)
from sergent_py_providers.transports import CREDENTIAL_ENV_VARS as CREDENTIAL_ENV_VARS
from sergent_py_runtime.lifecycle.concurrency import (
    CancelToken as CancelToken,
    RunHandle as RunHandle,
)
from sergent_py_runtime.execution.engine import SergentRuntime as SergentRuntime
from sergent_py_runtime.execution.errors import MergeConflictError as MergeConflictError
from sergent_py_runtime.lifecycle.observe import (
    ProgressSnapshot as ProgressSnapshot,
    RunObserver as RunObserver,
)
from sergent_py_runtime.proposals.intent_proposals import (
    IntentProposal_PassThrough as IntentProposal_PassThrough,
)
from sergent_py_runtime.proposals.intents import Intent_Continue as Intent_Continue
from sergent_py_runtime.run_record.run import Run as _Run  # noqa: F401
from sergent_py_runtime.run_record.run_record_file import (
    JsonlRunRecordWriter as JsonlRunRecordWriter,
)
from sergent_py_runtime.execution.scene_state import (
    CommitResult as CommitResult,
    SceneState as SceneState,
)

from sergent_py.facade import (
    create_sergent as create_sergent,
    fan_out as fan_out,
    make_llm_client as make_llm_client,
)
from sergent_py.scene_helpers import (
    apply_operations_in_order as apply_operations_in_order,
    basic_identity_verifier as basic_identity_verifier,
    field_identity as field_identity,
    pydantic_clone as pydantic_clone,
    whole_scene_has_target as whole_scene_has_target,
    whole_scene_target as whole_scene_target,
)
