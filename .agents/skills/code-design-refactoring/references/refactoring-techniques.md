# Refactoring Techniques Catalog

Each technique is a small, named, behavior-preserving transformation. Entries give: **When** (the trigger), **Do** (the move), **Steps** (safe mechanics), and **Watch** (drawbacks, preconditions, follow-ups). Classic names are kept because they are shared vocabulary; "method" means any function, "class" any unit that bundles data with behavior, "field" any piece of state it owns. Verify after each step.

Before/after sketches of the most common moves are in `worked-examples.md`. For code with no tests, start with `characterization-testing.md`; for changes too large for one sitting, see `legacy-and-large-scale.md`.

Many techniques come in inverse pairs (Extract/Inline, Pull Up/Push Down, Hide Delegate/Remove Middle Man). Neither direction is "correct"; the right one depends on which smell you currently have.

## Contents

1. **Composing Methods**: Extract Method, Inline Method, Extract Variable, Inline Temp, Replace Temp with Query, Split Temporary Variable, Remove Assignments to Parameters, Replace Method with Method Object, Substitute Algorithm
2. **Moving Features Between Objects**: Move Method, Move Field, Extract Class, Inline Class, Hide Delegate, Remove Middle Man, Introduce Foreign Method, Introduce Local Extension
3. **Organizing Data**: Self Encapsulate Field, Replace Data Value with Object, Change Value to Reference, Change Reference to Value, Replace Array with Object, Duplicate Observed Data, Change Unidirectional Association to Bidirectional, Change Bidirectional Association to Unidirectional, Replace Magic Number with Symbolic Constant, Encapsulate Field, Encapsulate Collection, Replace Type Code with Class, Replace Type Code with Subclasses, Replace Type Code with State/Strategy, Replace Subclass with Fields
4. **Simplifying Conditional Expressions**: Decompose Conditional, Consolidate Conditional Expression, Consolidate Duplicate Conditional Fragments, Remove Control Flag, Replace Nested Conditional with Guard Clauses, Replace Conditional with Polymorphism, Introduce Null Object, Introduce Assertion
5. **Simplifying Method Calls**: Rename Method, Add Parameter, Remove Parameter, Separate Query from Modifier, Parameterize Method, Replace Parameter with Explicit Methods, Preserve Whole Object, Replace Parameter with Method Call, Introduce Parameter Object, Remove Setting Method, Hide Method, Replace Constructor with Factory Method, Replace Error Code with Exception, Replace Exception with Test
6. **Dealing with Generalization**: Pull Up Field, Pull Up Method, Pull Up Constructor Body, Push Down Method, Push Down Field, Extract Subclass, Extract Superclass, Extract Interface, Collapse Hierarchy, Form Template Method, Replace Inheritance with Delegation, Replace Delegation with Inheritance

---

## 1. Composing Methods

Overlong functions are the root of most trouble: they bury the logic and resist change. These techniques streamline functions, remove duplication, and open the way for further improvement.

### Extract Method
- **When**: A fragment of code can be grouped and named. The workhorse of refactoring and a step inside many other techniques.
- **Do**: Move the fragment into a new function named for its *purpose* and call it from the original spot.
- **Steps**: (1) Create the function with an intention-revealing name. (2) Move the fragment. (3) Variables declared and used only inside the fragment stay local to the new function. (4) Variables declared before the fragment become parameters (or are eliminated first with Replace Temp with Query). (5) If the fragment modifies a local that is needed afterwards, return it.
- **Watch**: A fragment that modifies several outer locals is a sign to first untangle them (Split Temporary Variable, Replace Temp with Query) or to use Replace Method with Method Object.

### Inline Method
- **When**: The body is as clear as the name, or the code has become a maze of trivial delegations. Functions often become pointless over time rather than starting that way.
- **Steps**: (1) Confirm the function is not overridden anywhere; if it is, stop. (2) Replace every call with the body. (3) Delete it.

### Extract Variable
- **When**: An expression is hard to read (a compound condition, a long arithmetic formula, a long chained line).
- **Do**: Assign sub-expressions to well-named local variables.
- **Watch**: Splitting a short-circuiting condition (`a() || b()`) into variables makes *both* sides always execute; this matters if they are expensive or have side effects. Often the first step toward Extract Method when the expression recurs.

### Inline Temp
- **When**: A temp holds the result of a simple expression and adds nothing, usually as preparation for Replace Temp with Query or Extract Method.
- **Watch**: Do not inline a temp that caches an expensive result used several times.

### Replace Temp with Query
- **When**: A local stores an expression result for later use, and that blocks extraction or the same expression appears in other functions.
- **Do**: Move the expression into its own function and call it wherever the temp was used.
- **Steps**: (1) Ensure the temp is assigned exactly once (else Split Temporary Variable). (2) Extract Method on the expression; the query must be free of visible side effects (else Separate Query from Modifier). (3) Replace uses of the temp with calls.
- **Watch**: Costs repeated evaluation. Almost always negligible; if the expression truly is expensive, stop after extracting and keep the cached temp.

### Split Temporary Variable
- **When**: One local is reused for several unrelated intermediate values (loop counters and accumulators excepted).
- **Do**: One variable per purpose, each named for what it holds.
- **Steps**: At the first assignment, rename to match that value; update uses up to the next assignment; repeat for each subsequent assignment.

### Remove Assignments to Parameters
- **When**: A function reassigns one of its parameters.
- **Why**: With pass-by-reference semantics this can silently alter the caller's data; even with pass-by-value it obscures what the parameter means at any point and what was actually passed in.
- **Do**: Copy the parameter into a local at the top and work on the local.

### Replace Method with Method Object
- **When**: A long function whose locals are so interwoven that Extract Method is impractical.
- **Do**: Turn the function into its own class; locals become fields, so the body can be freely split into small methods that share them.
- **Steps**: (1) New class named after the function's purpose. (2) Field for the original object (if its data is needed) plus one field per local and parameter. (3) Constructor takes and stores them all. (4) A main method (e.g. `compute`) receives the original body. (5) The original function now constructs the object and calls the main method. (6) Decompose the main method at will.
- **Watch**: Adds a type. In functional style the equivalent is a closure or a small context record threaded through helper functions.

### Substitute Algorithm
- **When**: A clearer or better algorithm exists, a library now provides it, or requirements have shifted too far for incremental change.
- **Steps**: (1) Simplify the existing function as much as possible first (extract peripheral code): fewer moving parts makes replacement easier. (2) Write the new algorithm in a new function. (3) Run both against the same tests and compare; when results differ, investigate, remembering the fault is more often in the new code than the old. (4) When everything passes, delete the old one.

---

## 2. Moving Features Between Objects

Responsibilities rarely land in the right place on the first attempt. These techniques relocate behavior and data, create and dissolve types, and hide implementation details.

### Move Method
- **When**: A function uses, or is used by, another type more than its own. Moving increases cohesion and can remove a dependency altogether.
- **Steps**: (1) Inspect everything the function uses in its current home; members used only by it should move too, and sometimes it is easier to move a group of functions together. (2) Check parents/children for other declarations; if it is polymorphic, moving may be unsafe. (3) Declare it in the target, renaming if a better name fits there. (4) Decide how the target instance is reached (existing field/accessor, or pass it in). (5) Turn the old function into a delegate; if nothing needs the old entry point, redirect callers and delete it.

### Move Field
- **When**: A field is used more by another type than by its owner. Rule of thumb: keep a field next to the functions that use it.
- **Steps**: (1) If public, encapsulate it first. (2) Create the field with accessors in the target. (3) Decide how to reach the target instance. (4) Redirect every use. (5) Delete the original.

### Extract Class
- **When**: One type does the work of two (Large Class, Divergent Change, Data Clumps, Temporary Field).
- **Steps**: (1) Decide how responsibilities split. (2) Create the new type and link the old one to it, one-way if at all possible. (3) Move Field and Move Method one at a time, private members first, verifying after each. (4) Reconsider names; the slimmed-down original may deserve a new one. (5) Decide exposure: keep the new type hidden behind the old one, or make it public if direct access is safe.
- **Watch**: Overdone, it yields Lazy Classes and Shotgun Surgery; reverse with Inline Class.

### Inline Class
- **When**: A type no longer carries its weight and nothing more is planned for it.
- **Steps**: (1) In the absorbing type, create the donor's public members as delegates. (2) Redirect all clients to the absorbing type. (3) Verify. (4) Move Method/Move Field everything across until the donor is empty. (5) Delete it.

### Hide Delegate
- **When**: Clients obtain object B from object A only in order to call B (Message Chains). Vocabulary: A is the *server*, B the *delegate*.
- **Do**: Add methods on the server that forward to the delegate, so clients neither know nor depend on B.
- **Steps**: Add a forwarding method for each delegate method clients use; repoint clients; if no client needs the delegate directly any more, remove its accessor.
- **Watch**: Too many forwarders turns the server into a Middle Man.

### Remove Middle Man
- **When**: A type is mostly forwarding methods, and each new delegate feature demands yet another forwarder.
- **Do**: Expose an accessor for the delegate and have clients call it directly; delete the forwarders.

### Introduce Foreign Method
- **When**: You need one more operation on a type you cannot modify, and the workaround is being repeated at call sites.
- **Do**: Write the function in your own code, taking the foreign object as a parameter, and mark it clearly as a foreign method that belongs on that type.
- **Watch**: Its location will puzzle future maintainers; if several accumulate, use Introduce Local Extension. Prefer native extension mechanisms (extension methods, traits, protocols, free functions in a utilities module) where they exist.

### Introduce Local Extension
- **When**: You need several operations on an unmodifiable type.
- **Do**: Create an extension type holding them, as either a **subclass** (less work; impossible if the type is sealed/final) or a **wrapper** (always possible; requires forwarding the original's public interface).
- **Steps**: Create the extension; give it the original's constructors plus a *converting* constructor that accepts an original instance; add the new operations (moving in any foreign methods); use the extension where the extra features are needed.

---

## 3. Organizing Data

Replace primitives with rich types, untangle associations, and control access to state.

### Self Encapsulate Field
- **When**: A type reads and writes its own private field directly, but you need lazy initialization, validation on write, or subclass-specific access.
- **Do**: Route even internal access through a getter/setter.
- **Watch**: Direct access is simpler and more readable; do this when the flexibility is needed. Omitting the setter entirely makes the field fixed after construction.

### Replace Data Value with Object
- **When**: A simple field has grown associated data and behavior (a phone number needing formatting and validation), often replicated across several types.
- **Steps**: (1) Self-encapsulate the field if accessed directly. (2) Create a type holding the value, with a constructor taking the primitive and a getter; no setter, since a changed value means a new object. (3) Change the field's type; the owner's getter delegates, its setter builds a new value object. (4) Move related behavior in.
- **Follow-up**: If the concept is a real-world entity that must be unique, continue with Change Value to Reference. Not for dates, money, ranges and the like, which should stay values.

### Change Value to Reference
- **When**: Many equal copies of an object exist, but it represents one real-world entity and changes must be visible everywhere.
- **Steps**: (1) Replace Constructor with Factory Method. (2) Choose what holds the canonical instances (a registry, repository, or static map). (3) Decide between preloading and creating on demand. (4) The factory returns the canonical instance; decide how to handle requests for unknown ones, and rename the factory if it now only returns existing objects.
- **Watch**: References are considerably harder to manage than values.

### Change Reference to Value
- **When**: A reference object is small, rarely changes, and managing its identity and lifecycle is not worth the effort. Especially attractive in concurrent or distributed code.
- **Steps**: (1) Make it immutable: no setters; all state fixed at construction. (2) Implement value equality (and hashing). (3) If the factory is no longer needed, make the constructor public again.
- **Watch**: If it actually needs to change, every copy would have to be updated, which is the cue to use a reference instead.

### Replace Array with Object
- **When**: An array, tuple, or generic map is used as a record with different meanings by position or key.
- **Steps**: (1) New type that initially wraps the array. (2) One well-named accessor per element; migrate callers one at a time. (3) Make the array private. (4) Replace each element with a real field behind its accessor. (5) Delete the array. Then move related behavior in.

### Duplicate Observed Data
- **When**: Domain data and logic are trapped inside UI classes, and you need them separate (several views on the same data, testability, team separation).
- **Do**: Create a domain type owning the data; the UI observes it and keeps its widgets synchronized.
- **Steps**: (1) Self-encapsulate the data in the UI type. (2) Create the domain type with the same fields and accessors. (3) Wire Observer: the domain object notifies; the UI's update handler refreshes widgets. (4) UI setters write to the domain object. Take care that an update cannot re-trigger itself (write widgets directly in the handler, not through the domain setter).
- **Watch**: The classic observer form does not suit request/response web apps where objects are rebuilt per request; the underlying goal of separating domain from presentation still applies and is reached by other means.

### Change Unidirectional Association to Bidirectional
- **When**: Both ends now need to reach each other and computing the reverse lookup is expensive.
- **Steps**: Add the back-reference; designate one side as the *controlling* side that owns all link-changing logic; give the other side a narrowly named helper that only the controlling side calls to keep the link consistent.
- **Watch**: Harder to maintain, and the two types can no longer be used independently.

### Change Bidirectional Association to Unidirectional
- **When**: One direction of a two-way link is no longer used.
- **Steps**: Confirm the dependent side can obtain the other object some other way (a query, a parameter), or does not need it; replace field uses accordingly; remove the assignments; remove the field.
- **Payoff**: Simpler type, lower coupling, and no mutual references holding objects alive.

### Replace Magic Number with Symbolic Constant
- **When**: A literal with special meaning appears in code.
- **Steps**: Declare a named constant; then examine every occurrence of the literal and replace only those that carry *this* meaning, since the same number can mean different things in different places.
- **Watch**: Not every literal is magic; an obvious `0`, `1`, or `2` in context is fine. A literal that equals a collection's size should be replaced by asking the collection. A literal acting as a type code calls for the Replace Type Code techniques instead.

### Encapsulate Field
- **When**: A field is public.
- **Steps**: Add accessors; redirect every external use; make the field private. Then look at the callers: logic surrounding those accesses frequently belongs inside the owning type.
- **Watch**: Rare, genuine performance exceptions exist for tiny, hot, stable data such as coordinate pairs.

### Encapsulate Collection
- **When**: A type hands out its collection through a plain getter/setter, letting clients change the contents behind its back.
- **Do**: Return a read-only view or a copy; provide explicit add/remove operations; no setter that replaces the collection wholesale.
- **Steps**: (1) Add add/remove operations. (2) Initialize the field to an empty collection. (3) Rework or rename any setter (to something like "replace all") so it goes through add/remove. (4) Convert callers that mutate via the getter. (5) Make the getter return a read-only view. (6) Look for client code that belongs on the owner.

### Replace Type Code with Class
- **When**: A type code (enumerated numbers or strings) exists but does **not** drive any branching. Typical origin: a database column.
- **Why**: Setters do not validate raw codes, and neither the compiler nor the IDE can tell a role code from any other integer.
- **Do**: Create a small type with a private value, a getter, and one named factory (or constant instance) per allowed value; replace the primitive everywhere. In most languages today this is simply a proper enum.
- **Watch**: If the code *is* used in conditionals, use one of the next two instead.

### Replace Type Code with Subclasses
- **When**: A type code controls behavior through conditionals, its value never changes after creation, and the owner has no competing subclass hierarchy.
- **Steps**: (1) Self-encapsulate the code. (2) Make the constructor private and add a factory that selects the subclass from the code; this conditional is the one that remains. (3) One subclass per value, each overriding the code getter. (4) Remove the field from the parent; make its getter abstract. (5) Push code-specific fields and methods down. (6) Replace Conditional with Polymorphism.

### Replace Type Code with State/Strategy
- **When**: The type code drives behavior but subclassing the owner is ruled out, either because the code changes during the object's life or because the owner already has a hierarchy.
- **Do**: Extract a separate state hierarchy, one subclass per code value; the owner holds a reference and delegates. Changing the "type" is swapping the state object.
- **Steps**: As above, but the subclasses are of the new state type and the factory lives on its base; the owner's setter asks the factory for the matching state object. Then push behavior down and Replace Conditional with Polymorphism.
- **Choosing the name**: If the value merely selects an algorithm, think Strategy. If it governs the object's overall condition (allowed operations, field meanings, transitions), think State.
- **Watch**: Overkill for a trivial type code; you get many classes for little gain.

### Replace Subclass with Fields
- **When**: Subclasses differ only in methods that return constants.
- **Steps**: (1) Replace the subclass constructors with factory methods on the parent. (2) Add parent fields for the constant values and a protected constructor that sets them. (3) Have subclass constructors call it. (4) Implement the constant methods in the parent from the fields and remove them from the subclasses. (5) Inline the subclass construction into the factories and delete the subclasses.

---

## 4. Simplifying Conditional Expressions

Conditional logic grows more convoluted with time. These techniques restore clarity.

### Decompose Conditional
- **When**: A complex `if/else` (or switch). While reading one branch you forget the condition, and while reading the other you forget the first.
- **Do**: Extract the condition, the then-part, and the else-part into functions named for intent. Worth doing even for short conditions: `isSummer(date)` beats a pair of date comparisons.

### Consolidate Conditional Expression
- **When**: Several separate checks lead to the same result or action.
- **Steps**: (1) Confirm none of the checks has side effects. (2) Combine: sequential checks with OR, nested checks with AND. (3) Extract the combined condition into a function whose name says what is really being tested.

### Consolidate Duplicate Conditional Fragments
- **When**: Identical code appears in every branch.
- **Do**: Hoist it out. At the start of branches, move before the conditional; at the end, move after; in the middle, first check whether it can slide to either end without changing the result. If it is more than a line, extract it.

### Remove Control Flag
- **When**: A boolean variable steers a loop or sequence of checks.
- **Do**: Replace assignments to the flag with `break`, `continue`, or `return`, then delete the flag and its checks. The single-exit rule behind such flags is obsolete in modern languages.

### Replace Nested Conditional with Guard Clauses
- **When**: Nested conditionals form a rightward-drifting arrow and the normal path is hard to find.
- **Do**: Handle each special or edge case at the top with a check that returns (or raises) immediately, leaving the main logic flat and unindented.
- **Steps**: (1) Remove side effects from the conditions (Separate Query from Modifier). (2) Pull out every guard that leads to an early return or error and place it first. (3) Afterwards, guards with the same outcome can be merged with Consolidate Conditional Expression.

### Replace Conditional with Polymorphism
- **When**: A conditional picks behavior from the object's type, a field's value, or the result of a query, particularly when the same branching recurs in several functions.
- **First**: confirm that new *variants*, not new *operations*, are what keeps arriving (workflow step 6 in SKILL.md). If variants differ only in values, a data table is lighter than a hierarchy (`worked-examples.md`, example 4).
- **Prerequisite**: A hierarchy to hold the variants, created via Replace Type Code with Subclasses or with State/Strategy.
- **Steps**: (1) If the conditional shares a function with other work, Extract Method it. (2) For each variant, override the function with that branch's code, then delete the branch. (3) When the conditional is empty, make the base method abstract.
- **Payoff**: Tell-don't-ask; near-identical conditionals vanish; a new variant is a new subtype rather than an edit in many places.

### Introduce Null Object
- **When**: Code is littered with null checks because functions may return "nothing".
- **Do**: Return a special object of the same type that implements the default, do-nothing behavior.
- **Steps**: (1) Subclass the real type as the null version. (2) Add `isNull()` to both (false/true). (3) Return the null object wherever null was returned. (4) Replace null comparisons with `isNull()`. (5) Where the null branch ran alternative code, override the relevant methods in the null object with that code and delete the conditional entirely.
- **Watch**: Costs another type. In languages with Option/Maybe, optional chaining, or default values, prefer those idioms; the goal is the same: eliminate scattered absence checks.

### Introduce Assertion
- **When**: Code only works if some condition holds, and that assumption is implicit or sits in a comment.
- **Do**: State it as an assertion. It documents the contract and fails fast, before bad state spreads.
- **Watch**: Adding an assertion must not change behavior. Assert only what is genuinely necessary; if the code works when the assertion is false, remove it. If users or the environment can cause the condition and it can be handled, use the normal error mechanism instead; assertions are for programmer errors. A failing assertion also points to a missing test.

---

## 5. Simplifying Method Calls

Make interfaces easier to understand and use.

### Rename Method
- **When**: The name does not say what the function does, whether it was rushed at birth or outgrown since.
- **Steps**: (1) Check parents/children; repeat there. (2) Create the new name holding the body; the old one delegates. (3) Migrate callers. (4) Delete the old name, or mark it deprecated if it is part of a public interface.
- **Note**: This non-breaking migration recipe applies equally to Add Parameter and Remove Parameter.

### Add Parameter
- **When**: The function needs information it does not have.
- **Watch**: The easiest refactoring to regret, since it leads straight to Long Parameter List. First ask whether the data belongs on the object itself or on an object already being passed. Use a parameter for occasional or frequently varying data; use a field for data the object needs all the time.
- **Steps**: As Rename Method: new version with the parameter, old one delegates with a default value, migrate callers, delete or deprecate.

### Remove Parameter
- **When**: A parameter is not used in the body. Every parameter costs each reader some thought, and "might need it later" rarely comes true.
- **Watch**: Leave it alone if other implementations of the same method in the hierarchy use it.

### Separate Query from Modifier
- **When**: A function both returns a value and changes visible state.
- **Steps**: (1) Create a pure query returning the value. (2) Make the original return the query's result. (3) At each call site, call the modifier first, then the query. (4) Remove the return value from the modifier.
- **Watch**: "Visible state" is the key: internal caching does not count. Sometimes returning a result from a command is simply practical (number of rows affected, pop from a stack).

### Parameterize Method
- **When**: Several functions do the same thing with different built-in values.
- **Do**: Merge into one function that takes the varying value as a parameter. If only part of the bodies coincide, extract and parameterize just that part.
- **Watch**: Do not overshoot into one long, complicated function. In particular, a parameter that switches behavior on and off breeds a big conditional, the very thing the next technique removes.

### Replace Parameter with Explicit Methods
- **When**: A function is divided into sections chosen by a parameter's value.
- **Do**: One function per variant; callers call the one they mean. `startEngine()` communicates more than `setValue("engineEnabled", true)`.
- **Watch**: Skip if the function rarely changes and variants are not being added.

### Preserve Whole Object
- **When**: The caller pulls several values out of one object just to pass them on.
- **Do**: Pass the object. If the function later needs more from it, only the function changes, not every call site.
- **Watch**: The function now depends on that object's type and cannot be fed from other sources. If that coupling is unwelcome, keep the separate values.

### Replace Parameter with Method Call
- **When**: The caller computes an argument by calling something the callee could call itself.
- **Steps**: (1) Confirm the computation does not depend on the caller's own parameters or locals. (2) If it is more than a single call, extract it first. (3) Replace uses of the parameter in the body with the call. (4) Remove Parameter.

### Introduce Parameter Object
- **When**: The same group of parameters recurs across functions (Data Clumps).
- **Steps**: (1) Create an immutable type for the group. (2) Add Parameter for it, building it from the old arguments at each call site. (3) Remove the old parameters one by one, reading from the object instead, verifying each time. (4) Look for behavior that belongs on the new type and move it there.
- **Watch**: If no behavior ever moves in, you have created a Data Class. That is still often a net improvement.

### Remove Setting Method
- **When**: A field should be set at creation and never again.
- **Steps**: Ensure the constructor accepts the value; fold setter calls that immediately follow construction into the constructor call; inside the constructor assign the field directly; delete the setter.

### Hide Method
- **When**: A function is not used outside its type (or its hierarchy).
- **Do**: Make it as private as the language allows. This tends to become possible as a type matures from data holder to one with real behavior: the raw accessors stop being needed publicly.
- **Payoff**: Private code can be changed without worrying about external callers, and the true public interface stands out. Static analysis and good test coverage help locate candidates.

### Replace Constructor with Factory Method
- **When**: Construction needs more than a constructor can offer: returning a subtype chosen from the arguments (the usual companion to Replace Type Code with Subclasses), returning an existing or cached instance (needed for Change Value to Reference), or having a descriptive name for a particular creation mode.
- **Steps**: (1) Create a static/named factory function that calls the constructor. (2) Redirect every constructor call. (3) Make the constructor private. (4) Move any construction logic not strictly about initializing the object into the factory.

### Replace Error Code with Exception
- **When**: A function reports failure through a special return value that callers can forget to check.
- **Do**: Signal failure through the language's dedicated error channel, keeping the normal path free of error-code conditionals.
- **Steps**: Convert one error code at a time: make callers handle the error via the mechanism; raise it inside the function instead of returning the code; document it in the signature where the language supports that.
- **Watch**: Never use exceptions for ordinary control flow; they are for errors and critical situations only. **Language note**: where explicit error values are idiomatic (Result/Either types, multiple return values), the faithful translation is "replace magic sentinel values with the idiomatic, hard-to-ignore error type", not "add exceptions".

### Replace Exception with Test
- **When**: An exception is raised and caught for a condition the caller could simply have checked beforehand.
- **Steps**: (1) Add a conditional for the edge case ahead of the protected block. (2) Move the handler's logic into that branch. (3) Make the handler fail loudly, then run the tests. (4) If it never fires, remove the try/catch.
- **Watch**: In some ecosystems attempting and handling failure is the idiom, and for races (checking a file exists, then opening it) it is more correct. The principle that holds everywhere: reserve the error mechanism for genuinely unexpected conditions.

---

## 6. Dealing with Generalization

Moving behavior along an inheritance hierarchy, creating and removing types in it, and trading inheritance for delegation. Without class inheritance, read "superclass" as the shared module, mixin, embedded struct, or default trait implementation that gives common logic a single home.

### Pull Up Field
- **When**: Subclasses hold the same field for the same purpose.
- **Steps**: Confirm the purpose truly matches; unify the names; declare it in the parent (protected if it was private); remove it from the subclasses.

### Pull Up Method
- **When**: Subclasses have methods doing the same work, or a subclass override essentially repeats the parent.
- **Steps**: (1) Make the bodies and signatures identical. (2) Copy to the parent. If it needs subclass-only members, either pull those up too or declare abstract accessors/methods for them in the parent. (3) Remove from the subclasses. (4) Check callers: some can now be typed against the parent.

### Pull Up Constructor Body
- **When**: Subclass constructors share mostly identical code.
- **Do**: Create a parent constructor with the common part, taking only the parameters it needs; subclass constructors call it first and then do their specifics.
- **Watch**: Constructors are usually not inherited, and many languages require the parent constructor call to come first, so arrange for the common code to sit at the beginning before extracting it.

### Push Down Method / Push Down Field
- **When**: A parent member matters to only one or a few subclasses, typically after planned generality failed to materialize or after functionality was extracted elsewhere.
- **Do**: Declare it in the subclasses that need it and remove it from the parent; confirm callers hold the right subtype.
- **Watch**: If several but not all subclasses need it, an intermediate parent avoids duplication. When pushing a field to several subclasses, accept the duplication only if they will genuinely evolve it separately.

### Extract Subclass
- **When**: Some features of a type are used only in certain cases.
- **Steps**: (1) Create the subclass. (2) Give it a constructor if it needs extra data, calling the parent's. (3) Replace parent constructor calls with the subclass's wherever the special case applies. (4) Push Down Method, then Push Down Field (methods first, so fields stay reachable throughout). (5) Delete any flag fields that used to select the behavior, replacing the conditionals on them with polymorphism.
- **Watch**: Inheritance gives you one axis. If the type varies along two independent dimensions (say size *and* coat), subclassing dead-ends at the first object that needs both; use composition (Strategy/Bridge) instead.

### Extract Superclass
- **When**: Two types share fields and methods.
- **Steps**: Create an abstract parent; Pull Up Field first (common methods need them), then Pull Up Method and Pull Up Constructor Body; look for client code that can now depend on the parent type.
- **Watch**: Impossible if the types already have different parents in a single-inheritance language; use Extract Class plus delegation instead.

### Extract Interface
- **When**: Several clients use the same subset of a type's operations, or two types share part of their interface, or a type plays distinct roles in different situations.
- **Steps**: Declare the interface with the shared operations; mark the types as implementing it; change client type declarations to the interface.
- **Watch**: This shares a *contract*, not *code*. It will not remove Duplicate Code; for that use Extract Class with delegation, or Extract Superclass.

### Collapse Hierarchy
- **When**: A subclass and its parent have become practically the same.
- **Steps**: Choose which one to remove; move everything into the survivor with Pull Up or Push Down; replace every use of the removed type (construction sites, type declarations, documentation); delete it.
- **Watch**: If the removed type had other children, they are re-parented onto the survivor. Check that this still makes sense; otherwise you create substitution violations (collapsing `Transport` into `Car` would make `Plane` a kind of `Car`).

### Form Template Method
- **When**: Subclasses implement algorithms with the same steps in the same order but differing details. Duplication is frequently at this structural level rather than copy-paste.
- **Steps**: (1) Break each subclass's algorithm into step methods. (2) Pull Up the steps that are identical. (3) Rename the differing steps consistently. (4) Declare the differing steps abstract in the parent; implementations stay in subclasses. (5) Pull Up the main method, which now calls only steps the parent knows about.
- **Payoff**: A new variant is a new subclass that fills in the steps. See Template Method in `patterns-behavioral.md`; in functional style, pass the varying steps as functions.

### Replace Inheritance with Delegation
- **When**: A subclass uses only part of its parent's interface, or the inheritance exists merely to share code and the subclass is not truly substitutable.
- **Steps**: (1) Add a field in the subclass for a parent-type object, initially pointing at itself. (2) Change the subclass's methods to go through that field. (3) For each inherited method that clients actually call, add a simple forwarding method. (4) Remove the inheritance declaration. (5) Initialize the field with a newly created object of the former parent.
- **Payoff**: No unwanted inherited operations leaking out, and the delegate can be swapped for other implementations, which is effectively Strategy. Cost: writing the forwarders.

### Replace Delegation with Inheritance
- **When**: A type forwards to *every* public method of exactly one other type and has no parent of its own.
- **Steps**: Make it a subclass of the delegate; point the delegate field at itself; delete the forwarders one at a time (unifying names first); replace remaining uses of the field with self; remove the field.
- **Watch**: Do not do this if only part of the delegate's interface is forwarded: that would violate substitutability.
