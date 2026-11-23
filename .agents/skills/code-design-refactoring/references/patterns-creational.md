# Creational Patterns

Ways of creating objects that keep the rest of the code decoupled from concrete types. Entries are deliberately compact: **Intent**, **Recognize it**, **Shape**, **Use when**, **Non-obvious**, **Trade-offs**, **Lighter form**. For look-alikes see `pattern-selection.md`.

Designs typically start with Factory Method (simplest, customized by subclassing) and evolve toward Abstract Factory, Prototype, or Builder as more flexibility is needed.

"Factory" is an overloaded word: any creating function, a *static creation method* (named alternative to a constructor), a *simple factory* (one function with a conditional), or the two patterns below. Say which you mean.

---

## Factory Method
**Intent**: Make the creation step an overridable method so subtypes decide which concrete product is built.
**Recognize it**: Core logic welded to one concrete type; supporting a second would scatter type conditionals through it.
**Shape**: A *creator* holds business logic that *uses* products and calls its own factory method to get them; *concrete creators* override that method. All products share one interface, which is the method's return type.
**Use when**: exact product types are unknown up front or will grow; library users must be able to substitute their own components; you want to return pooled or cached instances (a constructor cannot, a method can).
**Non-obvious**: Creating products is *not* the creator's main job; the method exists to decouple the creator's real logic from concrete types. Introduce it by replacing constructor calls one by one; a temporary switch inside the base method is a normal intermediate state. With too many products for one creator each, keep a parameter so one creator chooses among a few.
**Trade-offs**: (+) decoupling, creation in one place, new products without edits. (−) a parallel hierarchy of creators; cheapest when that hierarchy already exists.
**Lighter form**: inject a creation function, or a registry from key to constructor.

## Abstract Factory
**Intent**: Create families of related objects without naming concrete types, guaranteeing that objects used together match.
**Recognize it**: A matrix of product *kinds* × *variants* (widgets per OS, furniture per style) where mixing variants is a bug.
**Shape**: One interface per product kind; an *abstract factory* with one creation method per kind, each returning the abstract type; one *concrete factory* per variant. The concrete factory is chosen once at startup from configuration and passed to whatever creates products.
**Use when**: code must work with several product families without depending on their classes; a type has accumulated a cluster of factory methods that blur its purpose.
**Non-obvious**: Adding a *variant* is cheap (one new factory); adding a *kind* changes the interface and every factory.
**Trade-offs**: (+) compatible products, decoupling. (−) many interfaces and types.
**Lighter form**: a record or module of constructor functions per variant.

## Builder
**Intent**: Construct a complex object step by step, so one process can yield different configurations or representations.
**Recognize it**: A telescoping constructor with a tail of mostly unused parameters, or a subclass per combination of options.
**Shape**: A *builder* exposes construction steps; *concrete builders* implement them for different representations; an optional *director* encodes reusable step sequences. The result is fetched from the builder.
**Use when**: eliminating a telescoping constructor; building different representations by similar steps; constructing Composite trees (steps can be deferred or recursive).
**Non-obvious**: Products of different builders need not share an interface (one builds a car, another its manual), which is why the fetch method lives on the concrete builder, not the interface. Only needed steps are called. The unfinished product is never exposed. It only applies if you can define construction steps common to all representations.
**Trade-offs**: (+) stepwise construction, reuse of construction code, construction separated from business logic. (−) several new types.
**Lighter form**: named/default arguments, an options record, or fluent chaining often solve the constructor problem alone. Use the full pattern for multiple representations, reusable recipes, or validity rules that only hold once building is complete.

## Prototype
**Intent**: Create objects by copying existing ones without depending on their concrete types.
**Recognize it**: Copying from outside fails because state is private and you hold only an interface; or an object needs laborious configuration with a few common presets.
**Shape**: A `clone` operation on the object itself; optionally a *registry* of pre-configured prototypes to look up and clone.
**Use when**: code must copy objects handed to it through an interface; you want to replace subclasses that differ only in initialization with cloned presets.
**Non-obvious**: Every subtype must override `clone` using its *own* type, or clones come out as the parent. A copy-constructor that chains to the parent's is the safest implementation, since it also copies private parent state and returns a fully formed object. Deep-copying graphs with circular references is the hard part. Always state whether a copy is shallow or deep.
**Trade-offs**: (+) no coupling to concrete types, less repeated initialization, alternative to inheritance for presets. (−) tricky for complex graphs.
**Lighter form**: built-in copy protocols, record "with" updates, or immutable values that need no copying.

## Singleton
**Intent**: Exactly one instance, globally accessible.
**Recognize it**: A shared resource (connection, configuration) that must not be duplicated or overwritten.
**Shape**: Private constructor; static accessor that lazily creates and thereafter returns the one instance.
**Use when**: there truly must be one instance; you need stricter control than a global variable.
**Non-obvious**: It solves two problems at once (instance count and global access), which is itself a Single Responsibility violation. It can mask bad design in which components know too much about each other. It needs care under concurrency. It makes client code hard to unit test, since private constructors and static accessors resist substitution.
**Guidance when the choice is open**: last resort. Prefer creating the one instance at the composition root and *passing it* to what needs it: still one instance, no hidden global coupling, trivially replaceable in tests. Module-level instances or `object` declarations are the idiomatic form where available.
**Guidance when the user has already chosen it**: write a good one, with the exact call shape they asked for, and say nothing more about the choice. Make it good in the code: typed keys, validation at first use so misconfiguration fails at startup, immutable state, and a clearly named reset-for-tests hook. Do not tell them to inject it, wrap it in an interface, or call it only from certain places; those are arguments against their decision in disguise.
