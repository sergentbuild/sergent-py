"""Resolve full model names and enforce bounded, strict provider calls.
@sergent/docs/trust-boundaries.md
@sergent-py-providers/docs/KNOWLEDGE.md"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import re
import typing
import urllib.parse

import anthropic
import google.genai.errors as genai_errors
import httpx
import openai
import sergent_py_core.model_calls as core_model_calls
import sergent_py_providers.facts as facts
import sergent_py_providers.transports as transports

_MAX_ATTEMPTS = 2


@dataclasses.dataclass(frozen=True)
class _ProviderAdapter:
    """Bind one curated provider to its transport-level facts and behavior.
    @sergent-py-providers/docs/providers.md"""

    sdk_package: str
    make_client: typing.Callable[[int | None], object]
    invoke: typing.Callable[
        [_ModelSelection, core_model_calls.ModelRequest, object],
        typing.Awaitable[core_model_calls.ModelResponse],
    ]
    status_errors: tuple[tuple[int, str], ...] = ()
    local_model_preflight: bool = False

    def status_error_kind(self, status: int) -> str | None:
        """Return a provider-specific stable error kind when configured.
        @sergent-py-providers/docs/KNOWLEDGE.md"""
        return dict(self.status_errors).get(status)


@dataclasses.dataclass(frozen=True)
class _ModelSelection:
    """Carry a curated provider adapter and unchanged provider-native model name.
    @sergent-py-providers/docs/KNOWLEDGE.md"""

    provider: str
    adapter: _ProviderAdapter
    model: str


_ADAPTERS = {
    "openai": _ProviderAdapter(
        sdk_package="openai",
        make_client=transports._openai_client,
        invoke=transports._call_openai,
    ),
    "anthropic": _ProviderAdapter(
        sdk_package="anthropic",
        make_client=transports._anthropic_client,
        invoke=transports._call_anthropic,
    ),
    "gemini": _ProviderAdapter(
        sdk_package="google-genai",
        make_client=transports._gemini_client,
        invoke=transports._call_gemini,
    ),
    "ollama": _ProviderAdapter(
        sdk_package="openai",
        make_client=transports._ollama_client,
        invoke=transports._call_ollama,
        status_errors=(
            (400, "invalid_payload"),
            (422, "invalid_payload"),
            (404, "model_not_found"),
        ),
        local_model_preflight=True,
    ),
}


def _select_model(model_name: str) -> _ModelSelection:
    """Resolve the provider prefix while preserving its native model remainder.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    provider, separator, model = model_name.partition("/")
    if not separator or not provider:
        raise core_model_calls.ModelError(
            "invalid_model_name",
            "model_name must include a provider prefix followed by '/'",
        )
    try:
        adapter = _ADAPTERS[provider]
    except KeyError as exc:
        raise core_model_calls.ModelError(
            "unknown_provider", f"unknown llm provider: {provider!r}"
        ) from exc
    return _ModelSelection(provider=provider, adapter=adapter, model=model)


def _extract_json_object(text: str) -> dict:
    """Parse one complete JSON object without repair or salvage.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    stripped = text.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise core_model_calls.ModelError("invalid_response", "response JSON was invalid") from exc
    if not isinstance(value, dict):
        raise core_model_calls.ModelError("invalid_response", "response JSON was not an object")
    return value


def _status_code(exc: BaseException) -> int | None:
    """Read an integer HTTP status exposed by an SDK exception."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    return status if isinstance(status, int) else None


def _strip_url_query(raw_url: str) -> str:
    """Remove query data from an error URL before it enters evidence."""
    parts = urllib.parse.urlsplit(raw_url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _request_url(exc: BaseException) -> str | None:
    """Find a request URL exposed by known SDK error shapes."""
    sources = [
        getattr(exc, "request", None),
        getattr(getattr(exc, "response", None), "request", None),
        getattr(exc, "response", None),
    ]
    for source in sources:
        url = getattr(source, "url", None)
        if url is not None:
            return str(url)
    return None


def _safe_error_message(exc: BaseException) -> str:
    """Sanitize URL query data before an SDK failure enters call evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    message = str(exc) or exc.__class__.__name__
    request_url = _request_url(exc)
    if request_url:
        safe_url = _strip_url_query(request_url)
        message = message.replace(request_url, safe_url)
        if safe_url not in message:
            message = f"{message} for {safe_url}"
    return _sanitize_url_queries(message)


def _sanitize_url_queries(message: str) -> str:
    """Remove URL query data from provider text before it enters evidence.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    for raw_url in re.findall(r"https?://[^\s'\"<>]+", message):
        message = message.replace(raw_url, _strip_url_query(raw_url))
    return message


def _sdk_error(exc: BaseException, adapter: _ProviderAdapter) -> core_model_calls.ModelError:
    """Map a recognized SDK failure to the provider-neutral retry contract.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    message = _safe_error_message(exc)
    status = _status_code(exc)
    if isinstance(
        exc,
        (openai.APITimeoutError, anthropic.APITimeoutError, httpx.TimeoutException),
    ):
        return core_model_calls.ModelError("timeout", message, retryable=True)
    if isinstance(
        exc,
        (openai.APIConnectionError, anthropic.APIConnectionError, httpx.ConnectError),
    ):
        return core_model_calls.ModelError("provider_unavailable", message, retryable=True)
    if isinstance(exc, genai_errors.APIError) and status is None:
        status = exc.code
    if status is not None:
        if "HTTP" not in message:
            message = f"HTTP {status}: {message}"
        if status == 429:
            return core_model_calls.ModelError("rate_limited", message, retryable=True)
        provider_kind = adapter.status_error_kind(status)
        if provider_kind is not None:
            return core_model_calls.ModelError(provider_kind, message)
        if status >= 500:
            return core_model_calls.ModelError("provider_unavailable", message, retryable=True)
        return core_model_calls.ModelError("provider_error", message)
    return core_model_calls.ModelError("provider_error", message)


async def _default_command_runner(argv: list[str]) -> tuple[int, str]:
    """Run one local provider command without a shell and capture its stderr.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        raise
    returncode = process.returncode
    if returncode is None:
        returncode = await process.wait()
    message = (stderr or b"").decode("utf-8", errors="replace")
    return returncode, message


def _parse_json_payload(
    response: core_model_calls.ModelResponse,
) -> dict[str, typing.Any]:
    """Admit one JSON object while preserving partial evidence on failure.
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    if response.raw_output is None:
        if response.parsed_json is None:
            raise core_model_calls.ModelError(
                "invalid_response",
                "response contained no JSON object",
                response=response,
            )
        return response.parsed_json
    try:
        return _extract_json_object(response.raw_output)
    except core_model_calls.ModelError as exc:
        raise core_model_calls.ModelError(
            exc.kind,
            exc.message,
            retryable=exc.retryable,
            response=response,
        ) from exc


class LlmClient(core_model_calls.ModelClient):
    """Provide official-SDK transport with bounded retries and strict one-object parsing.
    @sergent/docs/execution-model.md
    @sergent/docs/trust-boundaries.md
    @sergent-py-providers/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        *,
        sdk_clients: dict[str, object] | None = None,
        command_runner: typing.Callable[[list[str]], typing.Awaitable[tuple[int, str]]]
        | None = None,
    ) -> None:
        self._sdk_clients = sdk_clients or {}
        self._command_runner = command_runner or _default_command_runner

    async def invoke(
        self, request: core_model_calls.ModelRequest
    ) -> tuple[core_model_calls.ModelResponse, dict[str, typing.Any]]:
        """Return call evidence beside one strictly parsed JSON object.
        @sergent/docs/execution-model.md
        @sergent/docs/trust-boundaries.md
        @sergent-py-providers/docs/KNOWLEDGE.md"""
        selection = _select_model(request.model_name)
        await self._preflight(selection)
        log = facts._AttemptLog()
        response = await self._call_with_retries(selection, request, log)
        response = response.model_copy(update={"attempts": log.records})
        payload = _parse_json_payload(response)
        response = response.model_copy(update={"parsed_json": payload})
        return response, payload

    async def _call_with_retries(
        self,
        selection: _ModelSelection,
        request: core_model_calls.ModelRequest,
        log: facts._AttemptLog,
    ) -> core_model_calls.ModelResponse:
        """Run at most two provider attempts and close evidence for completed passes.
        @sergent-py-providers/docs/KNOWLEDGE.md"""
        identity = facts._model_identity(selection)
        for attempt_index in range(1, _MAX_ATTEMPTS + 1):
            log.begin_attempt()
            try:
                response = await transports._run_call(
                    selection,
                    request,
                    sdk_client=self._sdk_clients.get(selection.provider),
                )
            except transports._SDK_ERROR_TYPES as exc:
                err = _sdk_error(exc, selection.adapter)
                log.record_failure(err)
                if not err.retryable or attempt_index == _MAX_ATTEMPTS:
                    raise core_model_calls.ModelError(
                        err.kind,
                        err.message,
                        retryable=err.retryable,
                        identity=identity,
                        attempts=log.records,
                    ) from exc
            except core_model_calls.ModelError as exc:
                log.record_failure(exc)
                if exc.response is not None:
                    response = exc.response.model_copy(update={"attempts": log.records})
                    raise core_model_calls.ModelError(
                        exc.kind,
                        exc.message,
                        retryable=exc.retryable,
                        response=response,
                    ) from exc
                raise core_model_calls.ModelError(
                    exc.kind,
                    exc.message,
                    retryable=exc.retryable,
                    identity=identity,
                    attempts=log.records,
                ) from exc
            else:
                log.record_success()
                return response
        raise AssertionError("retry loop exhausted without response")

    async def _preflight(self, selection: _ModelSelection) -> None:
        """Exact-check an Ollama model once before provider retries.
        @sergent-py-providers/docs/KNOWLEDGE.md"""
        if not selection.adapter.local_model_preflight:
            return
        identity = facts._model_identity(selection)
        argv = ["ollama", "show", selection.model]
        try:
            returncode, stderr = await self._command_runner(argv)
        except OSError as exc:
            message = _sanitize_url_queries(str(exc) or exc.__class__.__name__)
            raise core_model_calls.ModelError(
                "provider_unavailable", message, identity=identity
            ) from exc
        if returncode == 0:
            return
        if returncode == 1:
            raise core_model_calls.ModelError(
                "model_not_found",
                f"Ollama model not found: {selection.model!r}",
                identity=identity,
            )
        message = stderr or f"ollama show exited with status {returncode}"
        raise core_model_calls.ModelError(
            "provider_unavailable",
            _sanitize_url_queries(message),
            identity=identity,
        )
