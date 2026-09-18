# Provider Adapter And Credential Catalog

This is the one list of supported LLM provider adapters in the Sergent Python
reference implementation. Every other document links here instead of restating
it. The adapter registry in code is private; a change to it must keep this
catalog true.

The catalog owns provider identifiers, official SDK distributions, client and
endpoint behavior, native Proposal Schema encoding, per-call control mapping, and
credentials. It curates no model names, default models, prices, or capability
matrix. SDK version bounds live in the package manifest, not here.
[KNOWLEDGE.md](KNOWLEDGE.md) explains full `provider/model` selection, the call
machinery, retries, error mapping, and the test clients.

## Supported Provider Adapters

| provider identifier | official SDK distribution | endpoint | native Proposal Schema encoding |
|---|---|---|---|
| `openai` | `openai` | `openai.AsyncOpenAI` Responses API | `text.format` with `type: json_schema`, `name`, `schema`, and `strict: true` |
| `anthropic` | `anthropic` | `anthropic.AsyncAnthropic` Messages API | `output_config.format` with `type: json_schema` and a `schema` lowered by an explicit `anthropic.transform_schema()` call |
| `gemini` | `google-genai` | `google.genai.Client` async `generate_content` | `response_json_schema` with `response_mime_type: application/json` |
| `ollama` | `openai` | OpenAI-compatible Chat Completions at `/v1/`, after the local existence preflight | `response_format` with `type: json_schema` and a nested `json_schema` object carrying `name`, `schema`, and `strict: true` |

A registry entry holds provider-level facts and behavior only: SDK identity,
credential and endpoint configuration, client construction, request invocation
and message shaping, and provider error mapping. Adding an adapter must not add
a provider-native model name or a per-model capability flag to the registry or to
this catalog.

The endpoint and encoding facts above describe adapter behavior. Model
availability, context limits, and per-model thinking behavior remain
provider-owned.

## The Anthropic Schema Lowering

OpenAI, Gemini, and Ollama send the canonical schema unchanged. Anthropic is the
only adapter that lowers it. The adapter calls `anthropic.transform_schema()`
explicitly before the Messages request, because passing a raw schema dictionary
does not lower it.

The documented transformation preserves closed objects, enums, unions, local
definitions and references, and a minimum item count of zero or one. Numeric
bounds, maximum item counts, and any larger minimum item count become description
guidance instead. The Plan Proposal envelope requires at least one Operation, so
that minimum survives lowering as a structural constraint.

A canonical schema that is valid at construction but that the installed SDK
cannot lower fails the call as non-retryable `invalid_payload` before any request
is sent. A retry reuses the identical lowered request, as
[step failure and mitigation](../../sergent/docs/execution-model.md#step-failure-and-mitigation)
requires.

## Per-Call Control Mapping

Each adapter maps the shared `ModelSettings` onto its own SDK arguments.

- Thinking effort: `reasoning.effort` for OpenAI, `output_config.effort` for
  Anthropic, and `extra_body.think` for Ollama, where low means false and both
  medium and high mean true. Gemini takes no thinking configuration.
- Output-token cap: `max_output_tokens` for OpenAI and Gemini, and `max_tokens`
  for Anthropic and Ollama. OpenAI and Ollama omit an unset cap. Gemini passes
  the setting through as it stands. Anthropic always sends a cap and falls back
  to its own default when the setting carries none.
- Timeout: the SDK client `timeout` for OpenAI, Anthropic, and Ollama, and
  `HttpOptions.timeout` in milliseconds for Gemini. A timeout applies only to a
  client this package constructs; an injected client keeps its owner's
  configuration.

Provider SDK retries are disabled on every constructed client: `max_retries=0`
for OpenAI, Anthropic, and Ollama, and `HttpRetryOptions(attempts=1)` for Gemini,
whose count includes the original request.

Anthropic keeps adaptive thinking enabled. Gemini disables automatic function
calling on every request and supplies no tools, because the installed SDK enables
it by default and warns on the async path before checking whether callable tools
exist.

## Credentials And Endpoints

Environment variables are read when this package constructs a real SDK client.
The exported `CREDENTIAL_ENV_VARS` tuple lists every variable below, and the test
environment deny-lists derive from it, so a new provider's variables must join
that tuple.

- `openai`: `OPENAI_API_KEY`, required.
- `anthropic`: `ANTHROPIC_API_KEY`, required.
- `gemini`: `GEMINI_API_KEY`, required, with `GOOGLE_API_KEY` as the accepted
  fallback.
- `ollama`: `SERGENT_OLLAMA_BASE_URL`, optional, defaulting to
  `http://127.0.0.1:11434`, which must not end in `/api` and receives an appended
  `/v1/`; and `OLLAMA_API_KEY`, optional, defaulting to the placeholder `ollama`.
- Perplexity Agent API: `PERPLEXITY_API_KEY`, required.

For an Ollama selection, the client runs a local model existence preflight before
its attempt loop. [KNOWLEDGE.md](KNOWLEDGE.md) explains the check.

## The Perplexity Agent API

The Perplexity Agent API is a separate plain-text research transport, not an
adapter in the provider registry. `PerplexityAgentClient` uses the official
`perplexityai` distribution and `perplexity.AsyncPerplexity` with the `medium`
preset, disables SDK retries, and applies a long research timeout.
[KNOWLEDGE.md](KNOWLEDGE.md) explains its boundary and its behavior.
