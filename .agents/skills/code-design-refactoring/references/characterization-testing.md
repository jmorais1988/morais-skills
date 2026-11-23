# Characterization Testing Recipe

A characterization test asserts what the code **does today**, not what it *should* do. Its only job is to make any change in behavior visible while you restructure. Write these before refactoring code that has no tests (ground rule 10 in SKILL.md).

## The recipe

1. **Pick the boundary.** Test through the entry points your refactoring will *not* change (the public function, the HTTP handler, the CLI). Everything behind that boundary stays free to move. Tests that reach into private helpers will block the very restructuring they are meant to protect.

2. **Inventory every observable effect**, not just the return value:
   - return values and raised errors
   - mutations of the arguments passed in
   - calls made to collaborators (database, mailer, logger, HTTP), including their **order** and arguments
   - writes to globals, files, environment
   - dependence on time, randomness, generated IDs, locale

3. **Replace collaborators with recording fakes.** Small hand-written fakes that append each call to a list are better than a mocking framework here: they record everything in order, and they do not encode expectations about structure.

4. **Let the code tell you the answer.** Write the call with a deliberately wrong assertion, run it, read the actual value from the failure, and paste it in. You are documenting, not judging. If the value looks wrong, keep it and flag it (step 9).

5. **Choose inputs by reading the branches.** One case per branch, plus for every comparison: exactly at the boundary, just below, just above. Add the awkward ones: empty, null or missing, zero, negative, an unknown enum or type-code value, duplicates. Include at least one *malformed* input that makes the code crash (a missing key or field): a crash is behavior too, and what matters is which side effects happened before it. A coverage tool shows which branches your cases never reached.

6. **Pin failure paths and their partial effects.** When the operation fails halfway, which side effects had already happened? (Was the log written, the balance reduced, the email sent?) These are the behaviors most likely to be reordered by accident during a refactoring, typically by hoisting a computation that can fail above a side effect that used to precede it.

7. **Assert exactly.** Exact equality, even for floating-point results and formatted strings. Tolerances hide precisely the kind of change you are trying to detect, such as a reordered arithmetic expression. Loosen later, deliberately.

8. **Make the suite switchable between old and new.** Select the implementation under test with an environment variable, a parameter, or a build tag, so the *identical* tests run against both versions. "Same tests, green on both" is the evidence that this was a refactoring.

9. **Label quirks.** Name or comment tests that pin suspicious behavior (`quirk: discount logged even when payment fails`). When someone later fixes the bug, the failing test tells them it was known and intentional to change.

10. **Tame non-determinism.** Inject the clock, random source, and ID generator, or normalize them out of the output before comparing.

## Variations

- **Golden master / snapshot.** For large outputs (reports, generated files, rendered markup), capture the whole output for a broad set of inputs and diff against it. Cheap to build; noisy to maintain; ideal as temporary scaffolding.
- **Differential testing.** Keep the old implementation callable as an oracle, generate many random or recorded real inputs, and assert `new(x) == old(x)`. Excellent for Substitute Algorithm and for pure functions. Delete the oracle when done.
- **Shadow comparison in production.** At system scale, run old and new side by side on live traffic, serve the old result, and log mismatches. See `legacy-and-large-scale.md`.

## Sanity checks

- **Break it on purpose.** Flip a condition or change a constant in the original and confirm a test fails. A suite that cannot fail protects nothing.
- **Watch for over-specification.** If a harmless internal reordering breaks a test, that test was pinned below the boundary; move it up.

## Afterwards

Characterization tests are scaffolding. Once the structure is clean, replace the valuable ones with intention-revealing unit tests of the newly extracted pieces (pure functions are now easy to test directly), keep a few end-to-end ones as regression cover, and delete those that only pin accidental detail.

## When you cannot test at all

Shrink the steps and lean on other nets: the compiler and type checker, automated IDE or tool-driven refactorings (far safer than hand edits), copying signatures exactly rather than retyping them, reviewing each diff in isolation, and committing after every step so any one can be reverted. Say clearly to the user that verification was limited to these.
