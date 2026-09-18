"""Provide the sanctioned provider-shaped client for hermetic tests.
@sergent-py-providers/docs/KNOWLEDGE.md"""

from __future__ import annotations

import collections.abc
import json
import typing

import pydantic

import sergent_py_core.model_calls as core_model_calls
import sergent_py_providers.client as client
import sergent_py_providers.facts as facts

_STATIC_REQUEST_ID = "static-provider-request"


class StaticLlmClient(core_model_calls.ModelClient):
    """Serve canned JSON objects with call evidence and no external access.
    @sergent-py-providers/docs/KNOWLEDGE.md"""

    def __init__(
        self,
        outputs: collections.abc.Iterable[object] | None = None,
    ) -> None:
        self.outputs = list(outputs or [])
        self.requests: list[core_model_calls.ModelRequest] = []

    async def invoke(
        self, request: core_model_calls.ModelRequest
    ) -> tuple[core_model_calls.ModelResponse, dict[str, typing.Any]]:
        """Serve the next JSON-compatible object with provider-shaped evidence.
        @sergent-py-providers/docs/KNOWLEDGE.md"""
        self.requests.append(request)
        selection = client._select_model(request.model_name)
        identity = facts._model_identity(selection)
        log = facts._AttemptLog()
        log.begin_attempt()
        if not self.outputs:
            error = core_model_calls.ModelError("invalid_response", "static client has no outputs")
            log.record_failure(error)
            raise core_model_calls.ModelError(
                error.kind,
                error.message,
                identity=identity,
                attempts=log.records,
            )
        raw = self.outputs.pop(0)
        output = (
            raw.model_dump(mode="json", serialize_as_any=True)
            if isinstance(raw, pydantic.BaseModel)
            else raw
        )
        log.record_success()
        response = core_model_calls.ModelResponse(
            identity=identity,
            attempts=log.records,
            usage=core_model_calls.CallUsage(
                latency_ms=7,
                tokens={"input": 11, "output": 13},
                request_id=_STATIC_REQUEST_ID,
            ),
        )
        if not isinstance(output, dict):
            raise core_model_calls.ModelError(
                "invalid_response",
                "static output was not a JSON object",
                response=response,
            )
        try:
            raw_output = json.dumps(output, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError) as exc:
            raise core_model_calls.ModelError(
                "invalid_response",
                "static output was not JSON-compatible",
                response=response,
            ) from exc
        response = response.model_copy(update={"raw_output": raw_output, "parsed_json": output})
        return response, output
