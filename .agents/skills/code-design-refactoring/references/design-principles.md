# Design Principles

Principles explain *why* some structures survive change better than others. Patterns are mostly these principles applied to a specific recurring problem. Terminology here is class-based; see the translation table in SKILL.md for other paradigms.

## Contents
1. What good design optimizes for
2. Foundations: abstraction, encapsulation, inheritance, polymorphism
3. Relationships between objects (weakest to strongest)
4. Three core principles
5. SOLID
6. Supporting heuristics
7. Pragmatism

---

## 1. What good design optimizes for

**Reuse.** Reusing code cuts cost and time, but only if the code can survive a new context. Tight coupling, dependence on concrete types, and hard-coded operations all block reuse. There are three levels of reuse: individual types and libraries (lowest level, lowest risk), frameworks (highest level, big investment, "don't call us, we'll call you"), and patterns in between, which reuse *design ideas* rather than code and carry far less risk than building a framework.

**Extensibility.** Change is the one certainty. It arrives for three reasons: you understand the problem better once you have built a first version; the environment shifts underneath you (platforms, dependencies, regulations); and success moves the goalposts because users now see what else is possible. Design so that likely changes are cheap, without trying to predict every change.

Both goals are bought with added complexity. The craft is spending that complexity only where change or reuse is actually expected.

## 2. Foundations

- **Abstraction**: a model of a real thing limited to one context, accurate about what matters there and silent about everything else. The same real-world entity is modeled differently in different applications.
- **Encapsulation**: hiding state and behavior behind a limited public surface. Callers depend on the surface; internals stay free to change. Interfaces/protocols are the formal version: a contract about behavior only.
- **Inheritance**: building a new type on an existing one. Main benefit is reuse. Main cost: the subtype is locked into the parent's entire interface and must honor all of it, including abstract members that may not suit it. Most languages allow one parent but many interfaces.
- **Polymorphism**: calling an operation through a general type and having the actual variant's implementation run, without the caller knowing which variant it holds. This is what replaces type-checking conditionals.

## 3. Relationships between objects

From weakest to strongest coupling. Each level includes the ones above it.

| Relation | Meaning | Typical form |
|---|---|---|
| **Dependency** | A change to B's definition may force a change in A | A mentions B's name: parameter types, constructor calls |
| **Association** | A has lasting access to B and interacts with it | A holds B in a field (or a method always returns it) |
| **Aggregation** | A is a container/whole for Bs, but B can exist independently and belong to several containers | collection fields |
| **Composition** | A is made of Bs and controls their life cycle; B has no meaning outside A | owned parts created/destroyed by A |
| **Implementation** | A fulfills contract B; an A can be used wherever a B is expected | implements/conforms |
| **Inheritance** | A takes on B's interface *and* implementation and may extend it | extends |

Practical uses of this ladder:
- Depending on an interface instead of a concrete type *weakens* a dependency.
- "Composition over inheritance" in everyday speech covers both composition and aggregation: any "has-a" delegation.
- Bidirectional associations are legitimate but costly: both sides must be kept in sync, neither can be reused alone, and in some runtimes mutual references complicate memory reclamation. Prefer one-way links unless the reverse lookup is genuinely needed and expensive to compute.

## 4. Three core principles

### Encapsulate what varies
Find the aspects likely to change and wall them off from the stable parts. Think watertight compartments in a ship: damage floods one compartment, not the hull.

- *At function level*: pull the volatile calculation (say, a tax or pricing rule) out of the larger routine into its own function. The caller states *what* it wants; the *how* lives in one place.
- *At type level*: when the volatile logic grows its own helpers and data, move it to its own type and have the original delegate to it.

This is the motive behind Extract Method, Extract Class, Strategy, State, Bridge, and most other patterns.

### Program to an interface, not an implementation
Depend on abstractions rather than concrete types. A design is flexible if it can be extended without breaking existing code.

Procedure for loosening a collaboration between two types:
1. Work out exactly which operations the client needs from the other object.
2. Declare those in a new interface.
3. Have the concrete dependency implement it.
4. Make the client depend on the interface only.

The immediate result is *more* code and no visible benefit. Do it where an extension point is plausible (others will plug in variants, or you expect alternative implementations, or you need a test seam), not everywhere. The remaining coupling is usually object *creation*; pushing that into an overridable creation step is exactly Factory Method.

### Favor composition over inheritance
Inheritance is the most obvious reuse tool and the one with the most delayed costs:

- A subclass cannot shrink the parent's interface; it must implement everything, relevant or not.
- Overrides must stay behavior-compatible with the parent, because subclass instances flow into code written for the parent.
- The subclass sees parent internals, weakening encapsulation (and parents sometimes start accommodating children).
- Subclasses are tightly coupled to the parent: any parent change can break them.
- Inheritance varies along one axis only. With two or more independent axes (e.g. vehicle kind x engine kind x control kind) you get a combinatorial explosion of subclasses and parallel hierarchies.

Composition fixes this: give the object a reference to a helper for each axis and delegate. Each axis gets its own small hierarchy, combinations are assembled rather than subclassed, and a helper can be swapped at runtime. Inheritance says "is a"; composition says "has a".

Inheritance remains appropriate when the subtype truly is a behavioral extension of the parent and passes the substitution checklist below.

## 5. SOLID

### S - Single Responsibility
*A unit should have one reason to change.*

Goal: manage complexity. Small programs do not need this; growing ones do. When a type does several things, you must touch it whenever any one of them changes, and risk breaking the others each time. Symptom: you cannot keep the type in your head, or edits for unrelated reasons keep landing in it (Divergent Change). Remedy: Extract Class along the line between reasons (e.g. separate "managing employee data" from "formatting timesheet reports").

### O - Open/Closed
*Open for extension, closed for modification.*

Goal: adding features should not break code that already works. "Closed" means its interface is stable and others rely on it; "open" means new behavior can still be attached (subtype, plug in a strategy, register a handler). Typical move: replace a hard-coded set of variants inside a type with an interface plus one implementation per variant, so a new variant is a new file, not an edit.

Limit: this is about new features. If the existing code has a bug, fix it in place; do not paper over it in a subclass.

### L - Liskov Substitution
*Anything that works with the parent type must keep working when handed a subtype.*

Critical for libraries and frameworks, where you cannot see or fix the client code. Unlike the other principles, this one has a concrete checklist for an overriding method:

1. **Parameters**: accept the same types or *more general* ones, never narrower.
2. **Return value**: return the same type or a *more specific* one, never broader (in dynamic languages: never a different kind of value).
3. **Errors**: raise only the error types the parent is known to raise, or subtypes of them; callers' handlers are written for those.
4. **Preconditions**: do not strengthen. If the parent accepts negative numbers, so must you.
5. **Postconditions**: do not weaken. If the parent guarantees it closes its connections, so must you.
6. **Invariants**: preserve everything that must always be true of the parent. This is the easiest to break because invariants are often implicit (living in tests or client assumptions). Safest extension style: *add* fields and methods; avoid altering inherited ones.
7. **Parent's private state**: do not modify it, even where reflection or lack of enforcement makes that possible.

Classic violation: a subtype that overrides an operation to throw "not supported" (a read-only document that cannot save). Clients must then type-check before calling, which also breaks Open/Closed. Fix by inverting the hierarchy: make the *less capable* type the base and let the more capable one extend it with the extra operation.

### I - Interface Segregation
*Clients should not be forced to depend on methods they do not use.*

Split "fat" interfaces into narrow, role-based ones. Implementers then provide only what makes sense for them (no stub methods), and a change to one role does not ripple to clients of another. A single type can implement several narrow interfaces. Classic trigger: an interface designed around one full-featured provider that later providers can only partially satisfy.

Limit: do not shred an already-focused interface. More interfaces means more complexity.

### D - Dependency Inversion
*High-level policy should not depend on low-level detail; both depend on abstractions, and details depend on abstractions.*

Low-level: disk, network, database, third-party APIs. High-level: business logic that orchestrates them. Building bottom-up tends to make business logic depend on primitives. To invert:
1. Describe the low-level operations the business logic needs as an interface **in business terms** (`openReport(file)`, not `openFile / readBytes / closeFile`). This interface belongs to the high level.
2. Make the high-level code depend on that interface.
3. Make low-level code implement it. The dependency arrow now points from detail to policy.

Payoff: swap or upgrade infrastructure without touching business logic; pairs naturally with Open/Closed.

## 6. Supporting heuristics

These recur throughout the smell and technique catalogs:

- **Things that change together belong together.** Put data next to the functions that use it; put a field where most of its users are.
- **Tell, don't ask.** Rather than querying an object's state and acting on it from outside, ask the object to do the thing. This is what polymorphism and Move Method accomplish.
- **Command-query separation.** A function should either return information or change visible state, not both. Queries without side effects can be called freely, reordered, and used in conditions. Invisible caching inside a query does not count as a side effect. Exception: operations where the result of the command is naturally needed (e.g. "rows deleted").
- **One variable, one purpose.** Reusing a variable or reassigning a parameter for different meanings hides bugs and blocks extraction.
- **The best comment is a good name.** If a block needs a comment to explain *what* it does, extract it and use the comment as the name. Reserve comments for *why*, and for irreducibly complex algorithms.
- **Least knowledge.** A client that navigates `a.b().c()` depends on the whole path. Hide the navigation, but not so aggressively that every type becomes a forwarding shell.
- **Values vs. references.** *Reference objects* stand for one real-world entity and must be unique (customer, order); *value objects* are defined by their content, should be immutable, and may be freely duplicated (date, money, range). Choosing wrongly causes either stale copies or needless lifecycle management. Values are much simpler, especially in concurrent or distributed settings.
- **Make assumptions executable.** Where code silently assumes a condition, state it as an assertion: living documentation that fails fast. Use real error handling, not assertions, for conditions that users or the environment can cause.
- **Separate domain from presentation.** Business data and rules must not live inside UI code; otherwise a second interface means duplication.
- **YAGNI.** Parameters, hooks, and abstract layers added "just in case" are a smell (Speculative Generality). Add them when the need is real. Exception: frameworks and libraries legitimately ship extension points they do not use themselves.

## 7. Pragmatism

Applied mechanically, these principles do more harm than good. Each one trades simplicity for flexibility; no successful product applies all of them everywhere. Use them as lenses when something already hurts or a specific change is foreseeable, keep a balance between clarity and flexibility, and be ready to reverse an abstraction that did not pay off (Inline Class, Collapse Hierarchy, Remove Middle Man exist for exactly that).
