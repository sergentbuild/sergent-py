"""Define the typed model-call boundary and the facts it produces. @sergent/docs/execution-model.md
@sergent/docs/trust-boundaries.md
@sergent-py-core/docs/core-class-design-pattern.md"""

from __future__ import annotations

import base64
import binascii
import json
import typing

import pydantic

import sergent_py_core.errors as errors
import sergent_py_core.strict_model as strict_model
import sergent_py_core.timing as timing

_IMAGE_PART_MAX_BYTES = 1_000_000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ProposalSchema(strict_model.StrictModel):
    """Carry one canonical proposal structure and stable provider name. @sergent/docs/framework.md
    @sergent-py-core/docs/KNOWLEDGE.md"""

    name: str = pydantic.Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    json_schema: dict[str, typing.Any]

    @pydantic.field_validator("json_schema")
    @classmethod
    def _schema_is_json_data(cls, value: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Reject values that do not round-trip as exact JSON data."""
        try:
            encoded = json.dumps(value, allow_nan=False)
            decoded = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise ValueError("json_schema must contain only JSON-compatible data") from exc
        if decoded != value:
            raise ValueError("json_schema must contain only JSON-compatible data")
        return value


class ModelIdentity(strict_model.StrictModel):
    """Identify the exact resolved endpoint and SDK that served a model call. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/KNOWLEDGE.md"""

    provider: str
    model: str
    sdk_package: str | None = None
    sdk_version: str | None = None

    @pydantic.field_validator("provider", "model")
    @classmethod
    def _endpoint_non_empty(cls, value: str) -> str:
        """Reject blank endpoint identity text without changing its evidence."""
        if not value.strip():
            msg = "endpoint identity text must be non-empty"
            raise ValueError(msg)
        return value


class CallUsage(strict_model.StrictModel):
    """Carry provider-measured outcome facts for one model call. @sergent/docs/run-record-spec.md
    @sergent-py-core/docs/KNOWLEDGE.md"""

    latency_ms: int = pydantic.Field(ge=0)
    tokens: dict[str, typing.Annotated[int, pydantic.Field(ge=0)]] | None = None
    request_id: str | None = None

    def output_tokens(self) -> int | None:
        """Return measured output tokens when the provider supplied them. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        return None if self.tokens is None else self.tokens.get("output")


class ModelAttemptRecord(strict_model.StrictModel):
    """Carry the closed evidence for one completed model-call attempt. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    timing: timing.TimeSpan
    status: typing.Literal["success", "failure"]
    retryable: bool | None = None
    error: errors.RunError | None = None

    @pydantic.model_validator(mode="after")
    def _timing_is_closed(self) -> ModelAttemptRecord:
        """Require completed attempts to carry a closed time span."""
        if not self.timing.is_closed():
            msg = "attempt timing must be a closed span"
            raise ValueError(msg)
        return self


class ImagePart(strict_model.StrictModel):
    """Carry one bounded PNG image input as validated base64 text. @sergent/docs/execution-model.md
    @sergent/docs/trust-boundaries.md"""

    media_type: typing.Literal["image/png"] = "image/png"
    data_base64: str

    @staticmethod
    def _decode_png_base64(value: str) -> bytes:
        """Decode bounded PNG bytes or reject malformed image input."""
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            msg = "data_base64 must be valid base64"
            raise ValueError(msg) from exc
        if len(decoded) > _IMAGE_PART_MAX_BYTES:
            msg = f"decoded image bytes must be <= {_IMAGE_PART_MAX_BYTES}"
            raise ValueError(msg)
        if not decoded.startswith(_PNG_SIGNATURE):
            msg = "data_base64 must contain PNG bytes"
            raise ValueError(msg)
        return decoded

    @pydantic.field_validator("data_base64")
    @classmethod
    def _data_is_png_base64(cls, value: str) -> str:
        """Normalize and validate one PNG base64 value."""
        stripped = strict_model.strip_non_empty(value)
        cls._decode_png_base64(stripped)
        return stripped

    def decoded_bytes(self) -> bytes:
        """Return the already-validated PNG bytes."""
        return self._decode_png_base64(self.data_base64)

    def decoded_byte_count(self) -> int:
        """Return the decoded PNG byte count."""
        return len(self.decoded_bytes())


class ModelMessage(strict_model.StrictModel):
    """Carry one bounded system or user prompt message. @sergent/docs/execution-model.md
    @sergent/docs/trust-boundaries.md"""

    role: typing.Literal["system", "user"]
    content: str
    images: list[ImagePart] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("content")
    @classmethod
    def _content_non_empty(cls, value: str) -> str:
        """Reject empty prompt text."""
        return strict_model.strip_non_empty(value)

    @pydantic.model_validator(mode="after")
    def _images_are_user_input(self) -> ModelMessage:
        """Allow image inputs only on user messages."""
        if self.images and self.role != "user":
            msg = "images are allowed only on user messages"
            raise ValueError(msg)
        return self


class ModelRequest(strict_model.StrictModel):
    """Carry one typed proposal request across the model-call boundary. @sergent/docs/execution-model.md
    @sergent/docs/trust-boundaries.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    model_name: str
    messages: list[ModelMessage] = pydantic.Field(min_length=1)
    model_settings: strict_model.StrictModel
    proposal_schema: ProposalSchema


class ModelResponse(strict_model.StrictModel):
    """Carry successful model-call output and completed attempt facts. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    identity: ModelIdentity
    raw_output: str | None = None
    parsed_json: dict[str, typing.Any] | None = None
    attempts: list[ModelAttemptRecord] = pydantic.Field(default_factory=list)
    usage: CallUsage


class ModelError(Exception):
    """Carry a typed model-call failure and any partial response. @sergent/docs/execution-model.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    _identity: ModelIdentity | None
    _attempts: list[ModelAttemptRecord]

    def __init__(  # noqa: PLR0913 - failure facts cross the model API here.
        self,
        kind: str,
        message: str = "",
        *,
        retryable: bool = False,
        response: ModelResponse | None = None,
        identity: ModelIdentity | None = None,
        attempts: list[ModelAttemptRecord] | None = None,
    ) -> None:
        """Create a typed failure while preserving one source for response facts."""
        super().__init__(message or kind)
        self.kind = kind
        self.message = message or kind
        self.retryable = retryable
        self.response = response
        if response is None:
            self._identity = identity
            self._attempts = list(attempts or [])

    @property
    def identity(self) -> ModelIdentity | None:
        """Read endpoint identity from the partial response or fallback facts. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        response = self.response
        return self._identity if response is None else response.identity

    @property
    def attempts(self) -> list[ModelAttemptRecord]:
        """Read attempts from the partial response or fallback facts. @sergent/docs/execution-model.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        response = self.response
        return self._attempts if response is None else response.attempts


class ModelClient(typing.Protocol):
    """Provide asynchronous model transport and strict one-object response parsing. @sergent/docs/execution-model.md
    @sergent/docs/trust-boundaries.md
    @sergent-py-core/docs/core-class-design-pattern.md"""

    async def invoke(self, request: ModelRequest, /) -> tuple[ModelResponse, dict[str, typing.Any]]:
        """Return model-call evidence beside one parsed JSON object. @sergent/docs/execution-model.md
        @sergent/docs/trust-boundaries.md
        @sergent-py-core/docs/core-class-design-pattern.md"""
        ...
