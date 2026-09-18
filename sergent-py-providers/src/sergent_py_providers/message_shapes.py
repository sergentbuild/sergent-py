"""Render core model messages into official SDK content shapes.
@sergent-py-providers/docs/KNOWLEDGE.md"""

from __future__ import annotations

import google.genai.types as genai_types

import sergent_py_core.model_calls as core_model_calls


def _openai_messages(request: core_model_calls.ModelRequest) -> list[dict[str, object]]:
    """Build OpenAI Responses messages with native PNG content blocks.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    messages: list[dict[str, object]] = []
    for message in request.messages:
        content: object = message.content
        if message.images:
            content = [{"type": "input_text", "text": message.content}]
            content.extend(
                {
                    "type": "input_image",
                    "image_url": f"data:{image.media_type};base64,{image.data_base64}",
                }
                for image in message.images
            )
        messages.append({"role": message.role, "content": content})
    return messages


def _ollama_messages(request: core_model_calls.ModelRequest) -> list[dict[str, object]]:
    """Build OpenAI Chat Completions messages with native PNG content blocks.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    messages: list[dict[str, object]] = []
    for message in request.messages:
        content: object = message.content
        if message.images:
            blocks: list[dict[str, object]] = [{"type": "text", "text": message.content}]
            blocks.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image.media_type};base64,{image.data_base64}"},
                }
                for image in message.images
            )
            content = blocks
        messages.append({"role": message.role, "content": content})
    return messages


def _anthropic_messages(
    request: core_model_calls.ModelRequest,
) -> tuple[str, list[dict[str, object]]]:
    """Build Anthropic system and conversation content with native PNG blocks.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    system = "\n".join(message.content for message in request.messages if message.role == "system")
    messages: list[dict[str, object]] = []
    for message in request.messages:
        if message.role == "system":
            continue
        content: object = message.content
        if message.images:
            blocks: list[dict[str, object]] = [{"type": "text", "text": message.content}]
            blocks.extend(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data_base64,
                    },
                }
                for image in message.images
            )
            content = blocks
        messages.append({"role": message.role, "content": content})
    return system, messages


def _gemini_contents(
    request: core_model_calls.ModelRequest,
) -> tuple[str | None, list[genai_types.Content]]:
    """Build Gemini system instruction and native text or PNG parts.
    @sergent-py-providers/docs/KNOWLEDGE.md"""
    system = (
        "\n".join(message.content for message in request.messages if message.role == "system")
        or None
    )
    contents: list[genai_types.Content] = []
    for message in request.messages:
        if message.role == "system":
            continue
        parts = [genai_types.Part(text=message.content)]
        parts.extend(
            genai_types.Part.from_bytes(
                data=image.decoded_bytes(),
                mime_type=image.media_type,
            )
            for image in message.images
        )
        contents.append(
            genai_types.Content(
                role="user",
                parts=parts,
            )
        )
    return system, contents
