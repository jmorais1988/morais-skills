# Code Smells Catalog

A smell is a surface symptom suggesting a deeper structural problem. Smells accumulate gradually, usually because adding to what exists feels cheaper than creating something new. Left alone they compound until change becomes paralyzingly expensive, so treat them while small. A smell is a prompt to look, not proof of a defect: each entry lists when leaving it is the right call.

Technique names in **bold** are detailed in `refactoring-techniques.md`.

## Contents
- Bloaters: Long Method, Large Class, Primitive Obsession, Long Parameter List, Data Clumps
- Object-Orientation Abusers: Switch Statements, Temporary Field, Refused Bequest, Alternative Classes with Different Interfaces
- Change Preventers: Divergent Change, Shotgun Surgery, Parallel Inheritance Hierarchies
- Dispensables: Comments, Duplicate Code, Lazy Class, Data Class, Dead Code, Speculative Generality
- Couplers: Feature Envy, Inappropriate Intimacy, Message Chains, Middle Man
- Other: Incomplete Library Class

---

## Bloaters
Code that has grown too big to handle comfortably. Growth is incremental; nobody decides to write a 300-line function.

### Long Method
- **Signs**: Hard to take in at a glance. Anything past roughly ten lines deserves a second look. Inline comments acting as section headings are the strongest signal.
- **Cause**: It is mentally cheaper to add two lines to an existing function than to create a new one; repeat for years.
- **Treatment**:
  - **Extract Method** for any fragment you feel like commenting, even a single line, and name it after its intent.
  - If locals and parameters get in the way: **Replace Temp with Query**, **Introduce Parameter Object**, **Preserve Whole Object**.
  - If locals are hopelessly tangled: **Replace Method with Method Object**.
  - Conditionals: **Decompose Conditional**. Loops: extract the loop (or its body) into its own function.
- **Payoff**: Short, well-named functions are the longest-lived code. Long functions also hide duplication.
- **Note**: The call overhead is negligible in nearly all cases, and clear code is easier to optimize if it ever matters.

### Large Class
- **Signs**: Many fields, many methods, many lines; the type plays several roles.
- **Cause**: Same economics as Long Method, at type level.
- **Treatment**:
  - **Extract Class** when a subset of behavior forms its own component.
  - **Extract Subclass** when some behavior applies only in certain cases or comes in variants.
  - **Extract Interface** when it helps to spell out the operations particular clients use.
  - UI type holding domain data and logic: move those to a domain object; keep the two in sync with **Duplicate Observed Data** where duplication is unavoidable.
- **Payoff**: Less to hold in your head; splitting often exposes duplication.

### Primitive Obsession
- **Signs**: Built-in types standing in for domain concepts (money, ranges, phone numbers, identifiers); numeric or string constants encoding categories (`ROLE_ADMIN = 1`); string constants used as keys to simulate fields in a generic map or array.
- **Cause**: One more primitive field is always easier than a new type. Type codes appear when a concept is modeled as "a set of allowed numbers/strings".
- **Treatment**:
  - Group related primitives into their own type and move their behavior in: **Replace Data Value with Object**.
  - Primitives passed around as parameters: **Introduce Parameter Object** or **Preserve Whole Object**.
  - Type codes: **Replace Type Code with Class** (no behavioral effect), **with Subclasses**, or **with State/Strategy** (affects behavior).
  - Positional arrays/maps as records: **Replace Array with Object**.
- **Payoff**: Validation and operations live with the data; the type system starts catching mistakes; duplication becomes visible.

### Long Parameter List
- **Signs**: More than three or four parameters.
- **Cause**: Several algorithms merged into one function with parameters selecting among them; or an effort to decouple by making the caller create and pass in everything.
- **Treatment**:
  - Argument is just the result of calling something the function could call itself: **Replace Parameter with Method Call**.
  - Several arguments are all read off one object: **Preserve Whole Object**.
  - Arguments come from different sources but belong together: **Introduce Parameter Object**.
- **Ignore when**: Removing the parameters would create an unwanted dependency between types. Coupling is worse than a long list.

### Data Clumps
- **Signs**: The same few values show up together as fields in several types or as parameters in several signatures (host/port/user/password; start/end; x/y/z).
- **Test**: Delete one of the values mentally. If the rest no longer make sense, they are a single concept.
- **Treatment**: Fields: **Extract Class**. Parameters: **Introduce Parameter Object**, then **Preserve Whole Object** at call sites. Then look for behavior that should move into the new type.
- **Ignore when**: Passing the whole object would couple two types that are otherwise independent.

---

## Object-Orientation Abusers
Incomplete or incorrect use of polymorphism, encapsulation, and inheritance.

### Switch Statements
- **Signs**: A large `switch`/`match` or if-else ladder keyed on a type or mode, especially when the same branching appears in several places, so that adding a variant means hunting them all down.
- **Treatment**:
  - Isolate the conditional with **Extract Method**, put it where the data lives with **Move Method**.
  - Keyed on a type code: **Replace Type Code with Subclasses** or **with State/Strategy**, then **Replace Conditional with Polymorphism**.
  - Few branches, all calling the same function with different arguments: **Replace Parameter with Explicit Methods** is enough.
  - One branch handles "nothing there": **Introduce Null Object**.
- **First ask**: do new *variants* or new *operations* arrive more often? Polymorphism makes variants cheap and operations costly; branching does the reverse (see workflow step 6 in SKILL.md). Only proceed if variants are the axis that changes, or if nothing reports a forgotten branch.
- **Ignore when**: The switch does simple things and lives in one place; or it sits inside a factory choosing which implementation to create (one such switch is expected and fine). In languages with sum types and exhaustiveness checking, matching is often idiomatic; the smell is the *duplication* of the same match across the codebase.

### Temporary Field
- **Signs**: Fields that are populated only while one algorithm runs and are empty otherwise.
- **Cause**: Avoiding a long parameter list by parking algorithm inputs in fields.
- **Treatment**: Move the fields and the code using them into their own type (**Extract Class**, effectively a method object). Use **Introduce Null Object** to remove the "is it set?" checks.

### Refused Bequest
- **Signs**: A subclass uses only a little of what it inherits; inherited methods are left unused or overridden to throw.
- **Cause**: Inheritance used purely to grab some code, between types that are not really related.
- **Treatment**: No genuine is-a relationship: **Replace Inheritance with Delegation**. Relationship is sound but the parent is too broad: move what the subclass needs into a new common parent with **Extract Superclass**.

### Alternative Classes with Different Interfaces
- **Signs**: Two types do the same job with differently named operations.
- **Cause**: Someone did not know the first one existed.
- **Treatment**: Converge the interfaces with **Rename Method**, **Move Method**, **Add Parameter**, **Parameterize Method**. If only part overlaps, **Extract Superclass**. Then delete the redundant type if possible.
- **Ignore when**: The two types live in separate libraries you do not control. (An Adapter can still give them a common face.)

---

## Change Preventers
A change in one place forces changes in many others, making development progressively more expensive.

### Divergent Change
- **Signs**: One type gets edited for many unrelated reasons (adding a product type means touching its finding, displaying, *and* ordering code).
- **Treatment**: **Extract Class** along the lines of change. Shared behavior across resulting types: **Extract Superclass** / **Extract Subclass**.
- Mirror image of Shotgun Surgery: here *many kinds of change hit one type*.

### Shotgun Surgery
- **Signs**: One logical change requires small edits across many types.
- **Cause**: One responsibility smeared across many places, sometimes the result of splitting too eagerly.
- **Treatment**: Gather the behavior with **Move Method** and **Move Field** into one type (create one if none fits). Emptied-out types: **Inline Class**.

### Parallel Inheritance Hierarchies
- **Signs**: Every new subclass in one hierarchy requires a matching subclass in another.
- **Treatment**: Make instances of one hierarchy hold references to the other, then fold one hierarchy away using **Move Method** and **Move Field**.
- **Ignore when**: De-duplicating produces something uglier. Parallel hierarchies are sometimes the price of avoiding a worse mess; revert and live with it.

---

## Dispensables
Things whose removal would make the code cleaner and easier to understand.

### Comments
- **Signs**: A function dense with explanatory comments.
- **Cause**: The author sensed the code was not self-explanatory and masked it rather than fixing it.
- **Treatment**: Complex expression: **Extract Variable**. Commented section: **Extract Method**, often using the comment text as the name. Still unclear: **Rename Method**. Comment states a required condition: **Introduce Assertion**.
- **Keep when**: The comment explains *why* something is done a particular way, or documents a genuinely complex algorithm after simplification has been exhausted.

### Duplicate Code
- **Signs**: Fragments that look alike, or that look different but do the same job (subtler, harder to spot).
- **Cause**: Parallel work by people unaware of each other; copy-paste under deadline.
- **Treatment by location**:
  - Same type: **Extract Method**, call from both places.
  - Sibling subclasses: **Extract Method** in both, then **Pull Up Method** (and **Pull Up Field** for what it uses). In constructors: **Pull Up Constructor Body**. Similar but not identical: **Form Template Method**. Same result by different algorithms: pick the better one, **Substitute Algorithm**.
  - Unrelated types: **Extract Superclass**; if a common parent is impractical, **Extract Class** and have both use the new component.
  - Many conditions leading to the same action: **Consolidate Conditional Expression**, then extract the combined test.
  - Same statements in every branch: **Consolidate Duplicate Conditional Fragments**.
- **Ignore when**: Rarely, merging makes the code less obvious than the duplication did.

### Lazy Class
- **Signs**: A type that does too little to justify the cost of understanding it. Often a leftover after refactoring, or scaffolding for plans that never happened.
- **Treatment**: **Inline Class**; for thin subclasses, **Collapse Hierarchy**.
- **Ignore when**: It deliberately marks out a concept for imminent development. Balance clarity against simplicity.

### Data Class
- **Signs**: Only fields and accessors; all logic about that data lives in its clients.
- **Treatment**: **Encapsulate Field** for public fields; **Encapsulate Collection** for collections. Then study the clients: behavior that belongs with the data moves in via **Extract Method** + **Move Method**. Finally tighten access with **Remove Setting Method** and **Hide Method**.
- **Note**: A plain record is a normal starting point, and immutable data carriers (DTOs, messages, config) are legitimate in many architectures. The smell is behavior about that data being duplicated across its clients.

### Dead Code
- **Signs**: A variable, parameter, field, function, type, or conditional branch that is never used or reached.
- **Treatment**: Delete it; version control remembers. Tooling (IDE, linters, coverage) finds it fastest. Unneeded types: **Inline Class** / **Collapse Hierarchy**. Unneeded parameters: **Remove Parameter**.

### Speculative Generality
- **Signs**: Abstractions, hooks, parameters, or types created for a future that has not arrived.
- **Treatment**: Unused abstract parents: **Collapse Hierarchy**. Pointless delegation: **Inline Class**. Unused functions: **Inline Method** or delete. Unused parameters: **Remove Parameter**. Unused fields: delete.
- **Ignore when**: You are writing a framework or library whose users need those extension points. Before deleting, confirm the element is not used by tests.

---

## Couplers
Excessive coupling between types, or what happens when coupling is replaced by excessive delegation.

### Feature Envy
- **Signs**: A function reaches into another object's data more than it uses its own.
- **Cause**: Often appears right after data was moved out to a data class while the operations stayed behind.
- **Treatment**: Whole function belongs elsewhere: **Move Method**. Only part of it: **Extract Method**, then move that part. Uses several objects: place it with the one whose data it uses most, or split it.
- **Ignore when**: Behavior is intentionally held apart from data so it can vary independently (Strategy, Visitor, and similar).

### Inappropriate Intimacy
- **Signs**: One type uses another's internal fields and methods. Good types know as little about each other as possible.
- **Treatment**: **Move Method** / **Move Field** to where the parts are actually used (only if the original owner truly does not need them). Or make the relationship official: **Extract Class** + **Hide Delegate**. Mutual dependence: **Change Bidirectional Association to Unidirectional**. Between subclass and parent: consider **Replace Delegation with Inheritance** (or the reverse if the inheritance is the problem).

### Message Chains
- **Signs**: `a.getB().getC().getD()`. The client is coupled to the whole navigation path; any change along it breaks the client.
- **Treatment**: **Hide Delegate**. Better, ask what the client ultimately wants, **Extract Method** for that, and **Move Method** it to the start of the chain.
- **Ignore when**: Hiding would turn intermediate types into Middle Men and obscure where the work happens. Fluent builders and query/stream pipelines that return the same abstraction at each step are not this smell.

### Middle Man
- **Signs**: Most of a type's methods just forward to another object.
- **Cause**: Over-enthusiastic Hide Delegate, or a type whose real work has gradually migrated elsewhere.
- **Treatment**: **Remove Middle Man**: let clients talk to the delegate directly.
- **Ignore when**: The indirection exists on purpose: to break a dependency, or as a Proxy, Decorator, Facade, or Adapter.

---

## Other

### Incomplete Library Class
- **Signs**: A third-party type lacks something you need and you cannot change it.
- **Treatment**: One or two additions: **Introduce Foreign Method**. Many: **Introduce Local Extension** (subclass or wrapper). Where the language offers extension methods, traits, or similar, use them.
- **Cost**: Your extension must track library changes.
