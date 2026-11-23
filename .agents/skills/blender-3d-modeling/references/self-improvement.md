# Improving This Skill

This skill is a living toolset. Every job that produces a reusable tool, a verified fix, or exposes a gap should leave the skill better for the next, **unrelated** job — and carry no trace of the job that taught it. The user's work stays with the user; only the generalized lesson enters the skill.

## Contents
1. Triggers
2. What goes where
3. Generalize & anonymize (hard rule)
4. Quality bar
5. Process
6. Red flags

## 1. Triggers

Capture a **skill candidate** when any of these is observably true:

| Trigger | Example of the observable signal |
|---|---|
| You wrote a script, operator, node-group builder or shader recipe that would work on a different asset | it ran successfully and its inputs are parameters, not hardcoded names |
| Guidance was **missing** — you had to work out a technique the skill doesn't mention | you searched the skill (grep) and found nothing covering the situation |
| Guidance was **wrong or outdated** | an API name raised an error, a documented default changed, an example failed when run |
| A gate or review found a **defect class** the skill doesn't warn about | the defect would recur on other assets of the same class |
| The user corrected your approach in a way that applies beyond this job | "measure it, don't eyeball it", "check from the side view too" |
| You looked something up externally that the skill should have contained | docs page, release note, forum answer used to unblock yourself |
| You found a workaround for a tool/environment quirk | an MCP bridge, headless mode, OS path or version difference |

**Not skill material**: the user's preferences for *this* project (project notes/memory instead), one-off hacks tied to one file, taste calls, unverified hunches, anything you couldn't reproduce on a synthetic test.

## 2. What goes where

| Change | Destination |
|---|---|
| New reusable script/tool | `scripts/<verb_noun>.py` + a row in `references/scripts-index.md` + its name in the grouped **Scripts** list at the end of `SKILL.md` + a mention at the step where it's used in the relevant reference file |
| Missing technique in an existing domain | new subsection in that reference file + its Contents list |
| New domain (distinct trigger words and roughly 60+ lines of guidance) | new `references/<topic>.md` with a `## Contents` list + a row in the `SKILL.md` §3 routing table (subject | reference file | key scripts) + new trigger words in the `description` (keep frontmatter ≤ 1024 chars) + a `project_state.py` profile if it has its own step sequence |
| Wrong/outdated fact | fix in place, with the version boundary ("4.x: X; 5.0+: Y") |
| New defect class | that file's **Common failures**; if it is mechanically detectable, add a check to a gate script instead of (or besides) prose |
| External source consulted | `references/sources.md` |
| Every change | one line in `CHANGELOG.md` |

`SKILL.md` stays lean: it gets pointers and table rows; details live in references. Search before adding — extend the existing section rather than creating a parallel one.

## 3. Generalize & anonymize (hard rule)

A skill entry has exactly these parts: **situation class** (the kind of object/problem) → **what goes wrong or what's needed** → **technique** (settings, steps, code) → **verification** (how to check, with numbers from a synthetic test).

Transform every candidate before writing it:
1. **Name the class, not the instance.** Describe the category of object and problem. When an example helps, use a *different* object from the same class than the one in the job.
2. **Strip identifiers**: project, file, folder, scene, object, material, collection and asset names; client, brand, product, character and person names; usernames and absolute paths; job dates; the user's images, renders and reference photos; the user's dimensions, colors, counts and layouts. Keep numbers only when they are public standards (door heights, lane widths) or values you invented for a synthetic test.
3. **Evidence from synthetic tests only**: scripts build their own test geometry in a fresh headless session; never load, quote or screenshot the user's files for the skill.
4. **Stranger test**: could someone reading the entry infer what the user was building, for whom, or where their files live? If yes, abstract further.
5. **Lint**: `python scripts/skill_lint.py --deny "<distinctive terms from the current job>"` — pass the job's project/folder/asset/object/client/character names as deny terms. They're used only for the check and never written anywhere. Choose *distinctive* terms (proper nouns, codenames, file/object/script names, unusual compound words); generic class words the skill legitimately uses ("railing", "lens", "tower") only produce false hits — leave them out and rely on the stranger test for those.

| Job situation (never written into the skill) | Leaky entry ✗ | Generalized entry ✓ |
|---|---|---|
| Straps on a client's character kept tearing when the torso bent | "For <character>'s harness, bind the straps with Surface Deform…" | "Straps or belts that must follow a deforming body: bind with Surface Deform in the rest pose; Shrinkwrap alone slides and tears at bends. Check at 90° flexion." |
| A helper written to place spiral stairs in a building model, saved under the user's project path | "`<user path>/tools/stairs.py` for <project>" | "New script `spiral_stairs.py` in `scripts/` — parametric spiral stair (radius, rise, steps, rotation direction), tested headless on a synthetic cylinder; row added to `scripts-index.md` and the SKILL.md list." |
| The Blender bridge in one setup hung on a status request | "In <project> the MCP on the user's machine hung…" | "Some Blender MCP bridges only accept a raw code-execution request; if a status/info call hangs, send code execution directly." |
| A gate missed that one vehicle's wheels floated 3 cm above the ground | "the wheels of <vehicle model> floated 31 mm" | "Contact gates on parent/child pairs miss parts resting on a *ground* object; add an explicit ground-contact check for wheels, feet and bases." |

## 4. Quality bar

- **Scripts**: follow the house style of existing scripts (module docstring with usage; live use via an options dict set before exec → `result`; headless prints one tagged JSON line); dependencies limited to stdlib/bpy/numpy; idempotent; write only to paths passed in; never touch the live session unless run by the session owner; tested headless on synthetic data with measured results; limitations in the docstring.
- **Prose**: recipe/table form with concrete settings; version boundaries stated; untested claims marked `[unverified]`; one good example rather than several.
- **Consistency**: match the surrounding file's tone and structure; update Contents lists; keep cross-references (`see x.md §n`) valid.
- **Verification**: `scripts/skill_lint.py` must pass (registration, paths, section pointers `x.md §N` against real `## N.` headings, `## Contents` lists on references over 100 lines, script syntax, frontmatter size, `SKILL.md` size < 500 lines and < 20 000 bytes, leak scan).

## 5. Process

1. **During the job**: note candidates already in generalized form (a short list in your working notes/scratch space — not in the user's project and not in the skill yet). Don't interrupt the user's task to edit the skill unless the gap is blocking.
2. **After the user's deliverable is done**: apply the candidates.
   - **Additive changes** (new script + registration, new subsection, new failure, corrected fact, new source) → apply directly, then report them to the user in one or two lines so they can veto.
   - **Removing or rewriting existing rules, renaming/moving files, changing the description's meaning, restructuring** → propose first and apply only after the user agrees.
3. Optionally run it as a **skill-maintenance subagent lane** (`parallel-work-with-subagents.md`): its write scope is the skill directory only, and its input is only the generalized candidate list — it never receives the user's files, paths or images. This is the strongest privacy boundary.
4. Build and test new scripts headless on synthetic scenes; then run `skill_lint.py` (with the job's deny terms) and fix everything it reports.
5. Add a `CHANGELOG.md` line: date, change type, generalized summary.
6. Edit the copy of the skill that was loaded (its base directory). Leave mirrored or synced copies alone unless the user asks.
7. If you can't write files in this environment, give the user the proposed change as a patch or text block instead.

## 6. Red flags

| Thought | Reality |
|---|---|
| "Too small to add" | If you'd want it on the next job, it's three lines in the right file. |
| "The user's example makes it clearer" | Examples are the leak vector. Use a different object from the same class. |
| "I tested it on their scene, that's enough" | Evidence in the skill must come from a synthetic test you can rerun anywhere. |
| "I'll put the whole technique in SKILL.md" | SKILL.md gets a pointer or table row; details go to a reference. |
| "I'll update the skill now, then finish the job" | The user's deliverable comes first unless the gap blocks it. |
| "The script works, no need to register it" | An unregistered script is invisible to future jobs — add the `scripts-index.md` row and the SKILL.md list entry. |
| "This rule seems wrong, I'll delete it" | Propose removals to the user; add a version boundary or exception if you have evidence. |
