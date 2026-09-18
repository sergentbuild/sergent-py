from __future__ import annotations

import asyncio
import base64
import types
import typing

import fake_sdk_clients
import sergent_py_core.model_calls as model_calls
import sergent_py_providers.client as provider_client
import sergent_py_providers.settings as provider_settings

PNG_BYTES = b"\x89PNG\r\n\x1a\nabc"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode("ascii")


def _request(model_name: str) -> model_calls.ModelRequest:
    return model_calls.ModelRequest(
        model_name=model_name,
        messages=[
            model_calls.ModelMessage(
                role="user",
                content="Inspect this image.",
                images=[model_calls.ImagePart(data_base64=PNG_BASE64)],
            )
        ],
        model_settings=provider_settings.ModelSettings(),
        proposal_schema=fake_sdk_clients.proposal_schema(),
    )


def _invoke(provider: str, sdk_client: typing.Any, request: model_calls.ModelRequest):
    command_runner = None
    if provider == "ollama":
        command_runner = fake_sdk_clients.FakeCommandRunner(fake_sdk_clients.command_result())
    client = provider_client.LlmClient(
        sdk_clients={provider: sdk_client},
        command_runner=command_runner,
    )
    return asyncio.run(client.invoke(request))


def test_openai_maps_images_to_response_content_parts() -> None:
    sdk_client = fake_sdk_clients.FakeOpenAIClient(fake_sdk_clients.openai_response())
    _invoke("openai", sdk_client, _request("openai/gpt-5.6-sol"))

    assert sdk_client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Inspect this image."},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{PNG_BASE64}",
                },
            ],
        }
    ]


def test_anthropic_maps_images_to_content_blocks() -> None:
    sdk_client = fake_sdk_clients.FakeAnthropicClient(fake_sdk_clients.anthropic_response())
    _invoke("anthropic", sdk_client, _request("anthropic/claude-sonnet-5"))

    assert sdk_client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this image."},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": PNG_BASE64,
                    },
                },
            ],
        }
    ]


def test_gemini_maps_system_and_image_content() -> None:
    sdk_client = fake_sdk_clients.FakeGeminiClient(fake_sdk_clients.gemini_response())
    request = _request("gemini/gemini-pro-latest")
    request.messages.insert(
        0,
        model_calls.ModelMessage(role="system", content="Inspect carefully."),
    )

    _invoke("gemini", sdk_client, request)
    call = sdk_client.calls[0]
    parts = call["contents"][0].parts

    assert call["config"].system_instruction == "Inspect carefully."
    assert parts[0].text == "Inspect this image."
    assert parts[1].inline_data.mime_type == "image/png"
    assert parts[1].inline_data.data == PNG_BYTES


def test_ollama_dispatches_images_for_an_arbitrary_model_name() -> None:
    response = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"ok": true}'))],
        usage=types.SimpleNamespace(prompt_tokens=2, completion_tokens=3),
    )
    sdk_client = fake_sdk_clients.FakeOllamaClient(response)

    _invoke("ollama", sdk_client, _request("ollama/custom/image:model"))

    assert sdk_client.calls[0]["model"] == "custom/image:model"
    assert sdk_client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Inspect this image."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{PNG_BASE64}",
                    },
                },
            ],
        }
    ]
