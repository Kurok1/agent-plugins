# Markdown codebase-map format

Use this reference when initializing or structurally updating
`docs/.codebase-map`. The map is a semantic navigation graph, not a rendered
file tree and not a source-code substitute.

## Contents

- [Directory contract](#directory-contract)
- [Writing rules](#writing-rules)
- [CODEMAP index](#codemap-index)
- [Domain maps](#domain-maps)
- [Business-flow maps](#business-flow-maps)
- [Architecture maps](#architecture-maps)
- [Dependency maps](#dependency-maps)
- [Cross-links](#cross-links)
- [Incremental maintenance](#incremental-maintenance)
- [Validation checklist](#validation-checklist)

## Directory contract

Keep every durable artifact in this optional structure:

```text
docs/.codebase-map/
├── CODEMAP.md
├── domain/
│   └── <domain>.md
├── flows/
│   └── <flow>.md
├── architecture/
│   ├── overview.md
│   ├── module-boundaries.md
│   ├── data-flow.md
│   └── event-system.md
└── dependencies/
    └── <dependency>.md
```

Create only documents with current navigation value. Do not create empty
folders or placeholder maps to satisfy the shape. Use kebab-case filenames.

`CODEMAP.md` is the only required document once a map exists. Markdown is the
only durable format in this directory.

## Writing rules

### Keep one map language

Use one primary natural language for all narrative text in
`docs/.codebase-map`, including headings, table labels, descriptions, and flow
steps. Select it from an explicit user preference, otherwise the existing
`CODEMAP.md`, the current conversation, or the repository's primary
documentation, in that order. The templates below define structure only;
translate their narrative labels and example prose into the selected language.

Do not translate source paths, symbols, identifiers, commands, code blocks,
configuration keys, protocol names, API names, or established technical terms.
If an existing map mixes primary languages, normalize its narrative text while
preserving verified facts, links, and organization before completing the next
update.

### Lead with code coordinates

Prefer this one-line coordinate:

```md
- [src/order/services/order.service.ts](../../../src/order/services/order.service.ts) → `OrderService.createOrder()` — creates and persists an order.
```

Use the correct relative path from the current map document. Put the path
first, the symbol second, responsibility third, then relationships or change
impact. Use line numbers only for exceptional short-lived debugging notes,
which normally do not belong in the map.

### Record verified semantics

Derive paths, symbols, relationships, dependencies, and business rules from
current repository evidence. When evidence is incomplete, use map-language
equivalents of `Unknown` or `Unconfirmed` (for example, `未知` or `未确认` in
Chinese), or omit the claim. Never infer implementation solely from a directory
name, filename, or familiar architecture pattern.

### Optimize for code changes

Prioritize facts that answer:

- Where should an Agent start modifying this behavior?
- Where does a state transition occur?
- Which entry point reaches this service?
- Which publisher, consumer, repository, table, or external system participates?
- Which nearby tests and side effects must change together?

Omit background prose that does not narrow future source inspection.

### Keep maps stable

Prefer tables, bullets, short call chains, paths, symbols, and cross-links.
Avoid file-tree copies, one sentence for every file, source excerpts, exact line
numbers, commit hashes, file counts, and transient debugging observations.

## CODEMAP index

Keep `CODEMAP.md` short enough to load at session start. It should route an
Agent to one or two detailed maps or directly to an important source entry.

Use this adaptable template:

```md
# Code Map

> Evidence-backed navigation index. Verify paths and symbols against current source before editing.

## Repository Entry Points

| Area | Code coordinate | Responsibility |
|---|---|---|
| HTTP API | [src/server.ts](../../src/server.ts) → `startServer()` | Builds and starts the API runtime. |

## Domain Concepts

- [Order](domain/order.md) — order lifecycle, persistence, and events.

## Business Flows

- [Payment callback](flows/payment-callback.md) — verifies a provider callback and marks an order paid.

## Architecture

- [Overview](architecture/overview.md)
- [Module boundaries](architecture/module-boundaries.md)

## Dependencies

- [Stripe](dependencies/stripe.md) — payment provider used by checkout and callbacks.
```

Keep only meaningful sections. Repository entry points may include runtime
bootstrap, routes, workers, scheduled jobs, package entry files, test entry
points, and major configuration roots.

## Domain maps

Organize domains by business semantics rather than mirroring directories. A
domain may span backend, frontend, persistence, events, and tests.

Use relevant parts of this template:

```md
# Order

## Concept

Represents the customer purchase lifecycle from creation through fulfillment or cancellation.

## Primary Source

- [src/order/domain/order.ts](../../../src/order/domain/order.ts) → `Order` — aggregate and invariants.

## Core Symbols

- [src/order/services/order.service.ts](../../../src/order/services/order.service.ts) → `OrderService` — application operations.
- [src/order/domain/order-state-machine.ts](../../../src/order/domain/order-state-machine.ts) → `transitionOrderStatus()` — validates state transitions.

## Business Rules

- `pending → paid` is performed only after verified payment success.
- `shipped → cancelled` is rejected.

## Commands / Operations

### Create order

- [src/order/services/order.service.ts](../../../src/order/services/order.service.ts) → `OrderService.createOrder()`

## Persistence

- [src/order/repositories/order.repository.ts](../../../src/order/repositories/order.repository.ts) → `OrderRepository.save()` — writes order state.

## Events

- [src/order/events/order-paid.ts](../../../src/order/events/order-paid.ts) → `OrderPaid` — published after the paid transition commits.

## Tests

- [tests/order/order-state-machine.test.ts](../../../tests/order/order-state-machine.test.ts) → `describe("transitionOrderStatus")`

## Related Flows

- [Payment callback](../flows/payment-callback.md)

## Related Domains

- [Payment](payment.md)
```

Use `Primary Source` for canonical ownership rather than listing every file that
mentions the concept. Record business rules only when code or tests confirm
them.

## Business-flow maps

Use a Flow for important behavior crossing controllers, services, domains,
repositories, events, jobs, or external systems. Trace from a real runtime
entry point rather than an assumed sequence.

Use this adaptable template:

```md
# Payment Callback

## Purpose

Verify a payment-provider callback, update payment and order state, and publish downstream events.

## Execution Path

1. [src/payment/http/payment-webhook.controller.ts](../../../src/payment/http/payment-webhook.controller.ts) → `PaymentWebhookController.handle()` — receives the callback.
2. [src/payment/providers/stripe/verify-webhook.ts](../../../src/payment/providers/stripe/verify-webhook.ts) → `verifyWebhook()` — verifies authenticity.
3. [src/payment/services/payment.service.ts](../../../src/payment/services/payment.service.ts) → `PaymentService.handleWebhook()` — dispatches provider events.
4. [src/order/services/order.service.ts](../../../src/order/services/order.service.ts) → `OrderService.markPaid()` — changes order state.

## State Changes

- Payment: `pending → succeeded`
- Order: `pending → paid`

## Side Effects

- Publishes `PaymentSucceeded` and `OrderPaid`.
- Persists payment and order updates.

## Consumers

- [src/notification/handlers/order-paid.handler.ts](../../../src/notification/handlers/order-paid.handler.ts) → `OrderPaidHandler.handle()` — sends confirmation.

## Tests

- [tests/payment/payment-webhook.test.ts](../../../tests/payment/payment-webhook.test.ts) → `describe("payment webhook")`

## Related Maps

- [Order](../domain/order.md)
- [Payment](../domain/payment.md)
- [Stripe](../dependencies/stripe.md)

## Change Impact

- Recheck signature verification, idempotency, transaction boundaries, event publication, and retry behavior.
```

Include failure, retry, async, and transaction behavior when it materially
changes how the flow must be modified or debugged.

## Architecture maps

Create architecture documents only for boundaries that help locate code.

### `overview.md`

Summarize applications, services, packages, major modules, runtime boundaries,
and repository shape. Link each important area to its actual entry point or
module root.

### `module-boundaries.md`

Record responsibility, ownership, public interface, allowed dependency
direction, prohibited coupling, and cross-module communication. Prefer a table:

```md
| Module | Responsibility | Public interface | Depends on |
|---|---|---|---|
| Order | Lifecycle and fulfillment state | `OrderService`, order events | Payment, inventory |
```

### `data-flow.md`

Record data transformations and persistence boundaries across layers or
services. Link major transformations to symbols.

### `event-system.md`

Record event definitions, publishers, consumers, transport, registration, and
retry or dead-letter behavior. Link to related Flow and Domain maps.

## Dependency maps

Document only infrastructure and external dependencies that materially affect
runtime behavior or code changes. Do not create a map for every ordinary
library.

Use this adaptable template:

```md
# Redis

## Purpose

Provides caching and distributed locking for selected workflows.

## Client Initialization

- [src/infrastructure/redis/client.ts](../../../src/infrastructure/redis/client.ts) → `createRedisClient()`

## Configuration

- [src/config/redis.ts](../../../src/config/redis.ts) → `redisConfig`
- Environment: `REDIS_URL`

## Used By

- [src/order/services/order-lock.service.ts](../../../src/order/services/order-lock.service.ts) → `OrderLockService` — prevents duplicate order transitions.

## Failure Behavior

- Lock acquisition failure aborts the protected transition.
- Retry policy: `Unconfirmed`.

## Related Flows

- [Checkout](../flows/checkout.md)
```

Distinguish repository-internal dependencies, infrastructure such as databases
or queues, and external services such as payment or messaging providers.

## Cross-links

Use clickable relative Markdown links:

- `CODEMAP.md` links every primary Domain, Flow, Architecture, and Dependency
  map.
- Domain maps link related Flows and Domains.
- Flow maps link participating Domains, Dependencies, Architecture, and tests.
- Dependency maps link their primary Domain and Flow consumers.
- Architecture maps link the modules and flows whose boundaries they explain.

Every detailed map must be reachable from `CODEMAP.md`. Prefer a useful
navigation edge over repeating the linked document’s content.

## Incremental maintenance

When a map already exists:

1. Read the index and affected maps before editing.
2. Check referenced paths and symbols touched by current evidence.
3. Add only newly verified, durable navigation knowledge.
4. Delete invalid references and repair renamed or moved coordinates.
5. Preserve stable organization and unrelated valid content.
6. Overwrite or remove stale content even when a human authored it, but only
   when current repository evidence proves the correction.
7. Preserve unresolved human/Agent conflicts with the map-language equivalent
   of `Unconfirmed` rather than selecting a side without evidence.
8. Avoid whole-document rewrites when a local patch expresses the change.
9. Return `NO_UPDATE` without touching Markdown when nothing adds navigation
   value.

The target is a long-lived, low-noise index rather than a newly generated set
of project documentation after every session.

## Validation checklist

After every update, confirm:

- [ ] `CODEMAP.md` is concise and routes common modification requests.
- [ ] Major recorded entry points are real.
- [ ] Changed paths exist, except references intentionally documenting verified deletion.
- [ ] Changed symbols exist in current source.
- [ ] Flow order follows actual calls or events.
- [ ] State changes, persistence, side effects, and failure behavior are evidence-backed.
- [ ] Local Markdown links resolve.
- [ ] Detailed map documents are reachable from `CODEMAP.md`.
- [ ] Domain, Flow, and Dependency cross-links are useful and consistent.
- [ ] All map documents use one primary natural language, apart from code identifiers and established technical terms.
- [ ] No graph database, JSON knowledge store, source copy, transcript, secret, or unstable statistic was added.
- [ ] A typical request reaches core source after `CODEMAP.md` plus one or two map documents.

Run `scripts/codebase_map.py validate --project-root <project-root>` for the
deterministic subset. Resolve all errors and manually inspect symbol warnings.
