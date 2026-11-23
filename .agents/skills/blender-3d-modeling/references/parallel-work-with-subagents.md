# Parallel Work with Subagents

A modeling job has long stretches of work that don't touch each other: gathering references for six components, generating and deriving texture sets, writing and testing a helper script, researching an engine's budget, modeling a prop that lives in its own file. Run those in parallel subagents; keep everything that mutates the shared scene in one pair of hands.

## Contents
1. The rule: disjoint write scopes, one Blender owner
2. Lanes: good lanes vs. never-parallel work
3. Dispatch recipe
4. Integration step (owner only)
5. Environment notes

## 1. The rule: disjoint write scopes, one Blender owner

**Parallelize only tasks whose write scopes are disjoint and whose inputs are already decided.** Before dispatching, write each lane's write scope (folders, files, `.blend`, datablock-name prefix) in one list and check it pairwise; any shared entry → those tasks run sequentially.

**One Blender owner.** The live Blender session (MCP socket, `execute_blender_code`) is a single process with one active object, one mode, one selection, one undo stack; MCP commands run serially on its main thread. Two agents driving it race on context (`mode_set`, active object, `temp_override` areas) and corrupt each other's work silently. The main agent owns the live session. A subagent that must run bpy works **headless on its own file** (`blender -b <lane>.blend --python ...`, or `execute_blender_code_for_cli`) and delivers a `.blend`/JSON/images; the owner integrates.

## 2. Lanes: good lanes vs. never-parallel work

| Parallel lane (good) | Exclusive write scope | Deliverable |
|---|---|---|
| Reference gathering per component | `references/0N_<component>/` + a lane manifest fragment | images + `manifest_<component>.json` + NOTES section draft |
| Reference *generation* (image-gen) for gaps | `references/0N_<component>/generated/` | images marked `generated: true` |
| Texture set per material (generate → `pbr_from_image.py` → previews) | `textures/<MAT_name>/` | map set + `PBR_REPORT` JSON + 2×2 tile preview |
| Helper script / add-on build + headless test | `scripts/<tool>.py` + its scratch dir | script + test log with numbers |
| Independent asset modeled headless (a crate, a rock kit, a tree variant) | `assets/<asset>.blend`, datablock prefix `<asset>_` | `.blend` + gate reports + turntable renders |
| Research (engine budgets, add-on availability, species anatomy) | none (report only) | cited notes |
| Read-only review of a saved snapshot | `review/<pass>/` | renders + discrepancy list with measurements |
| Baking maps from a saved copy | `bakes/<asset>/` | images + bake report |
| Large set: one district / city block per lane (after layout + kit spec are frozen) | `districts/<district>.blend`, prefix `<district>_` | linked-ready collection + review renders from the shared cameras |
| Modular kit: one piece family per lane (walls, floors, roofs, stairs) against a frozen grid spec | `kit/<family>.blend`, prefix `KIT_<family>_` | pieces + `tile_sockets.py` report for the family |
| Kitbash library: one part category per lane (panels, vents, pipes, greebles) | `library/<category>.blend` + its catalog entries | parts marked as assets + `asset_library.py audit` report |

**Never parallel**
- Anything that writes the live session, or two lanes writing the same `.blend`, object, material, node group, collection, or NOTES section.
- Sequential dependencies: blockout → detail, retopo → UVs → bake, rig → weights → pose sweep. A lane can't start from a stage that isn't finished and verified.
- Decisions that define consistency — palette, bevel-width standard, texel density, unit scale, naming scheme, style ratios, **grid module & pivot convention & socket profiles** (modular kits), **road/block layout & district boundaries** (cities). Decide them once, write them into NOTES.md, *then* fan out lanes that consume them read-only.
- Tiny tasks (one bpy call, one file read). Dispatch overhead exceeds the work; typical useful fan-out is 2–5 lanes.

## 3. Dispatch recipe

Send all independent lanes in one message so they run concurrently. Each prompt contains, in this order:

1. **Goal** — one sentence, the deliverable.
2. **Inputs (read-only)** — exact paths: NOTES.md sections, reference folders, the decided standards (scale, palette, texel density, naming).
3. **Write scope** — the exact folders/files/prefixes it may create or modify, and nothing else.
4. **Tool limits** — "headless Blender only: `<blender path> -b <file> --python <script>` (or `scripts/bridge_client.py run-cli`); never connect to the live session (its MCP tools, or its add-on socket, default port 9876 — see `blender-bridges.md` §2)". A lane that needs a UI context starts its own GUI instance, serving its own port if it must. Name the image-gen tool if the lane uses one.
5. **Method** — the skill reference file(s) to follow (e.g. `references/shader-nodes.md` §3) and the gates to run.
6. **Acceptance evidence** — what must exist when done: files, gate JSON, a render the lane has looked at, measured numbers.
7. **Report shape** — paths, numbers, open issues, what was *not* verified; under N words.

Research-only lanes get items 1, 2, 6, 7 and "do not modify local files".

## 4. Integration step (owner only)

1. Read every lane report; reject lanes without evidence (re-dispatch or do it yourself).
2. Append/link headless assets into the live scene: `with bpy.data.libraries.load(path, link=False) as (src, dst): dst.collections = [...]`. Appended datablocks that collide get `.001` suffixes — rename or remap (`ID.user_remap`) immediately; lane prefixes make collisions rare.
3. Build materials from delivered map sets with `scripts/build_pbr_material.py`.
4. Run the scene-level gates (`scene_gates.py` intersections/floating parts, budget totals) — lanes only verified their own piece.
5. Review the integrated result (`review-and-comparison.md`); record which lane produced what in the project state (`project_state.py mark ... --evidence <lane report>`).

## 5. Environment notes

- Claude Code: the `Agent` tool (background by default); several calls in one message run concurrently. Where no subagent tool exists, run the same lanes sequentially with the same write-scope discipline.
- Headless Blender cannot screenshot the viewport: lanes render to a path (Workbench/EEVEE for speed) and look at the image with an image-reading tool.
- Concurrent headless Blender processes are fine (separate processes, separate files); watch RAM with large scenes and Cycles bakes — limit render/bake lanes to what the machine can hold.
- Image-generation APIs may bill per image and run with concurrency limits — state the count per lane before dispatching when the provider charges.
