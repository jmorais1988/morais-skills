# Choosing, Distinguishing, and Combining Patterns

Many patterns share a structure (one object holding another and delegating to it) yet solve different problems. **A pattern is defined by its intent, not by its class diagram.** Naming the pattern also tells other developers which problem you were solving, so pick the name that matches the problem.

## Contents
1. Before reaching for a pattern
2. Look-alikes, disentangled
3. From smell or refactoring to pattern
4. Principles and the patterns that embody them
5. Patterns that work well together
6. How designs evolve

---

## 1. Before reaching for a pattern

Ask in this order:
1. **Is there real pressure?** A concrete change that is hard to make, duplication that keeps biting, a test seam that is needed now. If the pressure is hypothetical, wait (Speculative Generality).
2. **Would a simple refactoring do?** Extract Method, Extract Class, or a parameter often relieves the pressure with far less machinery.
3. **Does the language already provide it?** Iterators, first-class functions, decorators, events, module-level instances, pattern matching.
4. **Does the problem have the pattern's shape?** Check the entry's "Use when" list. If you have to squint, it is the wrong pattern.
5. **What does it cost?** Every pattern adds types and indirection. Recurring warnings from the catalog: two rarely changing algorithms do not need Strategy; a small, stable state machine does not need State; simple collections do not need a custom Iterator; a cohesive type does not need Bridge; Flyweight is only for a measured memory problem; Singleton is a last resort.

## 2. Look-alikes, disentangled

### The wrappers: Adapter vs. Decorator vs. Proxy vs. Facade

| Pattern | Interface seen by the client | Purpose | Wraps |
|---|---|---|---|
| Adapter | A **different** one | Make an incompatible type usable | Usually one object |
| Decorator | The **same, or extended** | Add responsibilities; stackable recursively | One object, which may itself be a decorator |
| Proxy | The **same** | Control access: lazy loading, caching, permissions, logging, remoting | One object, whose lifecycle it usually manages itself |
| Facade | A **new, simplified** one | Hide the complexity of a whole subsystem | Many objects |

- Decorator vs. Proxy: the structure is nearly identical. A proxy typically creates and manages its service on its own; a decorator's composition is always decided by the client.
- Adapter vs. Facade: an adapter makes an *existing* interface usable; a facade defines a *new* one. Adapters usually wrap a single object; facades front an entire subsystem.
- Facade vs. Proxy: both buffer a complex entity and may initialize it, but a proxy shares its service's interface and is interchangeable with it.
- Adapter does not support recursive composition; Decorator does.

### Bridge vs. Adapter
Bridge is designed **up front**, so that parts of an application can be developed independently. Adapter is applied **after the fact**, to make existing incompatible types cooperate.

### Bridge vs. State vs. Strategy (and, to a degree, Adapter)
All are composition and delegation.
- **Strategy**: interchangeable ways of doing *one job*. Strategies are independent and unaware of each other; the client chooses.
- **State**: an extension of Strategy in which the helper objects represent *states*, may know about one another, and may *trigger transitions* in the context.
- **Bridge**: a structural split of *two whole hierarchies* (high-level abstraction and platform-level implementation). Being able to swap the implementation at runtime is a side effect, not the point.

### Strategy vs. Template Method
- Template Method relies on **inheritance**: it varies parts of an algorithm by overriding steps. It is static and operates at the type level.
- Strategy relies on **composition**: it swaps whole behaviors by supplying a different object. It is dynamic and operates at the object level.
Prefer Strategy when you need runtime switching or want to avoid coupling to a hierarchy. Prefer Template Method when the skeleton is fixed and only a few steps differ.

### Strategy vs. Command
Both parameterize an object with some action.
- **Command** converts *any operation* into an object whose fields are its arguments, so that it can be deferred, queued, stored in a history, sent elsewhere, or undone.
- **Strategy** describes *different ways of doing the same thing* and swaps them inside one context.

### Decorator vs. Strategy
A decorator changes the **skin** of an object: behavior is wrapped around the outside. A strategy changes the **guts**: behavior is replaced on the inside.

### Decorator vs. Composite
Both rely on recursive composition. A decorator has exactly **one** child and *adds responsibilities* to it. A composite has **many** children and *aggregates* their results. They cooperate well: a decorator can extend a specific node within a composite tree.

### Decorator vs. Chain of Responsibility
The class structure is nearly the same. CoR handlers perform arbitrary, mutually independent operations and **may stop the request**. Decorators extend behavior while staying consistent with the base interface and **are not supposed to break the flow**.

### Four ways to connect senders and receivers

| Pattern | Connection |
|---|---|
| Chain of Responsibility | The request travels down a runtime-assembled line of candidate receivers, stopping when one of them takes it |
| Command | A unidirectional link from sender to receiver, with the request itself reified as an object |
| Mediator | No direct links at all; every component talks to a central mediator |
| Observer | Receivers subscribe and unsubscribe dynamically |

### Mediator vs. Observer
The goals differ. Mediator **eliminates mutual dependencies** among a set of components by making them all depend on one object. Observer **establishes dynamic one-way connections** in which some objects act as subordinates of others. A popular Mediator *implementation* uses Observer (the mediator publishes events and the components subscribe), which makes the two look alike. A mediator that is permanently wired to its components is still a Mediator. If *every* component becomes a publisher, there is no central mediator left, only a distributed web of observers.

### Facade vs. Mediator
Both organize collaboration among many tightly coupled types. A facade adds **no new functionality**; the subsystem is unaware of it, and its objects still talk to each other directly. A mediator **centralizes** communication; components know only the mediator and do not talk directly.

### Abstract Factory vs. Builder
Abstract Factory produces **families** of related objects and returns each product **immediately**. Builder assembles **one complex object step by step**, allowing extra construction steps before the product is fetched.

### Abstract Factory vs. Facade
When all you need to hide from client code is *how subsystem objects get created*, an Abstract Factory can stand in for a Facade.

### Factory Method vs. Prototype
Factory Method is based on inheritance (one creator subclass per product) but needs no initialization step. Prototype avoids inheritance and its drawbacks but requires the possibly complicated initialization, or copying, of the clone.

### Factory Method vs. Template Method
Factory Method is a specialization of Template Method, where the overridable step is "create the object". A factory method frequently appears as one step inside a larger template method.

### Flyweight vs. Singleton
A singleton has exactly one instance and may be mutable. Flyweights come in many instances, one per distinct intrinsic state, and must be immutable.

### Flyweight vs. Facade
Flyweight is about making **lots of small objects**; Facade is about making **one object that stands for an entire subsystem**.

### Memento vs. Prototype
For undo, cloning the whole object with Prototype can be a simpler alternative to Memento, provided the object is fairly simple and has no links to external resources, or those links are easy to re-establish.

### Visitor vs. Command
Visitor can be regarded as a more powerful Command: its objects execute operations over many objects of *different* types.

### Polymorphism vs. branching vs. Visitor: which axis changes?
With several variants and several operations, every structure makes one axis cheap and the other costly. Branching over a closed set (switch, or pattern matching on a sum type) makes new *operations* cheap and new *variants* costly. Polymorphism makes new *variants* cheap and new *operations* costly, since every implementation must gain the method. Visitor buys the branching trade-off (cheap operations, costly variants) in languages that cannot express a closed set of variants natively, at the price of an `accept` method per element and double dispatch. So in a language with sum types and exhaustiveness checking, reaching for Visitor usually recreates what `match` already provides; a visitor-like trait remains useful there mainly for sharing one *traversal* across many operations. Decide from the codebase's real history of change, and revisit if that history shifts. An open set of variants (third-party plugins) always requires the polymorphic form.

## 3. From smell or refactoring to pattern

| Smell or situation | Refactoring route | Pattern it arrives at |
|---|---|---|
| Switch on a type code repeated in several places | Replace Type Code with Subclasses / State-Strategy, then Replace Conditional with Polymorphism | State, Strategy |
| State-machine conditionals in every method | Extract the code for each state | State |
| Massive conditional selecting a variant of one algorithm | Extract each variant behind a common interface | Strategy |
| Subclasses with the same steps but different details | Form Template Method | Template Method |
| Subclass explosion across two dimensions; Parallel Inheritance Hierarchies | Replace Inheritance with Delegation, extracting one dimension | Bridge, Strategy |
| Subclass explosion from optional, combinable features | Turn each feature into a wrapper | Decorator |
| Refused Bequest; inheritance used purely for reuse | Replace Inheritance with Delegation | Strategy-like delegate |
| Null checks scattered everywhere | Introduce Null Object | Null Object (a do-nothing Strategy) |
| Constructor must choose a subtype or return a cached instance | Replace Constructor with Factory Method | Factory Method, static creation method |
| Telescoping constructor; very long parameter list for construction | Introduce Parameter Object; extract the construction logic | Builder |
| Cluster of creation methods obscuring a type's purpose | Extract Class | Abstract Factory |
| Incomplete Library Class; Alternative Classes with Different Interfaces in code you do not own | Introduce Local Extension (wrapper) | Adapter, Decorator |
| Domain data trapped inside UI classes | Duplicate Observed Data | Observer |
| Inappropriate Intimacy among many peers | Extract the interaction logic into one place | Mediator |
| Client coupled to a subsystem's internals; Message Chains into a library | Hide Delegate at subsystem scale | Facade |
| Feature Envy deliberately kept separate from the data | (leave as is; it is intentional) | Strategy, Visitor |
| Auxiliary operations cluttering a stable hierarchy | Move each behavior out into an external operation type | Visitor |
| Traversal code duplicated or tangled with business logic | Extract the traversal | Iterator |
| Undo that reaches into private state | Let the owner of the state produce the snapshot | Memento (+ Command) |
| Middle Man | Check first: is it a deliberate Proxy, Decorator, Facade, or Adapter? | If so, keep it |

## 4. Principles and the patterns that embody them

| Principle | Patterns that apply it most directly |
|---|---|
| Encapsulate what varies | Strategy, State, Bridge, Factory Method, Template Method, Iterator |
| Program to an interface | Every pattern; most visibly Factory Method, Abstract Factory, Adapter, Observer |
| Composition over inheritance | Strategy, State, Bridge, Decorator, Composite, Proxy, Adapter (object form) |
| Single Responsibility | Builder, Facade, Iterator, Command, Mediator, Visitor, Adapter. *Counter-example*: Singleton does two jobs |
| Open/Closed | Strategy, State, Decorator, Observer, Chain of Responsibility, Command, Visitor (for new operations), Factory Method and Abstract Factory (for new products and variants) |
| Liskov Substitution | At risk in Template Method when a subtype suppresses a default step; must be preserved by any Decorator or Proxy for it to remain interchangeable |
| Interface Segregation | Knowingly bent by Composite when child-management methods sit on the shared component interface |
| Dependency Inversion | Bridge, Abstract Factory, Strategy, Observer |

## 5. Patterns that work well together

- **Abstract Factory** is frequently built from **Factory Methods**; its methods can alternatively be composed using **Prototype**.
- **Abstract Factory + Bridge**: when certain abstractions only work with certain implementations, the factory encapsulates those pairings and hides them from client code.
- **Builder + Composite**: building steps can run recursively to assemble a tree.
- **Builder + Bridge**: the director plays the abstraction role, and the builders act as implementations.
- **Composite + Iterator**: traverse the tree. **Composite + Visitor**: run an operation over the whole tree. **Composite + Flyweight**: share leaf nodes to save memory. **Composite + Chain of Responsibility**: a leaf passes a request up through its chain of parents. **Composite or Decorator + Prototype**: clone complex structures instead of rebuilding them.
- **Command + Memento**: undo, where the command performs the operation and the memento holds the state from just before. **Command + Prototype**: keep copies of commands in the history.
- **Chain of Responsibility + Command**: handlers implemented as commands, executing different operations over the same context; or the request itself is a command executed in a series of different contexts.
- **Iterator + Factory Method**: collection subtypes return their own compatible iterator types. **Iterator + Memento**: capture the iteration state and roll it back. **Iterator + Visitor**: traverse a complex structure and apply an operation to elements of differing types.
- **Mediator implemented via Observer**: see section 2.
- **Facade as Singleton**: one facade object is usually enough. Abstract Factories, Builders, and Prototype registries can also be singletons.
- **Proxy + a creation method**: a factory decides whether the client receives the proxy or the real service.

## 6. How designs evolve

- Creation logic tends to start as **Factory Method** (the least complicated option, customized by subclassing) and to evolve toward **Abstract Factory**, **Prototype**, or **Builder** as more flexibility is demanded.
- Variation tends to start as a **conditional**, becomes a **Strategy** or **State** when the variants multiply or change often, and becomes a **Bridge** once a second independent dimension appears.
- Cross-object notification tends to start as **direct calls**, becomes **Observer** once the set of listeners varies, and becomes **Mediator** when the interactions among peers turn into a web.
- Evolution also runs **backwards**. When the variants die off, fold the pattern away again: Inline Class, Collapse Hierarchy, Replace Subclass with Fields, Remove Middle Man. Removing a pattern that no longer earns its keep is as legitimate a refactoring as introducing one.
