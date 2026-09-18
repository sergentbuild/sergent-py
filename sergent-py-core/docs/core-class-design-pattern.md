# Core Class Design Pattern

The classes in this package are the foundation of the Sergent Python reference implementation:
every other package builds on their shape. This document states the design rules that keep them
small, loosely coupled, and free of duplication. Read it before adding a class or a field here, and
hold changes elsewhere to the same rules when they construct or read these classes.

## The class families

Each concept has one responsibility, and no class here knows about engines, concrete transports, or
applications. The classes form four stable families:

- Boundary primitives and interfaces own identity, timing, errors, Scene and Target facts, MindBuf
  input, and the three framework seams.
- Proposal and execution values own Intent flow reading, immutable Operations, the application
  Operation Registry, canonical Proposal Schemas, Execution Plans, Patches, and rebase outcomes.
- Model-call values own requests, messages, endpoint identity, returned data, usage, attempts, and
  transport failures, without implementing a provider.
- Run Record and Sergent Result values own captured application data, ordered Run evidence,
  terminal facts, cancellation, Scene transition, and the final result.

The three framework interfaces are `ModelClient`, `SceneActions`, and `SergentRecipe`. Their
separate modules reflect their different owners and responsibilities. A module is named for the
specification concept it interprets, and a fact lives with the boundary that produces it.

## The pattern rules

### 1. Closed-world data

Every data class extends `StrictModel`: unknown fields fail validation and assignment revalidates.
Construction fails loudly on a shape mismatch. A tolerant builder, one that filters keyword
arguments down to "what fits" or attaches leftover values dynamically, is banned anywhere these
classes are constructed; it converts shape errors into silent data loss.

`Operation` is the one class outside the `StrictModel` parentage. It extends the Pydantic base
directly, declares the class keywords that freeze it and forbid unknown fields, and is abstract, so
a concrete Operation must supply its own apply behavior. Operations are immutable script steps:
freezing removes the mutation window between validate, dry-run, and commit, and it legalizes the
single-value discriminator literal for the type checker. The class-keyword form is load-bearing,
because pyright honors the frozen setting only as a class keyword and never through a
configuration dictionary, so every concrete Operation subclass restates it. Pydantic inherits the
configuration at runtime regardless; the restatement is for the checker.

### 2. One owner per travel-together fact group

Facts that always move together get exactly one owning value object, shared by value across every
holder:

| value object | owns | shared by |
| --- | --- | --- |
| `ModelIdentity` | the resolved endpoint and the SDK that served it | `ModelResponse`, `ModelError`, `ModelCallRecord` |
| `CallUsage` | the measured transport outcome of one call | `ModelResponse`, `ModelCallRecord` |
| `ProposalSchema` | the canonical structure and stable name of one proposal | `ModelRequest`, `ModelCallRecord` |
| `TimeSpan` | one wall-clock lifecycle with its measured duration | `RunRecord`, `RunStepRecord`, `ModelAttemptRecord` (closed span required) |
| `SceneTransition` | the Scene identity and the revisions entering and leaving | `RunRecord` |
| `Cancellation` | the cancellation request facts; absence means never requested | `RunRecord` |
| `RunOutcome` | status, error, and terminal data under a coherence validator | `RunRecord` |
| `ModelCallPayloads` | the model- and app-authored payloads of one call | `ModelCallRecord` |

A new owner is justified only by a real lifecycle, invariant, validation rule, or behavior surface.
A wrapper that merely renames fields and forwards access is ceremony; reject it and keep the fields
where they are.

### 3. The required shape

Every class stays at or under ten fields naturally. Field-count pressure is a design signal, not a
nuisance: it means the class is mixing unrelated responsibilities, or a travel-together group is
missing its owner. The fix is finding or creating that owner (rule 2), never widening the gate.

### 4. No mirror fields: the loss test

Before storing a field, name what observable capability is lost if the field is absent, and whether
it is recoverable from existing structure. Store nothing recoverable from:

- **list position**: a Step Record has no index, because its position in the Run Record Ledger is
  the index; an attempt row has no attempt number, for the same reason.
- **a derived roll-up**: a capture failure is recorded in place on the captured value where capture
  failed, so any roll-up is derived by walking the fixed slots. There is no stored list to keep
  synchronized.
- **another object already held**: an error that holds its response does not copy the response's
  fields (rule 5).
- **an echo of the other side of the model-call interface**: a response does not repeat the
  request's model selection, because the model call record and its captured request already carry
  that fact.

A flat field earns its place only as a Run input or a stable domain fact with an unrecoverable loss
story. The Run Record's model name is the worked example: the
[observability specification](../../sergent/docs/observability.md#ownership) requires the Run Record
to name the chosen model even when the Run makes no model call, so it stays even though nested
captured requests also carry a model name. The two are different facts: what the Run selected
versus what one request used.

### 5. Single source of truth across holders

Transient model-call objects reference; the durable Run Record copies whole value objects.

- `ModelError` holds the partial `ModelResponse` when one exists, and that held response is the
  single source of call and payload facts. Its identity and attempts derive from the response. A
  response-less error instead stores those two fallback facts privately. Consumers read the
  error's response for payloads and its two properties for call facts; the error never copies
  response-owned fields.
- `ModelCallRecord` copies identity and usage as whole value objects, so the Run Record stays valid
  after the transient objects die. Copying the value object is the sanctioned form of duplication;
  re-flattening its fields into loose Run Record fields is not.
- `ModelAttemptRecord` owns one attempt's closed timing, status, retryability, and error. It never
  copies usage latency, token counts, or request identity, and an interrupted provider await
  produces no attempt, as the
  [model call record](../../sergent/docs/run-record-spec.md#model-call-records) rules require.
- `ModelClient` returns data beside objects instead of growing them: invoking it returns the
  response and the parsed proposal payload together. The payload is not stored as a typed proposal
  on the response, and the model call record owns the request's `ProposalSchema`, from which the
  schema name derives, while captured request evidence omits the schema.

### 6. Split by failure domain, not by phase

`CapturedValue` marks the best-effort projection boundary for application-shaped Run Record slots:
step inputs and outputs, app-authored request content, parsed proposals, and terminal message or
metadata. These slots may contain app-owned values whose serialization can fail. Provider text,
extracted JSON, endpoint identity, usage, and scalar transport facts remain plain. This keeps typed
transport facts out of hostage range: a capture failure can never blank latency, tokens, or
identity. Capture is best-effort and never fails the Run.

### 7. Behavior methods over raw reads

When a decision or derivation exists, it lives behind a method on the owning object: usage answers
how many output tokens it measured, which supports complete output aggregation, and a time span
answers whether it is closed, which avoids null-checking paired fields. Raw stored facts without a
derived decision stay directly readable; usage keeps its provider-measured entries as data.

### 8. Wholesale replacement for validator-bearing values

Value objects with cross-field validators are replaced whole, never mutated field by field: a time
span opens and then returns a closed replacement, a Scene transition opens from an identity and
then returns a committed replacement, a cancellation record is created from its request facts, and
a fresh outcome is built at finish. Because `StrictModel` revalidates on assignment, half-mutating
such a value would run its validator against a transient illegal state. These copy-constructors
also keep every constraint live on every copy, which a plain model copy would skip.

### 9. Model-facing structure has one canonical owner

`ProposalSchema` has one owner chain: the core factory owns validation-mode derivation and
canonical-dialect conformance, `OperationRegistry` owns eager branch caching and Plan Proposal
composition, and a late `ModelRequest` carries the already-derived value and never repairs it. The
specification's
[semantic rules ride the schema](../../sergent/docs/framework.md#semantic-rules-ride-the-schema)
rule is why no second model-facing structure exists.

The Operation family's framework-owned identity is a Pydantic private attribute, so it is absent
from model-visible data, and both an echoed identity field and an unknown bookkeeping field fail
closed at the typed crossing. The class docstring and field descriptions carry permitted semantic
description into schema derivation; structural prompt text is not another annotation hook.

That private attribute is the sole framework-owned Operation identity. The read-only `op_id`
property exposes it, and narrow assignment and deletion guards preserve the frozen guarantee. The
base `Operation` field set is part of every application's Programming Interface, so growing it with
Run or result bookkeeping would create an unstable API even when a field is excluded from model
serialization. The [Operation identity](../../sergent/docs/framework.md#operation-identity) rule
keeps Run identity on the enclosing Run and Run Record.

Copying an Execution Plan into a Patch is framework-owned. Deep-copy each Operation and its nested
application values, preserve the source identity, and build traces from the copies. Do not expose a
public binding method or ask applications to copy framework identity.

### 10. Interface parameters are positional-only; `Any` marks app-owned meaning

The repository typing policy owns the rules; this package applies them at these places. Every
method of the three interfaces and both Operation hooks declares positional-only parameters. The
base owns the calling convention; implementers keep their own parameter names, including the
underscore-unused convention, and still conform. Intent and Plan request builders receive the
runtime's cached Proposal Schema as their final positional-only argument and return it unchanged on
the request.

An override may narrow an `Any` parameter to the app's own type, as a concrete Operation does when
it annotates its own Scene class. Narrowing an `object` parameter is an override violation, which is
exactly why pass-through slots stay `object`. Type parameters exist only where an
application-owned type flows through an interface: Scene, Intent Proposal, and Intent. Operation
scripts are heterogeneous by design, so their envelopes, the registry, and the `SceneActions`
interface use the base `Operation` vocabulary directly. Do not add an Operation type parameter that
consumers immediately erase back to the base class.

### 11. Coupling points down and stays narrow

Core owns the `SceneActions` and `ModelClient` protocols and the default-bearing `SergentRecipe`
abstract base, so the runtime and provider integrations share one vocabulary without depending on
each other. Providers construct model-call transport facts, the runtime is the production owner
that builds Run Records, and no Run Record class grows a field to serve one consumer's convenience.

## Adding a fact without regressing

1. Name the fact's owner first. Endpoint fact, measured usage, timing, Scene transition, outcome,
   cancellation, or call payload: put it inside that value object, and every holder receives it
   without any holder changing shape or field count.
2. If no owner fits, run the loss test (rule 4). Only a Run input or a stable domain fact with an
   unrecoverable loss story earns a new flat field.
3. If the fact crosses the model-call boundary, decide once where it lives (rules 2 and 9). Never
   add another schema name or wire copy.
4. Run `just fmt`, `just test`, and `just lint` after code or document changes.
5. Update this package's knowledge file and README in the same change. Treat any change to the Run
   Record shape as a specification change: the
   [Run Record specification](../../sergent/docs/run-record-spec.md) owns that shape.
