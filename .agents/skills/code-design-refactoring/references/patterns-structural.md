# Structural Patterns

How to assemble objects into larger structures that stay flexible. Most are one idea, an object holding another and delegating to it, distinguished by **intent** and by **what happens to the interface**. Compact entries: **Intent**, **Recognize it**, **Shape**, **Use when**, **Non-obvious**, **Trade-offs**, **Lighter form**.

---

## Adapter
**Intent**: Let objects with incompatible interfaces collaborate by translating one interface into another.
**Recognize it**: A useful third-party or legacy type expects different calls, formats, or units than your code uses, and you cannot or should not change it.
**Shape**: The adapter implements the interface *your* code expects, wraps the foreign object, and translates calls and data. The wrapped object is unaware of it.
**Use when**: reusing an existing type with the wrong interface; several existing subclasses lack common functionality that cannot be added to their parent (wrap them via their shared interface).
**Non-obvious**: Clients must depend on the target interface, never the concrete adapter, or you cannot swap adapters when the foreign API changes. Keep *only* translation in it; business logic creeping in is the common failure. The inheritance-based "class adapter" needs multiple inheritance. Sometimes simply changing the service is less work.
**Trade-offs**: (+) conversion separated from business logic, new adapters without touching clients. (−) more types.
**Lighter form**: a conversion function or a thin module of wrapper functions.

## Bridge
**Intent**: Split a type into two independent hierarchies, *abstraction* (high-level control) and *implementation* (platform work), so each evolves separately.
**Recognize it**: Variation along two independent dimensions (shape × color, UI × operating system, message × channel) producing one subclass per combination.
**Shape**: Extract one dimension into its own hierarchy; the original holds a reference to it and delegates. The abstraction offers rich operations built from the primitives the implementation interface provides.
**Use when**: dividing a monolith that contains several variants of some functionality; extending a type in orthogonal dimensions; implementations must be switchable at runtime.
**Non-obvious**: "Abstraction" and "implementation" here are *layers* (GUI over OS API, domain over infrastructure), not language keywords. Runtime switching is a side effect, not the point, and the reason it gets mistaken for Strategy. Designed up front, unlike Adapter.
**Trade-offs**: (+) platform independence, each side extensible alone. (−) pure overhead on a cohesive type with only one real dimension.

## Composite
**Intent**: Compose objects into trees and treat single objects and subtrees uniformly.
**Recognize it**: The model is naturally recursive (folders and files, nested UI, grouped shapes, orders containing boxes of products) and clients run an operation over it without caring what is inside.
**Shape**: A *component* interface shared by *leaves* (do the work) and *containers* (hold children typed as component, delegate, and combine results).
**Use when**: you need a tree structure; clients should treat simple and complex elements alike.
**Non-obvious**: Putting child-management methods on the shared interface violates Interface Segregation (they are meaningless on leaves) but lets clients build trees uniformly: a deliberate trade-off, make it consciously. A common interface for very dissimilar elements can become over-general.
**Trade-offs**: (+) recursion and polymorphism make trees convenient, new element types slot in. (−) strained common interface.
**Lighter form**: a recursive sum type (`Leaf | Node(children)`) with fold-style functions.

## Decorator
**Intent**: Attach behavior to an object dynamically by wrapping it in objects that share its interface.
**Recognize it**: Optional behaviors that must combine freely (notify by email + SMS + chat; compress + encrypt), where a subclass per combination explodes.
**Shape**: The wrapper implements the *same interface* as what it wraps and holds a reference typed as that interface, so it can wrap the core object or another wrapper. Each adds behavior before or after delegating. The client assembles the stack and holds the outermost layer.
**Use when**: behaviors must be added at runtime without breaking users of the object; inheritance is impossible (sealed types) or awkward.
**Non-obvious**: Hard to remove one wrapper from the middle of a stack; hard to make behavior independent of stacking order; the assembly code can be ugly, so hide it in a factory or builder. Decorators must stay substitutable for the component.
**Trade-offs**: (+) no subclass explosion, runtime composition, small single-purpose types. (−) the three issues above.
**Lighter form**: function composition, middleware, language-level decorators.

## Facade
**Intent**: A simple interface to a complex subsystem.
**Recognize it**: Business code must initialize many library objects, track their dependencies, and call them in the right order, coupling it to third-party internals.
**Shape**: One type exposing only what clients need, routing to the subsystem and usually managing its lifecycle. The subsystem is unaware of it.
**Use when**: you need a limited, easy entry point; you want to layer a system, with layers talking only through facades.
**Non-obvious**: It adds *no new functionality*; it only simplifies access. It tends to grow into a god object coupled to everything: split into several focused facades when it does. A subsystem upgrade should then touch only the facade.
**Lighter form**: a module exposing a few high-level functions.

## Flyweight
**Intent**: Fit far more objects in memory by sharing the state they have in common.
**Recognize it**: A *measured* memory problem from a huge number of similar objects (particles, glyphs, tiles) whose heaviest fields repeat.
**Shape**: Split state into *intrinsic* (constant, shareable) and *extrinsic* (per-context, changing). Flyweights hold only intrinsic state; small context objects hold extrinsic state plus a flyweight reference; a factory pools flyweights by intrinsic state.
**Use only when** all hold: huge object count, memory nearly exhausted, and duplicated state that can be extracted.
**Non-obvious**: Flyweights **must be immutable** because they are shared. You may be trading memory for CPU if context must be recomputed per call. The split makes code markedly harder to follow. This is an optimization: measure first.
**Lighter form**: interning, shared immutable values, structure-of-arrays layouts.

## Proxy
**Intent**: A stand-in with the same interface that controls access to another object, acting before or after forwarding.
**Recognize it**: You need lazy creation, access checks, caching, logging, or remoting around a service you cannot or should not modify, without duplicating it across clients.
**Kinds**: *virtual* (lazy initialization), *protection* (access control), *remote* (local stand-in for a network service), *logging*, *caching* (request parameters as keys), *smart reference* (release the service when no client holds it).
**Non-obvious**: A proxy typically creates and manages its service's lifecycle itself; that, and intent, is what separates it from Decorator, whose composition the client controls. If extracting a service interface is impractical, subclassing the service is the fallback. A creation method can decide whether a client gets the proxy or the real thing.
**Trade-offs**: (+) transparent to clients, works even when the service is not ready, new proxies without touching service or clients. (−) more types, added latency.
**Lighter form**: wrapper functions (memoize), language-level dynamic proxies and interceptors.
