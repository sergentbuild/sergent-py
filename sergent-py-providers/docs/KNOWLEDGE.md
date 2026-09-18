# sergent-py-providers Knowledge

This package is the concrete model transport of the sergent python reference
implementation stack, and the Sergent Specification's
[external-systems boundary](../../sergent/docs/trust-boundaries.md#fifth-external-systems)
made concrete. The [component README](../README.md) states the package's position
and its public offering. The [provider catalog](providers.md) lists the supported
adapters with their SDKs, endpoints, native schema fields, and credential
variables. This document explains the design behind both.

## The Technical Design: Feynman Explanation

A Run needs one JSON object from a model. Between that need and the model sit
provider SDKs that disagree about nearly everything: where a schema goes, how
system text and images are carried, which exception classes exist, and what a
refusal looks like. This package exists to absorb that disagreement so that
nothing else in the stack ever sees it.

### One client, one adapter per provider

The obvious alternative, a self-contained client per provider, fails for a
specific reason: the parts that must not vary would be exactly the parts that
vary. Attempt bounds, error kinds and their retryability, the shape of call
evidence, and the strict parse are promises the runtime and the application
depend on. Four separate implementations of a promise become four different
promises.

So `LlmClient` owns the invariant flow once: resolve the selection, run the
bounded attempt loop, classify failures into a fixed taxonomy, accumulate
evidence, and parse the response text exactly once. A provider adapter is a
small record of provider-level facts and behavior, reached through a closed
registry keyed by provider identifier. The client never branches on a provider
name; it asks the selected adapter. Adapters are curated rather than discovered,
and the registry stays small on purpose: every entry is an official SDK this
package depends on and keeps working.

### What an adapter may translate

An adapter performs the documented translation that its provider's native
facility requires, and nothing else. In practice that is five things:

- the messages, including system text and PNG image inputs, in the provider's
  own content shape;
- the canonical Proposal Schema, written into the one field the provider
  documents for schema-constrained output;
- the per-call controls, which land on different SDK arguments and units;
- the reported usage, normalized onto the shared token keys;
- the provider-specific meanings, namely which HTTP statuses carry a special
  reading and which apparent successes are really failures.

The framework specification fixes that limit at the documented translation, in
[the canonical Proposal Schema](../../sergent/docs/framework.md#the-canonical-proposal-schema).

### What an adapter never sees

The same specification section names what stays outside: proposal classes,
Operation classes, and the Operation Registry. This package holds none of them.
It also never sees the Scene, the Target, the Intent, the Execution Plan, or the
Run identity. A `ModelRequest` arrives with messages, a `ProposalSchema`, model
settings, and a model name. Nothing else crosses.

Two consequences follow, and both are easy to violate by accident.

An adapter cannot judge meaning. It does not know whether the parsed object is a
valid proposal, and it must not try. That judgment belongs to the runtime, at the
[model-output boundary](../../sergent/docs/trust-boundaries.md#first-the-model-output).

An adapter cannot weaken a request to make it succeed. The execution model
forbids mitigation that weakens a model request
([step failure and mitigation](../../sergent/docs/execution-model.md#step-failure-and-mitigation)),
so a retry resends the identical request, and an adapter that cannot express a
request through its provider's native facility fails closed instead of degrading
to prompt-only framing.

### The one transport outside this path

`PerplexityAgentClient` is a plain-text research transport, not a provider
adapter. It does not implement `ModelClient`, carries no Proposal Schema, and
takes no part in selection, retry, or the error taxonomy. It sends text through
the official Agent API with one preset, disables SDK retries, applies a long
timeout suited to research latency, and returns report text only from a completed
response. It lives here because it is an external system reached through an
official SDK with an environment credential, which is precisely this package's
responsibility. What to research, how to phrase it, and what to do with the
report stay in the application.

## The End-To-End Machinery

One call through `LlmClient.invoke` runs these stages in order.

**Selection.** The request carries one caller-provided `provider/model` name,
split at the first slash. The prefix must name a registered adapter; everything
after that first slash is provider-native text preserved exactly, so spaces,
colons, and further slashes survive untouched. A missing slash or an empty prefix
fails as `invalid_model_name`, and an unregistered prefix as `unknown_provider`.
Both are local failures raised before any SDK access.

**The local model preflight.** An adapter may declare that its models exist on
the local machine; only Ollama does. For that adapter the client runs one local
command, as an argument vector without a shell, before the attempt loop. The exit
status is the entire result. Zero continues, one becomes `model_not_found`, and
any other nonzero status, or a command that cannot run at all, becomes
`provider_unavailable` carrying the captured error stream. No prose is parsed.
The check runs once per call, so a retry never repeats it. The specification
recommends exactly this for locally hosted setups, in
[sizing and fail-fast construction](../../sergent/docs/reliability-best-practices.md#sizing-and-fail-fast-construction).

**The attempt loop.** Two attempts at most. Each attempt obtains an SDK client,
either the injected one or a fresh one built from environment credentials with
hidden retries disabled and the per-call timeout applied, and then makes exactly
one provider request. A client this package built is closed when the call
returns; an injected client stays open and belongs to its owner. A failure
consumes the second attempt only when its kind is retryable and an attempt
remains. Everything else ends the call at once. The bound and the identical
second request follow
[model transport and provider adapters](../../sergent/docs/reliability-best-practices.md#model-transport-and-provider-adapters).

**Native Proposal Schema encoding.** The canonical schema travels on the request,
and each adapter writes it into its provider's documented field. Three adapters
send it unchanged. Anthropic is the exception: its SDK must lower the schema
first, and the adapter performs that lowering explicitly. A schema that is valid
under the canonical dialect but that the installed SDK cannot lower fails as
non-retryable `invalid_payload` before the request is sent, which is the
fail-closed behavior the specification asks for instead of a weakened request.
The [catalog](providers.md) owns each exact field and the lowering's documented
effects.

**Envelope checks.** A provider can return HTTP success and still deliver no
usable output. OpenAI reports an incomplete status and can carry a refusal block;
Anthropic reports a refusal or a max-token stop reason. Each adapter with such
documented shapes rejects them as non-retryable `invalid_response` and keeps
whatever text the envelope carried. These are structured provider facts, read
from a status or stop-reason field, not classification of provider prose.

**Evidence and usage.** Every completed attempt closes into one
`ModelAttemptRecord` carrying its own timing, status, retryable flag, and error.
The response carries `ModelIdentity`, which is the provider prefix, the unchanged
model remainder, and the SDK distribution with its installed version, plus
`CallUsage`, which is latency, token counts when the provider reports them, and a
request id when the provider returns one. Token counts use the shared `input` and
`output` keys, and the object stays absent when a provider reports neither, per
the [token counts convention](../../sergent/docs/observability.md#token-counts).

**The strict parse.** It happens once, after the loop, never inside it. Trim the
surrounding whitespace, parse once, and require a JSON object. Text around the
object, several objects, a fenced block, and a truncated object all fail as
`invalid_response`, and nothing salvages a brace substring. Because the parse
sits outside the loop, unusable text never consumes a retry: an identical request
would not make a model's own answer parse, and repair is exactly what this
boundary must not do.

**What returns.** `invoke` returns the `ModelResponse` beside the parsed object.
The response carries identity, the raw provider text, that same parsed object,
the completed attempts, and usage. The runtime decodes the object into a typed
Intent Proposal or Plan Proposal and closes the model call record from these
facts alone, as
[model call records](../../sergent/docs/run-record-spec.md#model-call-records)
defines.

## Trust, Reliability, And Error Handling

Everything here serves one rule: admit external input once, fail closed, and hand
a typed value inward. This package is the
[external-systems boundary](../../sergent/docs/trust-boundaries.md#fifth-external-systems),
so it owns the provider response, the credentials, and the environment discovery.
It owns nothing beyond them, and it re-proves no promise an official SDK already
documents.

### Error kinds and their fixed retryability

The taxonomy is small, stable, and owned here. Retryability is a property of the
kind, never of the site that raised it.

Retryable, meaning an identical second attempt may follow:

- `timeout`: an SDK timeout class, or the underlying HTTP client's timeout class
  when an SDK raises it unwrapped.
- `provider_unavailable`: an SDK connection failure, the underlying HTTP client's
  connection failure raised the same way, or HTTP 5xx.
- `rate_limited`: HTTP 429.

Never retryable:

- `invalid_model_name` and `unknown_provider`: local selection failures.
- `missing_credentials`: a required environment variable is absent.
- `model_not_found`: the local preflight found no such model, or an
  adapter-declared status means the same.
- `invalid_payload`: an adapter-declared status meaning the provider rejected the
  request shape, or an SDK that could not lower the schema.
- `invalid_response`: a refusal, an incomplete envelope, missing text, or text
  that is not exactly one JSON object.
- `provider_error`: any other recognized SDK failure, including one with no HTTP
  status, and a local configuration fault such as a malformed endpoint or a
  settings object of the wrong type.

The official SDK error bases of the providers this package depends on are caught
and mapped, and so are the timeout and connection-failure classes of the HTTP
client beneath them, because the Gemini SDK raises those two transport faults
unwrapped. An unrecognized exception is not classified and propagates.
Provider-specific status meanings live on the adapter, so one provider's reading
of a status never silently becomes every provider's.

The retryable flag has one narrow meaning, fixed by the specification: whether an
identical in-call attempt may follow. Run-level retry is a separate application
decision that reads the kind instead. The runtime carries both facts outward,
recording a transport error's retryable flag in the error metadata of the Run
Record.

### What is never retried

Anything this package raises itself: selection failures, the preflight, missing
credentials, a rejected settings type, a malformed endpoint, a schema the SDK
cannot lower, an envelope rejection, missing text, and invalid JSON. An identical
second request cannot change any of those conditions.

Cancellation is never caught. An interrupted await propagates at once and
attaches no attempt facts from that in-flight call, even when an earlier attempt
in the same call completed, which is what
[model call records](../../sergent/docs/run-record-spec.md#model-call-records)
requires.

### Credential and query-string scrubbing

A provider request URL can carry the API key in its query string, and SDK errors
quote the request URL. Every message that becomes a `ModelError` therefore has
its URL query data stripped first, for SDK failures and for local command
failures alike. A complete Run Record is sensitive forensic data
([sensitivity](../../sergent/docs/observability.md#sensitivity)), so a key that
reached it would be durable.

### Partial evidence on every failure

The Run Record must answer what happened even when nothing usable came back, so
no failure here is bare. A failure that already has a provider response attaches
that partial response, with identity, measured usage, whatever text the envelope
carried, and every completed attempt. A failure with no response carries identity
and the completed attempts directly. A preflight failure carries identity alone,
because no attempt has begun. A parse failure keeps the raw text; a missing-text
failure has none to keep. One failure, one source, so the runtime never assembles
a record from two places.

### Per-call settings

A `ModelRequest` declares its settings as a core strict model, so core and
runtime keep a typed contract without depending on this package. The concrete
`ModelSettings` this package owns is the supported input, and an adapter requires
it before any SDK access; another strict model fails as `provider_error` with no
SDK call and no credential read.

The settings carry a thinking effort, an output-token cap, and a timeout. Each
adapter maps them onto its own SDK arguments and units, and the
[catalog](providers.md) records that mapping. The defaults are safety fallbacks
rather than tuned values: choosing values that fit the codified output is the
application's job under
[per-call sizing](../../sergent/docs/execution-model.md#per-call-sizing). An
undersized cap surfaces as a truncated envelope or a parse failure, so check the
cap before blaming the model. The settings shape is implementation-native, and a
captured model request preserves it as it stands
([captured values](../../sergent/docs/run-record-spec.md#captured-values)).

### Proving this with fakes

Reliability here is proven at two seams, as
[proving reliability with fakes](../../sergent/docs/reliability-best-practices.md#proving-reliability-with-fakes)
places them.

`StaticLlmClient` sits at the model-client interface and serves canned JSON
objects with provider-shaped evidence. It resolves the same full-name selection
and builds the same identity as the real client, returns fixed usage and one
successful attempt, and raises `invalid_response` with one failed attempt once
its outputs run out. It never touches the network, the environment, or a local
command. Use it to prove runtime and application containment.

Below the real client, tests inject fake SDK clients and a fake command runner,
then assert the exact outbound request. A shared fixture removes every credential
variable and replaces the SDK constructors and the subprocess launcher with
raising sentinels, so a test that forgets to inject fails loudly instead of
reaching a provider.

## Adding A New Provider

A new adapter is a commitment to an SDK, so the bar is deliberate. The provider
needs an official Python SDK and a native schema-constrained output facility.
Without that facility the request cannot carry the Proposal Schema at all, and
the specification says not to use the schema with such a model
([canonical schema dialect](../../sergent/docs/framework.md#canonical-schema-dialect)).

Then follow these steps.

1. **Write the catalog entry first**, in [providers.md](providers.md): the
   provider identifier, the official SDK distribution, the client and endpoint,
   the native Proposal Schema field, and the credential variables. The catalog is
   the one list; the registry in code mirrors it.
2. **Extend `CREDENTIAL_ENV_VARS`** with every variable the new client reads. The
   test environment deny-list derives from that tuple, so a variable missing from
   it can let a real credential leak into a test run.
3. **Build the client from the environment.** Disable the SDK's own retries,
   apply the per-call timeout in the units that SDK expects, and fail with
   `missing_credentials` when a required variable is absent.
4. **Shape the messages** into the provider's native content form, including
   system text and PNG image parts. Reject nothing locally on capability grounds;
   a provider's own rejection is the capability answer.
5. **Encode the Proposal Schema** into the single documented field. If the SDK
   requires a lowering step, call it explicitly and fail closed as
   `invalid_payload` when it rejects the schema.
6. **Add the envelope checks.** Read the provider's documentation for shapes that
   return HTTP success while carrying a refusal or a truncation, and reject each
   as `invalid_response` while keeping whatever text arrived.
7. **Map the errors.** Add the provider's SDK error base to the recognized set,
   and declare provider-specific status meanings on the adapter only where the
   provider's reading differs from the shared default. Check whether the SDK
   wraps its HTTP client's timeout and connection faults; when it raises them
   unwrapped, map those classes too. Never classify on message text.
8. **Report usage.** Map the provider's token fields onto the shared `input` and
   `output` keys, and leave the object absent when the provider reports neither.
9. **Test through injected fakes.** Assert the exact outbound request, one case
   for each envelope and error-mapping decision the adapter owns, and never a
   live call, a real SDK client, or a real credential.
10. **Run `just fmt`, `just test`, and `just lint`** before handing the work off.
