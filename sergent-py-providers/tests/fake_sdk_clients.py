from __future__ import annotations

import types
import typing

import sergent_py_core.model_calls as model_calls


def proposal_schema() -> model_calls.ProposalSchema:
    """Build the shared canonical schema used by provider adaptation tests."""
    return model_calls.ProposalSchema(
        name="TestProposal",
        json_schema={
            "$defs": {
                "Choice": {
                    "type": "object",
                    "properties": {"value": {"type": "integer", "minimum": 1, "maximum": 3}},
                    "required": ["value"],
                    "additionalProperties": False,
                }
            },
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Choice"},
                    "minItems": 1,
                    "maxItems": 2,
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    )


def openai_response(
    text: str = '{"ok": true}',
    *,
    status: str = "completed",
    incomplete_reason: str | None = None,
    output: list[object] | None = None,
) -> types.SimpleNamespace:
    """Build one exact-shaped OpenAI Responses result for adapter tests."""
    return types.SimpleNamespace(
        output_text=text,
        output=[] if output is None else output,
        status=status,
        incomplete_details=(
            None if incomplete_reason is None else types.SimpleNamespace(reason=incomplete_reason)
        ),
        id="resp-openai",
        usage=types.SimpleNamespace(input_tokens=8, output_tokens=9),
    )


def anthropic_response(
    text: str = '{"ok": true}',
    *,
    stop_reason: str = "end_turn",
) -> types.SimpleNamespace:
    """Build one exact-shaped Anthropic Messages result for adapter tests."""
    return types.SimpleNamespace(
        id="msg-1",
        content=[types.SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=types.SimpleNamespace(input_tokens=2, output_tokens=3),
    )


def gemini_response() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        text='{"ok": true}',
        response_id="gemini-1",
        usage_metadata=types.SimpleNamespace(prompt_token_count=4, candidates_token_count=5),
    )


class AsyncRecorder:
    def __init__(self, outcomes: list[typing.Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, typing.Any]] = []

    async def create(self, **kwargs: typing.Any) -> typing.Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def generate_content(self, **kwargs: typing.Any) -> typing.Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeOpenAIClient:
    def __init__(self, *outcomes: typing.Any) -> None:
        self._recorder = AsyncRecorder(list(outcomes))
        self.responses = types.SimpleNamespace(create=self._recorder.create)

    @property
    def calls(self) -> list[dict[str, typing.Any]]:
        return self._recorder.calls


class FakeAnthropicClient:
    def __init__(self, *outcomes: typing.Any) -> None:
        self._recorder = AsyncRecorder(list(outcomes))
        self.messages = types.SimpleNamespace(create=self._recorder.create)

    @property
    def calls(self) -> list[dict[str, typing.Any]]:
        return self._recorder.calls


class FakeGeminiClient:
    def __init__(self, *outcomes: typing.Any) -> None:
        self._recorder = AsyncRecorder(list(outcomes))
        self.aio = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=self._recorder.generate_content)
        )

    @property
    def calls(self) -> list[dict[str, typing.Any]]:
        return self._recorder.calls


class FakeOllamaClient:
    def __init__(self, *outcomes: typing.Any) -> None:
        self._recorder = AsyncRecorder(list(outcomes))
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._recorder.create)
        )

    @property
    def calls(self) -> list[dict[str, typing.Any]]:
        return self._recorder.calls


class FakeCommandRunner:
    def __init__(self, *outcomes: tuple[int, str] | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[list[str]] = []

    async def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def command_result(
    returncode: int = 0,
    *,
    stderr: str = "",
) -> tuple[int, str]:
    return returncode, stderr
