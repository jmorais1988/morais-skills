---
name: "code-design-refactoring"
description: Refactoring and design-pattern knowledge base - code smells, behaviour-preserving refactorings, SOLID, the 22 classic patterns, characterization tests for untested code, incremental migrations. Use when refactoring or cleaning up code, reviewing code structure, untangling legacy or hard-to-test code, or choosing a pattern or design principle.
---

# Code Design & Refactoring

A working knowledge base for making code easier to read, change, and extend, in any programming language.

## Two rules about the reply itself

**This skill is invisible to the user.** Never mention it, and never cite its rule numbers, step numbers, section titles, or file names ("per ground rule 10", "the skill's decision table", "workflow step 6"). The user cannot see any of it, so such references read as invented authority. Give the reasoning itself, in your own words. Naming a smell, a refactoring, a pattern, or a principle is fine: that vocabulary is public.

**The skill should make answers more rigorous, not longer.** Aim for the length the request would deserve anyway. Do not recite the catalog, do not list every smell you can find, and do not explain a principle the user did not ask about. Report the few things that matter to the pressure they described. Brevity applies to prose, never to verification: the tests, the walk through each failure path, and the list of preserved quirks are the substance of the answer. "Double-check the error mapping" is not a substitute for checking it.

## The mental model

Four kinds of knowledge work together. Keep them distinct:

| Layer | What it is | Role |
|---|---|---|
| **Code smells** | Observable symptoms of structural problems | Diagnosis: tells you *where* to look |
| **Refactoring techniques** | Small, named, behavior-preserving transformations | Treatment: tells you *what move to make* |
| **Design principles** | Reasons some structures age better than others | Judgment: tells you *why* and *how far to go* |
| **Design patterns** | Proven arrangements of collaborating objects for recurring problems | Destination: a shape to refactor *toward* when pressure justifies it |

A pattern is a blueprint, not a snippet: the same pattern looks different in every codebase. An algorithm prescribes steps; a pattern describes a result and leaves the construction order to you. Patterns also act as shared vocabulary, so naming the pattern you used is part of the value.

## Ground rules for refactoring

Refactoring means improving structure **without changing observable behavior**. Everything below follows from that.

1. **Never mix refactoring with feature work or bug fixes in the same step.** If you find a bug mid-refactor, note it and fix it separately. But preserving behavior is not the same as freezing a poor interface. When the interface itself is part of the problem the user brought you (integer error codes, a flag parameter, an awkward signature), deliver the better one *alongside* the old one, with the old one kept as a thin deprecated wrapper so no caller breaks. Flagging a problem you could have solved without breaking anything is under-delivering.
2. **Work in small steps and verify after each one.** Run tests (or whatever verification exists) after every move. A pile of unverified changes turns into a debugging session. In typed languages the compiler and type checker are part of that verification: prefer designs where a forgotten case fails to build (an unimplemented interface method, a non-exhaustive match) over designs where it fails silently at runtime.
3. **Keep the program working at every intermediate point.** The standard migration move for changing a signature or name: create the new function, make the old one delegate to it, migrate callers one at a time, then delete the old one.
4. **If the element is part of a published interface, deprecate instead of deleting.** Callers you cannot see still depend on it.
5. **Check the inheritance chain before touching a method.** If it is overridden or declared in a parent/child, the change must be repeated there, or the refactoring may not be safe at all.
6. **Migrate the least risky pieces first** (private helpers before public methods; methods before the fields they use, so data stays reachable throughout).
7. **Mark a save point after every verified step**, keeping structural changes apart from behavioral ones. A green build at a known state is what lets you revert a red step instead of debugging it, and lets a reviewer confirm "this step changes no behavior". Commit only when the user asks; until then, list the save points so the user can commit them as separate commits.
8. **If the result is uglier than what you started with, revert.** Some structures (for example certain parallel hierarchies) are the lesser evil.
9. **Do not pre-emptively worry about performance.** Extra function calls are almost never the bottleneck, and clean code is easier to optimize later. Two real exceptions: a temp variable that caches an expensive computation, and splitting a short-circuiting boolean expression into eagerly evaluated variables.
10. **No tests? Build the safety net first.** (Recipe: `references/characterization-testing.md`.) Write *characterization tests* that pin down what the code does today, quirks included, before restructuring anything. If you can execute code, write them, run them against the original, refactor, and run them again against the result; reporting "same tests pass before and after" is what turns a rewrite into a refactoring. Give every comparison in the code a case exactly at its boundary. Then break the original on purpose once or twice and confirm the tests fail; a suite that cannot fail proves nothing. If you cannot execute code, provide the tests anyway and keep the steps smaller and more mechanical.
11. **Preserve suspicious behavior, and flag it.** Refactoring exposes things that look like bugs (an off-by-one boundary, a log written before a check fails, an unknown value silently accepted). Do not quietly fix them: someone may depend on them, and mixing a behavior change into a restructuring makes both unreviewable. Keep the behavior, pin it with a test, and list it for the user to decide on.

## Workflow

### 1. Understand the pressure
Ask what is actually hurting: hard to read, hard to change, hard to test, hard to reuse, or a specific upcoming change that the current structure resists. Refactor toward a concrete need, not toward abstract tidiness. The smallest change that relieves the pressure wins.

Also respect what was asked. If the user says they have already decided something (a Singleton, a rewrite, a framework) and asks you to build it well, build it well: do not reopen the decision, do not steer them toward the alternative in prose, and keep the exact shape they asked for. Put your care into the code instead. A request to *review* is not a request to rewrite: give findings, ranked, with the named fix for each, and offer to apply them. And size the job: if the code cannot be tested as it stands, or the change spans hundreds of call sites, several services, or a data store, this is not a one-sitting refactoring. Read `references/legacy-and-large-scale.md` and plan an incremental migration in which old and new coexist and every step ships. Say explicitly that new features get written as new, tested code called from the old code rather than added to it, because that is what removes the need for a feature freeze.

### 2. Diagnose
Scan for smells using the quick table below. Name the smell explicitly to the user: a named problem is easier to discuss and justifies the change. For details, causes, and "when to ignore", read `references/code-smells.md`.

### 3. Choose the smallest effective treatment
Each smell maps to a short list of techniques. Prefer the cheap, local ones (extract, rename, move) before structural ones (new types, hierarchies, patterns). For step-by-step mechanics and caveats, read `references/refactoring-techniques.md`.

### 4. Apply, verifying as you go
Follow the mechanics. Present changes as a sequence of named steps so the user can review, stop, or reorder.

### 5. Check for overshoot
Many smells come in opposing pairs, and over-treating one produces the other:

| Too little | Too much |
|---|---|
| Large Class / Divergent Change | Shotgun Surgery, Lazy Class |
| Message Chains | Middle Man |
| Duplicate Code | One over-parameterized function full of flags |
| Primitive Obsession / Long Parameter List | Data Class with no behavior, unwanted coupling to a whole object |
| Rigid hard-coded design | Speculative Generality |

### 6. Before replacing branching with polymorphism, ask which axis changes
Any design with several *variants* and several *operations* makes one axis cheap to extend and the other expensive. Polymorphism is not automatically the better side of that trade.

| Structure | Add an operation | Add a variant |
|---|---|---|
| Data table (variants differ only in *values*: rates, labels, limits) | Cheap: read another field | Cheap: one new row |
| Branching on a closed set (switch, pattern match over a sum type) | Cheap: one new function | Expensive: edit every branch site |
| Polymorphism (interface or trait, one implementation per variant) | Expensive: edit every implementation | Cheap: one new type |
| Visitor | Cheap: one new visitor | Expensive: edit every visitor |

First check whether the variants differ in *logic* at all. If they differ only in values, a lookup table of plain data beats both alternatives, and building a type per variant is over-engineering. Otherwise choose by what actually changes in this codebase, which you usually have to ask about or read from its history. Variants keep arriving: polymorphism. Operations keep arriving over a stable set of variants: keep the branching, or use Visitor where the language lacks sum types. The Switch Statements smell is really about *unsafe* scattering, where nothing reports the branch you forgot. If the compiler enforces exhaustive matching and there are no wildcard arms hiding new variants, most of that danger is gone, and several *different* operations each matching on the same type is not duplication. Same type-based *decision* copy-pasted in several places still is.

### 7. Reach for a pattern only when the problem has the pattern's shape
Use the selector table below, then read the relevant catalog file. Every pattern buys flexibility at the price of more moving parts. If there are only two variants and they rarely change, a conditional is fine.

## Quick smell lookup

| Group | Smell | Tell-tale sign | First moves |
|---|---|---|---|
| Bloaters | Long Method | Needs comments to navigate; over ~10 lines deserves a look | Extract Method, Decompose Conditional, Replace Temp with Query |
| | Large Class | Many fields/methods, several "hats" | Extract Class, Extract Subclass, Extract Interface |
| | Primitive Obsession | Raw strings/ints standing in for concepts, type codes, string keys as field names | Replace Data Value with Object, Replace Type Code with ... |
| | Long Parameter List | More than 3-4 parameters | Introduce Parameter Object, Preserve Whole Object, Replace Parameter with Method Call |
| | Data Clumps | Same group of values travels together | Extract Class, Introduce Parameter Object |
| OO Abusers | Switch Statements | Same type-based branching in several places, and adding a variant means finding them all | Check the axis of change first (see below); then Replace Conditional with Polymorphism, State/Strategy |
| | Temporary Field | Fields only meaningful during one algorithm | Extract Class (method object), Introduce Null Object |
| | Refused Bequest | Subclass ignores or disables inherited members | Replace Inheritance with Delegation, Extract Superclass |
| | Alternative Classes, Different Interfaces | Two types do the same job under different names | Rename/Move Method, Extract Superclass |
| Change Preventers | Divergent Change | One type edited for many unrelated reasons | Extract Class |
| | Shotgun Surgery | One change touches many types | Move Method/Field, Inline Class |
| | Parallel Inheritance Hierarchies | Adding a subclass here forces one there | Make one hierarchy reference the other, then Move Method/Field |
| Dispensables | Comments (as deodorant) | Comments explain *what* instead of *why* | Extract Variable/Method, Rename, Introduce Assertion |
| | Duplicate Code | Same or equivalent logic in several places | Extract Method, Pull Up, Form Template Method, Extract Class |
| | Lazy Class | Type that does almost nothing | Inline Class, Collapse Hierarchy |
| | Data Class | Only fields and accessors | Encapsulate Field/Collection, Move Method into it |
| | Dead Code | Unused anything | Delete it |
| | Speculative Generality | Hooks and abstractions "for later" | Collapse Hierarchy, Inline Class/Method, Remove Parameter |
| Couplers | Feature Envy | Method uses another object's data more than its own | Move Method, Extract Method |
| | Inappropriate Intimacy | Types poke at each other's internals | Move Method/Field, Extract Class, Hide Delegate, make association one-way |
| | Message Chains | `a.b().c().d()` | Hide Delegate, Extract + Move Method |
| | Middle Man | Type only forwards calls | Remove Middle Man |
| Other | Incomplete Library Class | Third-party type lacks what you need | Introduce Foreign Method, Introduce Local Extension |

## Quick pattern selector

| If the problem is... | Consider |
|---|---|
| Creation code is coupled to concrete types; a framework user must substitute their own component | Factory Method |
| Objects come in matching families (themes, platforms, vendors) that must not be mixed | Abstract Factory |
| Constructor with many optional parameters; same build process, different representations | Builder |
| Need copies of objects without knowing their concrete type; many preset configurations | Prototype |
| Exactly one shared instance with controlled access (use sparingly) | Singleton |
| Useful existing/third-party type has the wrong interface | Adapter |
| A type varies along two independent dimensions and subclasses are multiplying | Bridge |
| Tree of parts and containers that clients should treat uniformly | Composite |
| Optional behaviors that must be stackable and combinable at runtime | Decorator |
| A complex subsystem needs a simple entry point | Facade |
| Huge number of similar objects exhausts memory | Flyweight |
| Need lazy loading, access control, caching, logging, or remoting in front of an object, same interface | Proxy |
| A request must pass through a configurable sequence of handlers, any of which may stop it | Chain of Responsibility |
| Operations must be queued, scheduled, logged, undone, or bound to UI triggers | Command |
| Traverse a collection without exposing its internal structure | Iterator |
| Many components talk to each other in a tangled web | Mediator |
| Snapshot and restore an object's state without breaking encapsulation | Memento |
| Objects must react to another object's events; the set of listeners changes at runtime | Observer |
| Behavior depends on a current state, with big state-machine conditionals | State |
| Several interchangeable algorithms for one job, chosen at runtime | Strategy |
| Several near-identical algorithms differ only in certain steps | Template Method |
| New operations needed across a stable hierarchy of element types without editing them | Visitor |

Look-alikes (Adapter/Decorator/Proxy/Facade, State/Strategy/Bridge, Mediator/Observer, and so on) are disentangled in `references/pattern-selection.md`.

## Principles in one breath

Read `references/design-principles.md` for the reasoning, checklists, and limits. The short version:

- **Encapsulate what varies**: isolate the parts likely to change so changes stay contained.
- **Program to an interface, not an implementation**: depend on the narrow contract you actually need.
- **Favor composition over inheritance**: "has-a" delegates can be swapped at runtime and avoid subclass explosion.
- **SRP**: one reason to change per unit. **OCP**: add behavior by adding code, not editing tested code (bug fixes excepted). **LSP**: a subtype must work anywhere its parent does. **ISP**: narrow, role-specific interfaces. **DIP**: high-level policy owns the abstraction; low-level detail implements it.
- **Tell, don't ask** and **keep data with the behavior that uses it**: things that change together live together.
- **Command-query separation**: a function either answers a question or changes state, not both.
- **Pragmatism over dogma**: every principle and pattern costs complexity. A 200-line script needs tidy functions, not architecture.

## Making it language-agnostic

The source vocabulary is class-based OOP. Translate concepts, not syntax, to the user's language and follow that language's idioms over the letter of any technique.

| Classic term | What it really means | Equivalents across languages |
|---|---|---|
| Class | A unit bundling data with the behavior that owns it | struct + functions, module, record with associated functions, closure over state |
| Interface / abstract class | A contract a caller depends on | protocol, trait, type class, structural/duck typing, function signature |
| Subclass + override | Selecting behavior by variant | trait impls, sum types + pattern matching, dispatch tables, passing functions |
| Method | Function with privileged access to some data | any function; "move method" = move the function next to the data it uses most |
| Private / encapsulation | Limiting who can touch internals | module-private names, unexported identifiers, closures, naming conventions |
| Getter/setter | A controlled access point | properties, accessor functions, immutable records with "with" copies |
| Exception | Out-of-band error path | Result/Either types, error return values where idiomatic, panics only for bugs |
| Null object | A do-nothing stand-in to avoid null checks | Option/Maybe types, default implementations, empty collections |
| Static factory method | A named function that returns an instance | constructor functions, `new_*`/`from_*` functions, companion objects |

Guidance when adapting:

- **Functions are lightweight objects.** Where functions are first-class, Strategy is "pass a function", Command is "a closure plus its arguments", Template Method is "a higher-order function with callback steps", Observer is "a list of callbacks or an event emitter", and a simple Factory is "a function returning the right implementation". Use the full object form only when the behavior needs its own state, several related operations, or a name worth having.
- **Many languages build patterns in.** Iterators/generators, decorators/annotations, event systems, module-level singletons, copy/clone protocols, pattern matching. Prefer the built-in mechanism and mention which pattern it embodies.
- **Sum types change the polymorphism trade-off.** Pattern matching over a closed set of variants with compiler exhaustiveness checks is a legitimate alternative to "replace conditional with polymorphism"; Visitor is essentially that same trade-off simulated in languages without sum types. See workflow step 6 for how to choose.
- **Error-handling advice is about separating the normal path from the failure path** using the language's idiomatic mechanism. Do not introduce exceptions into a Result-based codebase. The durable rules: do not signal errors with magic return values that callers can ignore, and do not use the error mechanism for ordinary, checkable conditions.
- **Without inheritance**, "pull up / push down / extract superclass" become "extract shared function, module, mixin, or embedded struct". The goal (one home for shared logic) is unchanged.
- **Dynamic languages** cannot enforce privacy or immutability (relevant to Memento, Flyweight, value objects). Use conventions, frozen objects, and tests.
- **Thresholds are heuristics** (10-line methods, 3-4 parameters). They prompt a question, not a verdict.

## Self-check before you answer

These are the ways this kind of work commonly goes wrong. Run through them before presenting.

- **Does every failure still fail the same way?** Happy paths survive refactoring; failure paths are where behavior quietly changes. Walk each failure exit of the original and confirm the new code produces the same result for it. Three hazards account for most slips. *Merged errors*: flattening nested checks into a pipeline, a `with`/`else`, or a shared handler can make distinct failures indistinguishable, so "no weight" and "no carrier" both come out as "bad weight"; have each step return its own specific error rather than relabelling afterwards. *Tolerant rewrites*: swapping a strict lookup for a forgiving one (`o["items"]` to `o.get("items")`, optional chaining, a default value) turns a crash into a quiet success or a `False`; that is a behavior change, so keep the strict form or flag it. *Moved side effects*: see the next item.
- **Did a side effect move across a point of failure?** "Compute everything first, then act" is a natural tidy-up, and it silently reorders logs, writes, and sends relative to anything that can throw or return early, including crashes on malformed input. For each side effect, check that the same things can still fail *before* it and *after* it as in the original. Pin at least one malformed-input case in the characterization tests.
- **Did the tests run against the original, not only the result?** Tests written from reading the old code and run only on the new code describe your implementation. They are not evidence of equivalence until they have passed on both.
- **Is every concrete value you cite computed?** A specific number, output, or count offered as evidence (a floating-point artifact, a total, "12 call sites") must come from running or calculating it. Plausible-looking invented examples are easy to produce and are simply false. If you cannot compute it, describe the risk without an example.
- **Does each claim match what the mechanism guarantees?** "Impossible", "always", "cannot" need checking. An interface makes a forgotten *method* a compile error, but not a forgotten *registration*: wherever one lookup keyed on a type code remains (registry, factory), add a test that every known code resolves. Before stating a consequence ("this order is lost"), trace it through the code line by line.
- **Is the new code you wrote held to the same standard?** A proposed fix or a new class is new code: probe *its* failure path and edge inputs (empty string, zero) as carefully as you characterized the legacy code. Ask specifically: if this fails or is killed halfway, what is left behind, and under what name? Anything that writes a file others will pick up should write to a temporary name, rename on success, and clean up on failure.
- **Do your findings agree with each other?** One finding often changes the consequence of another: a swallowed exception means a thrown one never surfaces, so "this blows up at runtime" and "errors are silently ignored" cannot both describe the same call. Before sending, describe once, end to end, what actually happens on the path you are criticizing, and make every finding consistent with that.
- **In a review, did you look beyond structure?** Smells are not the only findings. Check error handling, shared mutable state and thread safety for anything service-like, money and time representation, and resource cleanup.

## How to present the work

- Name the smell, name the technique or pattern, and state the payoff in one or two sentences. Skip lectures.
- Show before/after in the **user's language and style**. Match their naming conventions.
- For multi-step refactorings, list the ordered steps and where to run tests.
- State the trade-off honestly: what got more complex, and why it is worth it (or when it would not be).
- Say where you stopped and why. "I did not introduce a Strategy per tier because three tiers differing only by a rate are better served by a data table" tells the user the restraint was a decision, and tells them what future pressure would justify the next step.
- List the suspicious behaviors you preserved (ground rule 11), each in a line, so the user can decide which are bugs. This is often the most valuable part of the response.
- Report how you verified, precisely: which tests, whether they ran against the original as well as the result, whether you checked they can fail, plus compiler or linter checks. Say plainly what was *not* verified.
- When the user has made an informed decision you would have made differently (a Singleton, a rewrite, a framework), respect it. Raise a concern once and briefly if they have not heard it; if they say they have, skip it. Then do the job well, building the mitigations silently into the code (validation, immutability, a way to reset state in tests) without changing the call shape they asked for and without advice about how they ought to use it instead. One short remark is the ceiling; zero is usually right. Helping someone succeed with their choice is worth more than being right about the alternative.
- If the honest answer is "leave it alone", say so. Simple switch statements, obvious numbers, a framework's unused extension points, and parallel hierarchies that resist untangling are all legitimate to keep. If, while looking, you find a genuine defect rather than a structural problem, report it as exactly that: a proposed *behavior change*, separate from any refactoring, for the user to accept or decline. Hold the fix to the standard you applied to their code: if it writes a file, it writes to a temporary name and renames on success.
- Code comments that explain *why* a non-obvious choice was made are valuable; do not strip them.

## Reference files

Read only what the task needs.

| File | Read when |
|---|---|
| `references/design-principles.md` | Judging a design, explaining *why*, reviewing inheritance (LSP checklist), deciding how far to go, clarifying object relationships (dependency through inheritance) |
| `references/code-smells.md` | Reviewing or diagnosing code; need causes, full treatment options, payoffs, and legitimate exceptions for each of the 23 smells |
| `references/refactoring-techniques.md` | About to perform a specific refactoring; need its preconditions, step-by-step mechanics, drawbacks, and follow-ups (66 techniques in 6 groups, with a table of contents) |
| `references/worked-examples.md` | Want a concrete before/after for the commonest moves: guard clauses, comments to names, parameter object, type code three ways, message chains, a pattern at three weights |
| `references/characterization-testing.md` | The code has no tests and you are about to restructure it; need the recipe for pinning current behavior, switching the suite between old and new, and what to do when testing is impossible |
| `references/legacy-and-large-scale.md` | Code resists testing (hidden dependencies, globals, side effects welded to logic), a feature must be added to an untested tangle, or the change is too big for one sitting: seams, sprout/wrap, parallel change, branch by abstraction, strangler fig, Mikado, data migration, commit discipline, agent conduct. *Supplementary: goes beyond the two source books* |
| `references/patterns-creational.md` | Object creation problems: Factory Method, Abstract Factory, Builder, Prototype, Singleton |
| `references/patterns-structural.md` | Composing types and wrapping objects: Adapter, Bridge, Composite, Decorator, Facade, Flyweight, Proxy |
| `references/patterns-behavioral.md` | Communication and responsibility: Chain of Responsibility, Command, Iterator, Mediator, Memento, Observer, State, Strategy, Template Method, Visitor |
| `references/pattern-selection.md` | Choosing between similar patterns, combining patterns, mapping smells to patterns, evolving a design over time |
