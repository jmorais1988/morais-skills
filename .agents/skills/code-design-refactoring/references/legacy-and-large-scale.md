# Legacy Code and Large-Scale Migration

> **Provenance**: this file is supplementary. It is not drawn from the two source books behind the rest of this skill but from widely used industry practice, notably Michael Feathers' work on legacy code (seams, sprout, wrap), Martin Fowler's writing on Strangler Fig, Branch by Abstraction and Parallel Change, and the Mikado Method. Technique names in **bold** refer to `refactoring-techniques.md`.

Use this when the code cannot simply be refactored in an afternoon: there are no tests and it resists testing, or the change spans hundreds of call sites, several services, or a data store.

## Contents
1. The legacy dilemma and the way out
2. Seams
3. Dependency-breaking moves that are safe without tests
4. Adding features without making things worse
5. Understanding code you are afraid of
6. Large-scale migration: principles
7. Large-scale migration: techniques
8. Version control discipline (and working as an agent)
9. When a rewrite is actually right

---

## 1. The legacy dilemma and the way out

To change code safely you need tests; to get legacy code under test you usually need to change it. The way out is to allow yourself a *small set of conservative, mechanical edits* whose only purpose is to make testing possible, then write tests, then refactor properly.

Working order:
1. **Identify change points**: where must the behavior change?
2. **Find test points**: where can you observe the effects of that code?
3. **Break dependencies** that stop you getting the code into a test harness (section 3).
4. **Write characterization tests** (`characterization-testing.md`).
5. **Make the change and refactor**, using the normal catalog.

Do not try to clean the whole thing. Cover and improve the region you need to change, and leave it better than you found it; over time the frequently changed areas become the clean ones, which is where it pays.

## 2. Seams

A **seam** is a place where you can alter behavior *without editing the code at that place*. Every seam has an **enabling point**: where you decide which behavior runs. Getting legacy code under test is mostly a hunt for seams, or the creation of new ones.

| Seam | How behavior is substituted | Enabling point |
|---|---|---|
| Object / interface | Pass in a different implementation; override a method in a test subclass | Constructor argument, parameter, factory |
| Function | Pass a function as a parameter; default to the real one | Call site |
| Module / link | Swap which module or library is imported or linked for the test build | Build config, import path, module mocking facility |
| Configuration | Behavior chosen from settings or environment | Config file, env var |

Prefer object and function seams: they are explicit and visible in the code. Link-level and monkey-patching seams work as a last resort but leave hidden coupling behind.

## 3. Dependency-breaking moves that are safe without tests

The obstacles are nearly always the same: a constructor that does real work (opens connections), hidden collaborators created internally, globals and singletons, static calls, and side effects welded to logic. These moves are mechanical enough to perform with the compiler as your only net.

- **Parameterize the constructor or function.** The collaborator that was created inside becomes a parameter, with a default that preserves today's behavior. Existing callers do not change; tests pass a fake.
- **Extract Interface** on the collaborator, and depend on that. Step one of Dependency Inversion.
- **Extract and override.** Pull the awkward call (object creation, static call, clock read) into its own small overridable method; a test subclass overrides just that. Crude but fast; tidy into real injection later.
- **Wrap the global.** Put the singleton, static API, or global behind an instance-level accessor or thin adapter that tests can replace. Callers switch one at a time.
- **Separate the pure core from the effectful shell.** Extract the computation into a function that takes values and returns values, leaving reads, writes, and I/O at the edges. The core becomes trivially testable with no fakes at all. Usually the highest-value move available (**Extract Method**, **Separate Query from Modifier**).
- **Adapt the parameter.** When a parameter's type is impossible to construct in a test (a framework request object), introduce a narrow interface exposing only what the code uses and wrap the real one.

Habits that keep these edits safe: *preserve signatures* (copy and paste them, do not retype); *one goal per edit*; *lean on the compiler* (make the change, let the errors list every site); prefer *automated tool refactorings* over hand edits; commit after each move.

## 4. Adding features without making things worse

When you must add behavior to an untested tangle and cannot afford to get it all under test first:

- **Sprout.** Write the new behavior as a new, fully tested function or type, and call it from the legacy code with a single line. The tangle grows by one line rather than thirty.
- **Wrap.** Rename the existing function, create a new one under the old name that calls the original plus the new, tested behavior (before or after). At type level this is a Decorator.

Both leave the old code no better, but they stop the bleeding, and the new code is clean and covered from day one.

## 5. Understanding code you are afraid of

- **Scratch refactoring.** On a throwaway branch, refactor aggressively and carelessly (extract, rename, delete) purely to learn the shape of the code. Then discard it all. Do not be tempted to keep it; its value was the understanding.
- **Sketch effects.** For a variable or field, trace what can change it and what it can affect. This shows where a test must observe.
- **Monster functions.** Find the skeleton first (the top-level conditionals and loops). Extract the small, low-coupling pieces first: those needing few parameters and returning one value. A temporary "sensing" variable can expose an intermediate result to a test until extraction makes it unnecessary.
- Look for the hidden types: groups of variables and code that change together are an **Extract Class** waiting to happen.

## 6. Large-scale migration: principles

- **No big-bang rewrites on a long-lived branch.** The old system keeps changing underneath you, integration is deferred to the riskiest possible moment, and value arrives only at the end, if at all.
- **Old and new coexist**, and the mainline stays releasable at every step.
- **Each step is small, verifiable, and reversible.**
- **Make progress measurable**: a count of remaining call sites, routes, or tables still on the old path. Put it somewhere visible.
- **Finish.** A half-completed migration is worse than either end state: two ways to do everything, both of which must be understood. Budget explicitly for the last 20% and for deleting the old path.
- **Do not improve behavior during migration.** Reproduce it, quirks included, prove equivalence, switch over; *then* improve. The same separation as ground rule 1, at system scale.

## 7. Large-scale migration: techniques

### Parallel change (expand, migrate, contract)
For anything with consumers you cannot change atomically: function signatures, library APIs, message formats, database schemas, configuration.
1. **Expand**: add the new form alongside the old. Both work.
2. **Migrate**: move consumers over one at a time, each independently shippable.
3. **Contract**: when nothing uses the old form, remove it.

This is the **Rename Method** mechanics (new one added, old one delegates, callers move, old one is deprecated and deleted) generalized to any interface.

### Branch by abstraction
For replacing a component used in many places, in the mainline, without a long-lived branch.
1. Introduce an abstraction (interface) that captures how clients use the current component.
2. Point clients at the abstraction, a few at a time. Still the old implementation behind it.
3. Build the new implementation behind the same abstraction, developed and tested in the mainline but not yet selected.
4. Switch over, by configuration or flag, gradually or per client.
5. Delete the old implementation. Remove the abstraction too if it no longer earns its keep (**Inline Class**).

In pattern terms: **Extract Interface**, then a Strategy selected by a flag, with Adapter where the new component's API differs.

### Strangler fig
For replacing a whole system or large subsystem.
1. Put an **interception point** in front of the old system: a router, proxy, or facade through which all traffic passes.
2. Build one slice of functionality in the new system and route just that slice to it.
3. Repeat slice by slice; the new system grows around the old one until nothing routes to the old, which is then removed.

Needs a clean interception point, and usually a plan for shared data (both systems reading one store for a while, or synchronization). Put an **anti-corruption layer** (Adapter/Facade) between new and old so the legacy model does not leak into the new design.

### Shadow (dark) comparison
Run the new implementation alongside the old on real inputs, serve the old result, and log every mismatch. This is characterization testing with production as the test suite. Switch over once the mismatch rate is zero or fully explained. Take care with side effects: the shadow path must not send the email twice.

### Feature flags
Decouple *deploying* the new path from *releasing* it; enable per user, tenant, or percentage; roll back instantly. Flags are debt: delete each one as soon as its migration completes.

### Data migration by expand and contract
1. Add the new column, table, or store. 2. Write to both. 3. Backfill historical data. 4. Verify the two agree. 5. Switch reads to the new. 6. Stop writing the old. 7. Drop it. Each step ships and can be reversed independently.

### The Mikado method
For changes whose prerequisites are unknown and tangled.
1. Attempt the goal naively. 2. Note what breaks; those are prerequisites. 3. **Revert.** 4. Attempt each prerequisite the same way, recursively, drawing the dependency graph as you go. 5. When a node works with nothing else breaking, commit it. 6. Work from the leaves back to the goal.

The discipline is in the revert: never keep a broken tree while you dig further in.

### Bulk mechanical change
For the same edit at hundreds of sites (rename, signature change, import move), do it with a tool or script (IDE refactoring, codemod, structured search-and-replace), in its **own commit containing nothing else**, and review a sample plus the tool's configuration rather than every line.

## 8. Version control discipline (and working as an agent)

- **Commit after every verified step.** A green build plus a commit is a save point; when a step goes red, reverting is nearly always faster than debugging.
- **Separate structural commits from behavioral commits**, and ideally separate pull requests. A reviewer can check "this changes no behavior" or "this changes this one behavior", never both together.
- **Keep each change reviewable**: a sequence of small, named steps ("Extract PricingPolicy", "Move discount rules into PricingPolicy") beats one large diff.

When acting as an agent with access to a repository:
- Discover how to build and test before editing anything, and run that after every step.
- Commit on green, with messages naming the refactoring performed. If committing is not appropriate, say where the save points would be.
- If no verification is available, say so *before* proceeding, propose building it (characterization tests), and otherwise restrict yourself to tool-driven or compiler-checked moves.
- Do not silently widen scope. Note adjacent smells in the report; do not fix them uninvited.
- For bulk edits, write the script, show it, run it, and report the count of sites changed.

## 9. When a rewrite is actually right

Rarely, but it happens: the component is small; its behavior is well specified or already well covered by tests that can judge the replacement; the platform underneath is truly dead; or the code is so wrong for the current problem that little would survive refactoring. Even then, put it behind an abstraction, run old and new in parallel, and switch over incrementally. That is a rewrite delivered as a migration, which keeps it reversible.
