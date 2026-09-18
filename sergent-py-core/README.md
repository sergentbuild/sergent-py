# sergent-py-core

`sergent-py-core` is the foundation package of the Sergent Python reference implementation. It
holds the values that the [Sergent Specification](../sergent/docs/KNOWLEDGE.md) names, plus the
three interfaces an application implements or supplies. It executes nothing: no Run flow, no event
loop, no provider call, no file access.

## Purpose and role

A Sergent Run carries one observation toward one committed change through a fixed sequence of
stages. Core does not perform that sequence. It names the value each stage carries and the
interface each participant implements, so every package above it shares one vocabulary instead of
agreeing on one informally.

Core sits at the bottom of a four-package stack and depends on nothing else inside it. Its only
outside dependencies are Pydantic, typing-extensions, and the Python standard library.

- `sergent-py-runtime` composes these values into the Run flow, builds the Run Record, and delivers
  observer callbacks.
- `sergent-py-providers` implements the model-call interface. It consumes only the model-call
  values and the shared primitives, and core knows nothing about any provider SDK.
- `sergent-py` re-exports the curated subset that applications import.

Applications import from `sergent_py` only. Framework packages and tests import the defining core
submodule directly, because every package initializer here is an empty marker and importing a
submodule has no side effects.

Core is not the specification. The specification teaches the concepts and owns their rules. This
package materializes them as Python objects and holds nothing conceptual of its own.

## Design philosophy and what belongs here

Core is a **vocabulary**, not a coordinator. A class earns its place by naming one specification
concept and owning the facts that concept owns. Four habits keep it that way.

- **Closed-world data.** Values reject unknown input and fail at construction, so a value admitted
  once at its boundary is trusted everywhere afterwards, as the
  [trust rule](../sergent/docs/trust-boundaries.md#the-trust-rule) requires.
- **One owner per fact.** Facts that always travel together live in one value object that every
  holder shares. Nothing stores what it can derive.
- **Specification terminology decides names.** A class is named after the concept it materializes,
  never after the mechanism it happens to use.
- **Immutability where authority is at stake.** Script steps are frozen, and a value carrying
  cross-field rules is replaced whole rather than edited in place.

Code that belongs here: specification-shaped values, the framework identifier and timing
conventions, canonical Proposal Schema derivation with its closed dialect check, the Operation
Registry, and the three interfaces.

Code that does not belong here: the Run flow and its stages, concurrency and cancellation
machinery, observer delivery, persistence, provider transport and credentials, application policy,
and default wiring. Intent and Intent Proposal classes are absent by design. An application owns
its own, and the runtime owns its deterministic variants.

## Knowledge in this package

- [Component knowledge](docs/KNOWLEDGE.md) explains the design, then walks subject by subject from
  specification concept to Python shape.
- [Core class design pattern](docs/core-class-design-pattern.md) is the standing rulebook for
  adding or changing a class or a field here.
