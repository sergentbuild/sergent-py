# sergent-py-core Knowledge

This document explains how the foundation package of the Sergent Python reference implementation is
designed. The [Sergent Specification](../../sergent/docs/KNOWLEDGE.md) teaches the concepts and owns
their rules; every subject below names one concept, shows the Python shape that materializes it, and
gives the rule or test that keeps that shape honest. The [component README](../README.md) states the
package boundary, and the [core class design pattern](core-class-design-pattern.md) is the standing
rulebook for adding or changing a class or a field.

## Technical design and philosophy

**Core is a vocabulary, not a coordinator.** The
[Run flow](../../sergent/docs/execution-model.md#the-sergent-run-flow) belongs to the specification
and its execution belongs to the runtime. Core names the value or interface that each step of that
flow carries, so a core module answers "what is exchanged here", never "what happens next".

**Construction is the admission.** Nearly every data class here extends one strict Pydantic base
that rejects unknown keys and revalidates on assignment. That is the Python form of the
[trust rule](../../sergent/docs/trust-boundaries.md#the-trust-rule): a value is checked once where
it enters and trusted everywhere after. A validation hook may therefore stay empty, and a second
check for a fact an owner already admitted is a defect, not caution.

**One fact has one owner.** Facts that always travel together live in one value object that every
holder shares, and nothing stores what it can derive.

**Synchronous by default.** Only the model-call interface has an asynchronous method, which is what
the specification's [async execution](../../sergent/docs/execution-model.md#async-execution) section
allows: the async form changes scheduling, not the flow. Nothing here awaits, imports an event loop,
opens a socket, or touches a file.

**One current shape.** Core defines the current version of each structure and carries no
compatibility variant, alternate reader, or migration. A shape change replaces the previous shape in
place.

## Subject tour

The subjects follow the specification's own reading order: framework, execution model, trust
boundaries, observability, and the Run Record.

### Closed-world values

The strict Pydantic base is the one place where fail-closed behavior is configured, so no class
repeats the configuration and no class opts out of it quietly. A shared text helper rejects blank
boundary text, turning an empty string into a construction failure rather than a downstream
surprise. `Operation` is the single class outside this base, for the reason its own subject gives.
A tolerant builder that filters keyword arguments down to what fits is banned wherever these classes
are constructed, because it turns a shape error into silent data loss.

### The three interfaces

Three seams cross out of this package, and their shapes differ because their owners differ.
`SceneActions` is the Python binding of the
[Scene Actions](../../sergent/docs/terminology.md#scene-actions): identity, isolated clone, Target
selection and existence, Target-aware apply, and verification. `ModelClient` is the
[external-system boundary](../../sergent/docs/trust-boundaries.md#fifth-external-systems) for model
transport. Both are structural protocols, because the code that satisfies them lives in other
packages and in application code, and structural typing lets an implementer conform without
inheriting anything from core. `SergentRecipe` is the Python binding of the
[Recipe](../../sergent/docs/terminology.md#recipe) and is an abstract base class instead, because
the framework owns mechanical defaults that an implementer inherits.

Three rules hold across all three. Every method takes positional-only parameters, so the base owns
the calling convention while implementers keep their own parameter names. Type parameters exist only
where an application-owned type genuinely flows through a seam: the Scene, the Intent Proposal, and
the Intent. Operation scripts are heterogeneous by design, so envelopes, the registry, and the Scene
interface speak the base Operation vocabulary directly.

### Observation, Scene identity, Target, and verification

`MindBuf` is the Python base for the out-of-Scene channel of the
[Observation](../../sergent/docs/terminology.md#observation): a plain class rather than a strict
model, because what it exports is application-rendered text. The base renders nothing.

`SceneIdentity` binds one Scene ID to one non-negative revision: the fact a Run observed. Choosing
whether that revision must still be current is the application's
[writer model](../../sergent/docs/framework.md#writer-model-and-revision-policy) decision, and core
deliberately supplies no policy for it. What core does supply is the one check that
[embedded revision ownership](../../sergent/docs/execution-model.md#revision-representation)
requires: `identity_transition_issues` reports identity drift or a revision that did not advance by
exactly one.

`Target` carries the selected Target ID and nothing else; an application subclasses it to add the
execution context its domain rules need. Every consumer treats it as read-only and ephemeral under
[Target ownership](../../sergent/docs/framework.md#target-ownership), and core gives it no mutation
surface. `VerificationReport` carries the issue list of the
[Verification Report](../../sergent/docs/terminology.md#verification-report); an empty list accepts
the resulting Scene. Three more values serve
[Patch rebase on shared live state](../../sergent/docs/execution-model.md#patch-rebase-on-shared-live-state):
a rebase request, a rebased Patch with Scene-supplied metadata, and a merge conflict with its
reason. Core names them so the Scene can answer in typed terms; the Scene owns the domain decision
and the runtime owns the second admissibility pass around it.

### Operation, its identity, and its two hooks

An `Operation` is one call over the application's
[Programming Interface](../../sergent/docs/terminology.md#programming-interface). It is the one core
class outside the strict base: it extends the Pydantic base directly with frozen and
unknown-field-rejecting class keywords, and it is abstract. Frozen removes the mutation window
between validation, rehearsal, and commit, and it legalizes the single-value discriminator literal
for the type checker. The class-keyword form is load-bearing because the type checker honors it only
there, so every concrete subclass restates it. Abstract means the application must supply the apply
behavior; the base has none to inherit.

[Operation identity](../../sergent/docs/framework.md#operation-identity) is framework-owned, so core
mints it into a private attribute exposed through a read-only property and guarded against
assignment and deletion. It is therefore absent from every derived schema and every serialized
payload, and a deep copy preserves it. `OperationTrace` is the matching row that ties one Patch
Operation back to that identity.

Admissibility answers the narrow question of the
[Operation Admissibility flow](../../sergent/docs/execution-model.md#operation-admissibility-flow):
it rejects by raising, accepts by returning, and the base accepts, because an Operation with no
extra precondition needs no custom check. Apply performs the deterministic change through Scene
behavior.

### Plan Proposal, Execution Plan, and Patch

These three values are the same Operations at three stages of trust, and keeping them separate is
what makes the [second phase](../../sergent/docs/framework.md#the-second-phase) auditable.
`PlanProposal` is the closed envelope the model fills, and its minimum of one Operation lives on the
class itself because a continuing Run must compile to a non-empty Patch. `ExecutionPlan` binds a
validated script to the Scene identity it was planned against. `Patch` carries that base, the
Operations, and one trace row for each of them.

The Recipe's mechanical default compiles that Patch: it deep-copies every Operation and its nested
application values, preserves each Operation identity, and builds the traces from the copies. Plan
and [Patch](../../sergent/docs/terminology.md#patch) therefore share correlation facts and share no
mutable state. The configured maximum lives in Recipe configuration, not on the envelope class.

### Canonical Proposal Schemas

The specification asks each implementation to document how its type system maps onto the
[canonical schema dialect](../../sergent/docs/framework.md#canonical-schema-dialect); this is that
mapping. `ProposalSchema` is the single structural value that travels from a proposal definition to
model transport and then into evidence: a stable name and deterministic JSON data. Applications
never author that data. One factory derives it from one exact Pydantic class in three stages,
reading the validation-mode schema because that same exact class later receives provider data.

The traversal walks every reachable annotation, including metadata, union members, container keys
and values, and inherited structures, across Pydantic models, Pydantic dataclasses, and typed
dictionaries. It rejects application authorship of model-facing structure: overridden schema
methods, authored titles, schema extras, and explicit include or skip markers. Annotation forms
whose structural meaning it cannot prove, such as standard-library dataclasses and opaque type
wrappers, fail construction rather than being weakened. A field alias is allowed only as one unique
provider key that validation would actually accept; alias paths, alias choices, and duplicate
provider keys fail.

Normalization is a closed list, never a repair: it removes generated titles, defaults, and the
refinements the dialect cannot express; it requires every declared property; it turns a constant
into a one-value enumeration; and it wraps a described reference in a described union. Conformance
then proves the result against the closed dialect: closed objects, typed array items, inclusive
bounds, scalar enumerations, and local references that resolve without cycles.

One consequence deserves attention: the derived schema is not acceptance-equivalent to Pydantic.
Requiring defaulted properties is narrower than validation, and removing an enumerated refinement is
broader. That is why the
[canonical Proposal Schema](../../sergent/docs/framework.md#the-canonical-proposal-schema) rule
keeps the strict parse, the exact typed crossing, and the application validators as the authority.
Every failure here is raised at construction, before any provider call, and names the proposal and a
pointer into the schema. These are wiring checks, not a
[trust boundary](../../sergent/docs/trust-boundaries.md#the-trust-rule).

### The Operation Registry and the Plan Proposal envelope

`OperationRegistry` is the Python binding of the
[Operation Registry](../../sergent/docs/terminology.md#operation-registry). It receives the closed
Operation set once and derives every canonical branch eagerly, so an abstract class, a malformed
discriminator, or a duplicate call fails at construction rather than during a Run.
It is the single owner of three derived artifacts, which is why no parallel structural renderer
exists anywhere: the cached branches, the composed envelope schema, and typed decoding of a raw
envelope. Composition lifts branch definitions to one root, rewrites their local references, shares
equal same-name definitions, and fails on an unequal collision while naming both source Operations.
Registration order fixes the order of the union branches; definition names sort. Decoding fails
closed on unknown top-level keys, a script that is not a list, a script over the configured maximum,
an unknown call, and any field the exact registered class rejects. The registry holds Operation
classes, while a provider adapter downstream receives only the schema, as
[semantic rules ride the schema](../../sergent/docs/framework.md#semantic-rules-ride-the-schema)
requires.

### The model-call boundary

`ModelRequest` carries prompt messages, the caller's full provider and model selection, one settings
value, and the canonical schema. Core types the settings value as the strict base and never reads
its members, so the concrete settings shape stays in the providers package and core gains no
provider fields. The selection is opaque request data here; splitting it, finding an adapter, and
encoding the schema natively belong to that package too. Messages are system or user text, only user
messages may carry images, and an image part admits bounded base64 PNG data and nothing else.

Invoking the client returns call evidence beside one parsed JSON object. The parsed object travels
beside the response rather than inside it because the typed proposal crossing belongs to the
runtime, one boundary later. Within that evidence, usage is the sole owner of latency, token counts,
and request identity, while an attempt row keeps its own timing, status, retryability, and error and
never copies those three.

Failure evidence has one source, which is why `ModelError` is an exception rather than a record. It
carries the failure kind, message, and retryability plus the partial response when one exists, and
reads endpoint identity and attempts back out of that response; only a response-less failure keeps
those two facts privately. That shape is what lets the runtime satisfy the
[model call record](../../sergent/docs/run-record-spec.md#model-call-records) rules, including what
an interrupted await keeps, without guessing.

### Intent readers and Recipe policy

Core defines no Intent class and no Intent Proposal class, and that absence is deliberate. Under
[Intent resolution](../../sergent/docs/execution-model.md#intent-resolution) the application owns
its domain proposal and Intent types, and the runtime owns its deterministic variants, including
[pass-through](../../sergent/docs/terminology.md#pass-through); a base class here would pull one of
those owners into the foundation. Core instead reads an Intent through free readers over an opaque
value. The flow reader treats an
absent flow fact as continue, so a plain continuing Intent needs no field at all, and any value
outside the specification's two verbs raises for the runtime to contain as a structured failure. Two
more readers take a stopping Intent's terminal message and metadata when it defines them.

`SergentRecipe` makes only Intent derivation abstract. Execution Plan derivation and Patch
compilation carry the two mechanical defaults the
[framework rules](../../sergent/docs/framework.md#the-second-phase) allow. Intent and Execution Plan
validation default to accepting, which is the correct answer whenever construction already proves
the invariant. The two request builders fail loudly when a model-backed stage is reached without an
application builder, so an application implements only the builders its
[Run Kind](../../sergent/docs/terminology.md#run-kind) can reach.

Recipe configuration encodes the Run Kind without any extra core value: the exact Intent Proposal
class, an optional Operation Registry whose absence declares an Intent-Only Recipe, an optional
maximum, and the no-target error. Core declares this configuration and the runtime reads it once at
[construction time](../../sergent/docs/execution-model.md#construction-time-capture), composes every
reachable schema, and rejects a maximum declared without a registry. The matching contract on the
builders is that each receives the cached Proposal Schema as its final argument and returns that
same object on the request, because the runtime's unchanged-schema check compares object identity.

### The Run Record family

Core owns the [Run Record](../../sergent/docs/run-record-spec.md#anatomy-of-the-runrecord-object)
shapes; the runtime fills them and the record itself stays inert. `RunRecord` carries the Run
identity, the chosen model name, timing, the Scene transition, the outcome, cancellation facts, and
the steps sequence that is the Run Record Ledger, whose elements are
[Step Records](../../sergent/docs/run-record-spec.md#step-records) nesting the evidence of any model
call made inside a step. Position is the index: no step and no attempt stores its own number,
because the sequence already answers that question.

`CapturedValue` marks the best-effort projection boundary of
[captured values](../../sergent/docs/run-record-spec.md#captured-values). Its status derives from
its error instead of being stored, and only application-shaped slots are wrapped in it, so a capture
failure can never blank latency, tokens, or endpoint identity. Capture never fails a Run.

Values that carry cross-field rules are replaced whole rather than edited: a span opens and then
closes, a Scene transition opens and then commits, and the outcome is built fresh at the end.
Because the strict base revalidates on assignment, half-mutating such a value would judge it in a
transient illegal state.
Two derivations live on the owner rather than in a consumer: the usage slots of recorded calls in
step order, and a total output-token count that is known only when every part is known, never a
partial sum presented as a total.

The status vocabulary is split on purpose. The public terminal vocabulary holds the three terminal
values; the record's own vocabulary adds the open-Run value and stays private, so a caller reading a
returned result cannot receive a non-terminal status. Any change to these shapes is a specification
change first.

### The Sergent Result

`SergentResult` is the in-process return described by
[the Sergent Result structure](../../sergent/docs/run-record-spec.md#the-sergent-result-structure).
Status, error, and Scene identity are computed from the Run Record it carries rather than stored
beside it, so the two can never disagree, and the derived identity uses the committed revision when
one exists. Observer errors sit beside the Run Record and never inside it, because a terminal
observer can only fail after the record has closed.

### Identifiers and timing

The [identifier grammar](../../sergent/docs/observability.md#identifiers) has one owner here: a
minting function and an admission function, the latter optionally bounded to named prefixes. Run
Records admit only the Run prefix, traces only the Operation prefix, and Scene identity any
conforming prefix. Timing is equally small: one instant function producing the
[timestamp](../../sergent/docs/observability.md#timestamps) form, and a span whose closing timestamp
and [duration](../../sergent/docs/observability.md#durations-and-latency) must travel together or
both stay absent.
Both read the real clock and a random source, and core injects neither, so its tests assert shape
and relations rather than exact values. Run-level determinism is arranged one layer up, where the
clock and identity seams belong.

### What core deliberately leaves out

Core has no engine, no stage machine, no cancellation machinery, no observer delivery, and no
persistence; no event loop, no HTTP, no threads, no process configuration, and no credentials; no
Intent class, no Intent Proposal class, and no pass-through variant; no application policy and no
default wiring; and no provider settings shape, adapter, or model catalog, because a model name is
caller-supplied data.

### Testing patterns

Core's suite is one self-contained module per subject, importing defining submodules directly, with
no shared support module and no fixtures file. Throwaway types stand in for applications: Operation
subclasses declared inline, each restating the frozen class keyword; proposal classes extending the
strict base; and a minimal Recipe subclass that implements only Intent derivation so the inherited
defaults are the thing under test.
The Intent seam is attribute-based, so a test uses a plain local class carrying a flow and terminal
facts. There is no Intent base class to fake.

Schema and registry work carries most of the risk and most of the tests. They compare whole derived
structures against the exact expected shape, and every rejection test asserts the proposal name, the
pointer, and the reason, because those diagnostics are what a developer sees when wiring fails.
Typed dictionaries in these tests come from `typing_extensions`, which Pydantic requires on the
oldest supported Python version.
The suite contains no asynchronous test, no network access, and no protocol double. Core's seams are
the interfaces themselves, so their doubles belong to the packages that consume them, and a
structural protocol is what lets those packages write one without importing from here.

### Coding rules for changes here

Read the [core class design pattern](core-class-design-pattern.md) before adding a class or a field:
it owns the ownership table, the loss test, the field ceiling, and the coupling rules. Beyond it:

- Restate the frozen class keyword in every Operation subclass; the type checker honors only that
  form.
- Keep every interface parameter positional-only. Mark app-owned meaning crossing a seam as `Any`,
  which an override may narrow; mark a value this layer never inspects as an opaque pass-through,
  which an override may not.
- Give every public symbol a one-line docstring that states its purpose and points at the
  specification document it materializes and the knowledge artifact that explains it.
- Every public symbol needs a real consumer outside this package, or it becomes private.
- Run `just fmt`, `just test`, and `just lint` before handing the work over.
