from __future__ import annotations

import asyncio
import types

import fake_sdk_clients
import httpx2
import openai
import pytest
import sergent_py_core.model_calls as model_calls
import sergent_py_providers.client as provider_client
import sergent_py_providers.settings as provider_settings


def _request(model_name: str = "openai/gpt-5.6-sol") -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[model_calls.ModelMessage(role="user", content="Return JSON.")],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )


def _openai_response(text: str = '{"ok": true}'):
    return types.SimpleNamespace(
        output_text=text,
        output=[],
        status="completed",
        incomplete_details=None,
        id="resp-1",
        usage=None,
    )


def _ollama_response(text: str = '{"ok": true}') -> types.SimpleNamespace:
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))],
        usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=2),
    )


def _sdk_request(url: str = "https://api.openai.com/v1/responses") -> httpx2.Request:
    return httpx2.Request("POST", url)


def _connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=_sdk_request())


def _status_error(status: int, *, url: str = "https://api.openai.com/v1/responses"):
    response = httpx2.Response(status, request=_sdk_request(url))
    return openai.APIStatusError(f"Error code: {status}", response=response, body=None)


# --- full model selection ---------------------------------------------------
def test_selection_splits_once_and_preserves_provider_native_name() -> None:
    selection = provider_client._select_model("openai/org/model:revision   ")
    assert selection.provider == "openai"
    assert selection.model == "org/model:revision   "

    whitespace_selection = provider_client._select_model("openai/model\t  ")
    assert whitespace_selection.model == "model\t  "


@pytest.mark.parametrize("model_name", ["gpt-5.6-sol", "/gpt-5.6-sol"])
def test_selection_rejects_a_missing_provider_prefix(model_name: str) -> None:
    with pytest.raises(model_calls.ModelError) as info:
        provider_client._select_model(model_name)
    assert info.value.kind == "invalid_model_name"


def test_invoke_unknown_provider_fails_before_sdk_access() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(provider_client.LlmClient().invoke(_request("unknown/model")))
    assert info.value.kind == "unknown_provider"


def test_model_settings_validates_effort_token_cap_and_timeout() -> None:
    assert (
        provider_settings.ModelSettings().max_output_tokens
        == provider_settings._DEFAULT_MAX_OUTPUT_TOKENS
    )
    assert (
        provider_settings.ModelSettings().timeout_seconds
        == provider_settings._DEFAULT_TIMEOUT_SECONDS
    )
    settings = provider_settings.ModelSettings(
        thinking_effort="medium",
        max_output_tokens=1,
        timeout_seconds=2,
    )
    assert settings.thinking_effort == "medium"
    assert settings.max_output_tokens == 1
    assert settings.timeout_seconds == 2
    with pytest.raises(ValueError):
        provider_settings.ModelSettings(
            thinking_effort="none"  # pyright: ignore[reportArgumentType] - deliberate invalid effort
        )
    with pytest.raises(ValueError):
        provider_settings.ModelSettings(max_output_tokens=0)
    with pytest.raises(ValueError):
        provider_settings.ModelSettings(timeout_seconds=0)


# --- JSON extraction --------------------------------------------------------
def test_extract_plain_object() -> None:
    assert provider_client._extract_json_object('{"ok": true}') == {"ok": True}


def test_extract_invalid_json_raises() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        provider_client._extract_json_object("not json at all")
    assert info.value.kind == "invalid_response"


def test_extract_non_object_raises() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        provider_client._extract_json_object("[1, 2, 3]")
    assert info.value.kind == "invalid_response"


def test_extract_broken_brace_string_no_salvage() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        provider_client._extract_json_object('prefix {"ok": true} trailing junk')
    assert info.value.kind == "invalid_response"


# --- missing credentials (no retry) -----------------------------------------
def test_missing_credentials_no_retry() -> None:
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(provider_client.LlmClient().invoke(_request()))
    assert info.value.kind == "missing_credentials"


# --- Ollama preflight -------------------------------------------------------
def test_default_command_runner_uses_an_argument_vector_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Process:
        returncode = 0

        async def communicate(self) -> tuple[None, bytes]:
            return None, b"captured stderr"

        async def wait(self) -> int:
            return self.returncode

        def kill(self) -> None:
            raise AssertionError("completed process must not be killed")

    async def create_subprocess_exec(*argv: str, **kwargs: object) -> Process:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        create_subprocess_exec,
    )

    result = asyncio.run(provider_client._default_command_runner(["ollama", "show", "exact:model"]))

    assert captured == {
        "argv": ("ollama", "show", "exact:model"),
        "kwargs": {
            "stdout": asyncio.subprocess.DEVNULL,
            "stderr": asyncio.subprocess.PIPE,
        },
    }
    assert result == (0, "captured stderr")


def test_default_command_runner_kills_and_reaps_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        communicating = asyncio.Event()

        class Process:
            returncode: int | None = None
            killed = False
            waited = False

            async def communicate(self) -> tuple[None, bytes]:
                communicating.set()
                await asyncio.Event().wait()
                return None, b""

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

            async def wait(self) -> int:
                self.waited = True
                assert self.returncode is not None
                return self.returncode

        process = Process()

        async def create_subprocess_exec(*_argv: str, **_kwargs: object) -> Process:
            return process

        monkeypatch.setattr(
            asyncio,
            "create_subprocess_exec",
            create_subprocess_exec,
        )
        task = asyncio.create_task(
            provider_client._default_command_runner(["ollama", "show", "model"])
        )
        await communicating.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.killed is True
        assert process.waited is True

    asyncio.run(scenario())


def test_ollama_preflight_yields_while_the_async_runner_is_awaiting() -> None:
    async def scenario() -> None:
        called = asyncio.Event()
        release = asyncio.Event()
        peer_progressed = asyncio.Event()

        async def runner(argv: list[str]) -> tuple[int, str]:
            assert argv == ["ollama", "show", "local-model"]
            called.set()
            await release.wait()
            return fake_sdk_clients.command_result()

        sdk_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())
        invocation = asyncio.create_task(
            provider_client.LlmClient(
                sdk_clients={"ollama": sdk_client},
                command_runner=runner,
            ).invoke(_request("ollama/local-model"))
        )
        await called.wait()

        async def peer() -> None:
            peer_progressed.set()

        peer_task = asyncio.create_task(peer())
        await peer_progressed.wait()
        assert not invocation.done()
        release.set()
        await invocation
        await peer_task

    asyncio.run(scenario())


def test_ollama_preflight_uses_exact_name_once_before_retries() -> None:
    runner = fake_sdk_clients.FakeCommandRunner(fake_sdk_clients.command_result())
    sdk_client = fake_sdk_clients.FakeOllamaClient(
        _connection_error(),
        _ollama_response(),
    )

    response, _ = asyncio.run(
        provider_client.LlmClient(
            sdk_clients={"ollama": sdk_client},
            command_runner=runner,
        ).invoke(_request("ollama/org/model:tag   "))
    )

    assert runner.calls == [["ollama", "show", "org/model:tag   "]]
    assert len(sdk_client.calls) == 2
    assert sdk_client.calls[0]["model"] == "org/model:tag   "
    assert response.identity.provider == "ollama"
    assert response.identity.model == "org/model:tag   "
    assert [attempt.status for attempt in response.attempts] == ["failure", "success"]


def test_ollama_preflight_status_one_is_model_not_found() -> None:
    runner = fake_sdk_clients.FakeCommandRunner(
        fake_sdk_clients.command_result(1, stderr="ignored status-one prose")
    )
    sdk_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(
                sdk_clients={"ollama": sdk_client},
                command_runner=runner,
            ).invoke(_request("ollama/missing:latest"))
        )

    assert info.value.kind == "model_not_found"
    assert "missing:latest" in info.value.message
    assert info.value.identity is not None
    assert info.value.identity.model == "missing:latest"
    assert info.value.attempts == []
    assert runner.calls == [["ollama", "show", "missing:latest"]]
    assert sdk_client.calls == []


def test_ollama_preflight_other_nonzero_is_provider_unavailable() -> None:
    runner = fake_sdk_clients.FakeCommandRunner(
        fake_sdk_clients.command_result(
            2,
            stderr="cannot reach http://localhost:11434/api?token=secret",
        )
    )

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(command_runner=runner).invoke(_request("ollama/local-model"))
        )

    assert info.value.kind == "provider_unavailable"
    assert info.value.message == "cannot reach http://localhost:11434/api"
    assert "secret" not in info.value.message
    assert info.value.attempts == []
    assert runner.calls == [["ollama", "show", "local-model"]]


def test_ollama_preflight_command_not_found_is_provider_unavailable() -> None:
    runner = fake_sdk_clients.FakeCommandRunner(FileNotFoundError("ollama command missing"))

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(command_runner=runner).invoke(_request("ollama/local-model"))
        )

    assert info.value.kind == "provider_unavailable"
    assert info.value.message == "ollama command missing"
    assert info.value.attempts == []
    assert runner.calls == [["ollama", "show", "local-model"]]


def test_ollama_preflight_cancellation_propagates_without_sdk_access() -> None:
    runner = fake_sdk_clients.FakeCommandRunner(asyncio.CancelledError())
    sdk_client = fake_sdk_clients.FakeOllamaClient(_ollama_response())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            provider_client.LlmClient(
                sdk_clients={"ollama": sdk_client},
                command_runner=runner,
            ).invoke(_request("ollama/local-model"))
        )

    assert runner.calls == [["ollama", "show", "local-model"]]
    assert sdk_client.calls == []


@pytest.mark.parametrize(
    ("status", "kind"),
    [(400, "invalid_payload"), (422, "invalid_payload"), (404, "model_not_found")],
)
def test_ollama_stable_http_errors_are_mapped(status: int, kind: str) -> None:
    runner = fake_sdk_clients.FakeCommandRunner(fake_sdk_clients.command_result())
    sdk_client = fake_sdk_clients.FakeOllamaClient(_status_error(status))

    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(
                sdk_clients={"ollama": sdk_client},
                command_runner=runner,
            ).invoke(_request("ollama/local-model"))
        )

    assert info.value.kind == kind
    assert len(sdk_client.calls) == 1
    assert runner.calls == [["ollama", "show", "local-model"]]


# --- retry: one transient then success --------------------------------------
def test_one_transient_then_success() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(_connection_error(), _openai_response())
    request = _request()
    response, payload = asyncio.run(
        provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(request)
    )
    assert len(sdk_client.calls) == 2
    assert payload == {"ok": True}
    assert payload is response.parsed_json
    assert response.raw_output == '{"ok": true}'
    assert response.parsed_json == {"ok": True}
    assert response.identity.sdk_package == "openai"
    assert isinstance(response.identity.sdk_version, str)
    attempts = response.attempts
    assert [attempt.status for attempt in attempts] == ["failure", "success"]
    first_error = attempts[0].error
    assert first_error is not None
    assert first_error.kind == "provider_unavailable"
    assert attempts[0].retryable is True
    assert response.usage.request_id == "resp-1"
    first_schema = sdk_client.calls[0]["text"]["format"]["schema"]
    second_schema = sdk_client.calls[1]["text"]["format"]["schema"]
    assert first_schema is request.proposal_schema.json_schema
    assert second_schema is first_schema


def test_two_transients_then_raise() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(_connection_error(), _connection_error())
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )
    assert info.value.kind == "provider_unavailable"
    assert len(sdk_client.calls) == 2
    assert info.value.response is None
    identity = info.value.identity
    assert identity is not None
    assert identity.provider == "openai"
    assert identity.model == "gpt-5.6-sol"
    assert identity.sdk_package == "openai"
    assert isinstance(identity.sdk_version, str)
    attempts = info.value.attempts
    assert len(attempts) == 2
    assert [attempt.status for attempt in attempts] == ["failure", "failure"]


def test_timeout_retried_and_mapped_to_timeout_kind() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(
        openai.APITimeoutError(request=_sdk_request()),
        openai.APITimeoutError(request=_sdk_request()),
    )
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )
    assert info.value.kind == "timeout"
    assert len(sdk_client.calls) == 2


def test_non_transient_not_retried() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(_status_error(400))
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )
    assert info.value.kind == "provider_error"
    assert len(sdk_client.calls) == 1


def test_status_errors_redact_query_credentials() -> None:
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=secret-key"
    sdk_client = fake_sdk_clients.FakeOpenAIClient(
        _status_error(429, url=url), _status_error(429, url=url)
    )
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )

    assert info.value.kind == "rate_limited"
    assert info.value.retryable is True
    assert len(sdk_client.calls) == 2
    assert "secret-key" not in info.value.message
    assert "key=" not in info.value.message
    assert "429" in info.value.message
    assert "gemini-2.5-pro:generateContent" in info.value.message


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[1,2,3]",
        '```json\n{"ok": true}\n```',
        '```\n{"ok": true}\n```',
    ],
)
def test_invoke_rejects_content_that_is_not_one_json_object(text: str) -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(_openai_response(text))
    with pytest.raises(model_calls.ModelError) as info:
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )
    assert info.value.kind == "invalid_response"
    assert info.value.response is not None
    assert info.value.response.usage.request_id == "resp-1"
    assert info.value.response.raw_output == text
    assert info.value.response.parsed_json is None
    identity = info.value.identity
    assert identity is not None
    assert identity.provider == "openai"
    assert len(info.value.response.attempts) == 1
    assert len(sdk_client.calls) == 1


# --- cancellation propagates ------------------------------------------------
def test_cancellation_propagates() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            provider_client.LlmClient(sdk_clients={"openai": sdk_client}).invoke(_request())
        )
