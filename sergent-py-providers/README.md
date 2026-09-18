# sergent-py-providers

`sergent-py-providers` is the concrete model transport of the sergent python
reference implementation stack. It depends on `sergent-py-core`, implements the
async `ModelClient` interface, and is the only package in the stack that speaks
to a model provider.

## The Big Picture

The Sergent Specification closes its trust model with a short, closed list of
boundaries. This package is one of them made concrete: the
[external-systems boundary](../sergent/docs/trust-boundaries.md#fifth-external-systems).
Every provider SDK call, every credential read, and every strict parse of
provider text happens here.

That placement decides the shape of everything inside. Above this package,
`sergent-py-runtime` drives a deterministic Run. Below it, the provider SDKs
disagree about request shape, schema facility, error classes, and what a
successful response looks like. This package is the narrow seam between those
two worlds. It hands the runtime one `ModelResponse` beside one parsed JSON
object, and it hands each provider what that provider's documented API requires.
Nothing above it learns a provider name beyond the `provider/model` string the
application chose, and nothing below it learns what the JSON means. Judging
whether that JSON is a valid proposal belongs to the runtime, at the
[model-output boundary](../sergent/docs/trust-boundaries.md#first-the-model-output).

## The Technical Design And Its Philosophy

The design is one client and one adapter per provider. `LlmClient` owns
everything that must behave identically whichever provider is selected:
selection, the attempt loop, error classification, call evidence, and the strict
parse. An adapter owns only what genuinely differs. The specification treats the
adapter as a suggested strategy rather than a rule
([canonical schema dialect](../sergent/docs/framework.md#canonical-schema-dialect));
this implementation takes the suggestion because the provider differences are
real and each one is small enough to isolate.

These decisions shape the rest:

- **Each provider is called through its official Python SDK**, as the
  specification's
  [implementer guidance](../sergent/docs/for-implementers.md#interact-with-the-model-providers)
  recommends. The package relies on documented SDK promises and never re-proves them.
- **Provider text gets one strict parse and no repair.** Trim once, parse once,
  reject anything that is not a single JSON object. Fence stripping, brace
  hunting, and truncation repair are all forbidden here.
- **Retry is bounded and hidden retries are disabled.** Two attempts at most,
  the second request identical to the first. Every SDK client this package builds
  has its own retry machinery off, so one attempt is exactly one provider request.
- **Classification reads structured facts.** An exception class and an integer
  HTTP status decide an error kind; a command exit status decides the local
  model check. No decision reads human-readable provider prose.
- **Credentials come from the environment**, read only at real client construction.
- **Provider-shaped fakes are the test seam.** SDK clients and the local command
  runner are injected; no test reaches a provider or reads a real credential.
- **There is no model catalog.** The package curates provider identifiers, not
  model names; a provider's own rejection is the capability answer.

Applications never import this package directly. The battery package
`sergent_py` constructs `LlmClient` in its default wiring and re-exports
`ModelSettings`, `ThinkingEffort`, `CREDENTIAL_ENV_VARS`, and
`PerplexityAgentClient`. `StaticLlmClient` is the sanctioned provider-shaped
fake for hermetic tests.

## The Specific Challenges Of Different Providers

Providers agree on little below the request. Four differences matter most:

- **Anthropic** is the only adapter that does not send the canonical schema
  unchanged. Its SDK lowers the schema to the dialect its Messages API accepts,
  and the adapter performs that lowering explicitly, before the request.
- **Gemini** enables automatic function calling by default and warns about it on
  the async path before checking whether tools exist, so every request disables
  it. Its timeout and retry bounds travel in HTTP options, not client arguments.
- **Ollama** runs through the OpenAI SDK against a local OpenAI-compatible
  endpoint, so OpenAI error classes cover it, but a model the machine never
  pulled looks like an ordinary HTTP failure. A local existence check runs first
  and turns that into a clear model-not-found result.
- **OpenAI and Anthropic** can refuse or truncate while still returning HTTP
  success, so both adapters inspect the response envelope before treating any
  text as usable output.

## Knowledge Artifacts

- [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md): the distilled design, covering the
  client-and-adapter shape, the machinery of one call, the trust and error model,
  and how to add a provider.
- [docs/providers.md](docs/providers.md): the catalog, and the one list of
  supported adapters with their SDKs, endpoints, native Proposal Schema fields,
  and credential variables.
