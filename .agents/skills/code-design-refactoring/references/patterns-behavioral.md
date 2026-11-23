# Behavioral Patterns

Communication between objects and the assignment of responsibilities. The recurring move: turn a *behavior* (a check, a request, an algorithm, a state's logic, a traversal) into a stand-alone object so it can be passed, swapped, queued, or combined. Compact entries: **Intent**, **Recognize it**, **Shape**, **Use when**, **Non-obvious**, **Trade-offs**, **Lighter form**.

---

## Chain of Responsibility
**Intent**: Pass a request along a chain of handlers, each deciding whether to process it and whether to pass it on.
**Recognize it**: A request must clear a growing series of checks or stages (auth, validation, rate limit, cache) that you want to reorder and reuse.
**Shape**: Handlers share one interface and each hold a `next`. Two flavors: a *pipeline*, where every handler acts unless one stops the request; and *first-capable-wins*, where at most one handles it (UI events bubbling up through containers, where the chain is a branch of the object tree).
**Use when**: request kinds and their order are not known in advance; handlers must run in a specific order; the set or order changes at runtime.
**Non-obvious**: Wrap request data in an object for flexibility. A request may be sent to *any* handler, not only the first. Clients must cope with a one-link chain, a request stopped midway, and a request that falls off the end unhandled.
**Trade-offs**: (+) ordering control, invokers decoupled from performers, new handlers without edits. (−) unhandled requests.
**Lighter form**: a list of functions applied with early exit; middleware stacks.

## Command
**Intent**: Turn a request into a stand-alone object so it can be passed, queued, scheduled, logged, sent elsewhere, or undone.
**Recognize it**: Many triggers (buttons, menus, shortcuts, API calls) invoke the same operations; or operations need history, scheduling, or reversal.
**Shape**: A command bundles receiver, operation, and arguments behind a parameterless `execute()`. *Senders* hold commands and are pre-configured with them by the client; they know only the command interface. *Receivers* do the actual work.
**Use when**: parameterizing objects with operations; queuing, scheduling, or remote execution (commands serialize); reversible operations.
**Non-obvious**: Undo has two implementations. *State backup* (save state before executing; Memento helps with private state; memory-hungry) or *inverse operation* (each command reverses itself; cheap but sometimes impossible). Keep commands immutable, with arguments fixed at construction.
**Trade-offs**: (+) decoupling, undo/redo, deferred execution, composite commands. (−) a whole layer between senders and receivers.
**Lighter form**: a closure capturing receiver and arguments; move to objects when you need undo, serialization, or metadata.

## Iterator
**Intent**: Traverse a collection without exposing its internal structure.
**Recognize it**: Traversal logic for a complex structure is duplicated, or tangled into business code, or several traversal orders are needed.
**Shape**: The traversal algorithm *and its state* live in an iterator object obtained from the collection, so several can run over one collection independently.
**Non-obvious**: Nearly every language has this built in (iterators, generators). Use the native protocol; the pattern is the reasoning behind it, and the guide for writing a custom one for your own tree or graph. Overkill for simple collections.

## Mediator
**Intent**: Replace a web of direct dependencies among peers with communication through one mediator.
**Recognize it**: Form or dialog elements (or services, or UI panels) reference each other directly, so none can be reused and any change ripples.
**Shape**: Components notify the mediator that something happened; the mediator decides what that means and calls the right components. Components know only the mediator *interface*.
**Use when**: types are hard to change because of tight coupling to many others; a component cannot be reused elsewhere; you are subclassing components just to vary how they collaborate (write a new mediator instead).
**Non-obvious**: Often an existing container (the dialog itself) is the natural mediator, because it already knows its children. The sender must not know who reacts; the receiver must not know who triggered it. The mediator tends to become a god object: watch its size.
**Trade-offs**: (+) interaction logic in one place, reusable components. (−) god object risk.

## Memento
**Intent**: Snapshot and restore an object's state without exposing its internals.
**Recognize it**: Undo or rollback needs copies of state, but copying from outside means exposing every field.
**Shape**: The *originator* produces and consumes its own snapshots; the *memento* is opaque and immutable; a *caretaker* stores them (usually a history stack), seeing at most metadata.
**Non-obvious**: Three implementations: a nested type (originator has full access, others none), a narrow interface for everyone else (relies on convention), or stricter encapsulation where the memento holds its originator and carries `restore` itself. Memory grows quickly if snapshots are frequent; caretakers must discard obsolete ones. Dynamic languages cannot guarantee the snapshot stays untouched. For simple objects, cloning (Prototype) may be enough.

## Observer
**Intent**: A subscription mechanism that notifies many objects about events in the object they observe.
**Recognize it**: Interested parties poll for changes, or the source broadcasts to everyone; the set of interested parties is unknown in advance or changes at runtime.
**Shape**: The *publisher* keeps a subscriber list with subscribe/unsubscribe and calls each subscriber's notification method through a common interface.
**Use when**: a change in one object requires changes in others whose set is dynamic or unknown; objects must observe only for a limited time.
**Non-obvious**: Pass context with the notification (*push*), or pass the publisher so subscribers fetch what they need (*pull*). For an existing publisher hierarchy, put the subscription logic in a helper object used by composition rather than a base class. **Notification order is not guaranteed; never rely on it.** Forgotten subscriptions keep objects alive (a classic leak), so unsubscribe deterministically. Beware cascading and re-entrant updates.
**Lighter form**: callback lists, event emitters, signals, reactive streams.

## State
**Intent**: An object changes its behavior when its internal state changes, as though it had changed class.
**Recognize it**: A state machine written as conditionals: every method begins with a switch on the current state, and adding a state means editing them all.
**Shape**: One type per state holding that state's behavior; the *context* delegates to its current state object; a transition replaces that object.
**Use when**: many states with frequently changing state-specific logic; massive conditionals on state fields; duplication across similar states (share it in an intermediate base state).
**Non-obvious**: Unlike strategies, states may know about each other and trigger transitions; whoever performs the transition becomes coupled to the concrete states it creates. State code often needs the context's private members: expose what is needed, or nest the state types. Temporary fields and helper methods often leave the context along with the conditionals. Overkill for a few rarely changing states.
**Lighter form**: a sum type of states with a transition function, or a transition table.

## Strategy
**Intent**: A family of interchangeable algorithms, each in its own unit.
**Recognize it**: One type does a job in many ways; each new variant enlarges it, edits to one risk the others; or a large conditional selects among variants of the same algorithm.
**Shape**: The *context* holds a strategy behind a common interface and delegates the job to it. The **client** chooses the strategy and passes it in; the context never needs to know the concrete ones.
**Use when**: switching algorithms at runtime; many similar types differing only in one behavior; isolating business logic from algorithmic detail; replacing a variant-selecting conditional.
**Non-obvious**: Clients must understand the differences to choose. With only a couple of rarely changing algorithms it is pure overhead. Strategies that need the context's data can receive it through a narrow interface rather than the whole context.
**Lighter form**: pass a function. Use an object when the algorithm has its own state, configuration, or several related operations.

## Template Method
**Intent**: Fix an algorithm's skeleton in a base type and let subtypes override individual steps.
**Recognize it**: Several types implement nearly the same sequence (open, extract, parse, analyze, report, close), differing in a few steps and duplicating the rest.
**Shape**: The base type's template method calls step methods in order. Steps are *abstract* (must implement), *optional* (have a default), or *hooks* (empty defaults placed around crucial steps as extension points).
**Non-obvious**: Subtypes override steps, never the template method itself (make it final where possible). A subtype that suppresses a default step can violate Liskov substitution. More steps means harder maintenance. It is static and inheritance-based; if you need runtime variation, use Strategy.
**Lighter form**: a higher-order function taking the varying steps as arguments, with defaults for optional ones.

## Visitor
**Intent**: Add operations across a hierarchy of element types without modifying those types.
**Recognize it**: A stable set of element types (syntax tree, document model, scene graph) keeps acquiring unrelated operations (export, analyze, render) that do not belong inside the elements.
**Shape**: A *visitor* has one method per concrete element type. Each element has a trivial `accept(visitor)` that calls back the method matching its own type (*double dispatch*), so the right method is chosen without conditionals. Overloading cannot do this, because overloads resolve from the declared type at compile time.
**Use when**: an operation spans all elements of a complex structure; auxiliary behavior should leave the primary types; a behavior applies to only some element types.
**Non-obvious**: Every concrete element must implement `accept` itself, even if its parent does. Visitors can accumulate state across a traversal. Every visitor must change when an element type is added, so this suits *stable* hierarchies. Visitors may lack access to private state they need. **In a language with sum types and exhaustive matching, `match` already gives this trade-off natively**; see workflow step 6 in SKILL.md.
**Lighter form**: pattern matching over a sum type.
