"""Define provider-owned controls for individual model calls.
@sergent/docs/execution-model.md
@sergent-py-providers/docs/KNOWLEDGE.md"""

import typing

import pydantic
import sergent_py_core.strict_model as core_strict_model

ThinkingEffort = typing.Literal["low", "medium", "high"]
_DEFAULT_MAX_OUTPUT_TOKENS = 4096
_DEFAULT_TIMEOUT_SECONDS = 60


class ModelSettings(core_strict_model.StrictModel):
    """Configure low, medium, or high effort with optional positive output-token and timeout limits.
    @sergent/docs/execution-model.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""

    thinking_effort: ThinkingEffort = "high"
    max_output_tokens: int | None = pydantic.Field(default=_DEFAULT_MAX_OUTPUT_TOKENS, ge=1)
    timeout_seconds: int | None = pydantic.Field(default=_DEFAULT_TIMEOUT_SECONDS, ge=1)
