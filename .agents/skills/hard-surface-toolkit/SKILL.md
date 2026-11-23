---
name: hard-surface-toolkit
description: Scripted hard-surface technique and troubleshooting for Blender — cutters and booleans, bevel and weighted-normal stacks, support loops vs n-gons, mid-poly for games, plus a bpy toolkit (bx_hardsurface.py) with measurable shading and boolean gates and matcap contact sheets. Use when building or fixing the surfaces of a hard-surface part (panels, vents, machined or product parts, weapons, robot shells) and especially when shading smears on flat faces, a bevel vanishes after a boolean, a boolean empties the mesh or leaves holes, or edges pinch.
---

# Hard-surface toolkit

Vendored from [scenario-labs/skills](https://github.com/scenario-labs/skills) (MIT, see [vendor/LICENSE](vendor/LICENSE)). Covers **how a surface is cut, bevelled and shaded**. For the order of work on a whole machine use `anymachine`. For general Blender use `blender-3d-modeling`. Before you call anything done, run `auditing-3d-geometry`.

## Read first

1. [vendor/scenario-blender-hard-surface/UPSTREAM-SKILL.md](vendor/scenario-blender-hard-surface/UPSTREAM-SKILL.md) is the skill itself: stance, procedures, gates, failure table. Its `references/` (procedures, critique, expert notes) load on demand.
2. Its "required background" `scenario-blender-expert` is at [vendor/scenario-blender-expert/UPSTREAM-SKILL.md](vendor/scenario-blender-expert/UPSTREAM-SKILL.md). Read **section 1 (execution channel)** and the review loop. Skim the rest.

## Mapping upstream names to this repo

- `<skills>/scenario-blender-hard-surface/scripts` → `.agents/skills/hard-surface-toolkit/vendor/scenario-blender-hard-surface/scripts`. `bx_hardsurface.py` finds `bx_review`/`bx_audit` in the sibling `vendor/scenario-blender-expert/scripts` on its own. Keep the two folders side by side.
- Sibling skills it names (`scenario-blender-blockout`, `-retopology`, `-uv-baking`, `-texturing-shading`, the `scenario-blender` plugin skill, `skill_get`) are **not vendored**. Use `blender-3d-modeling` for those steps instead. Don't try to install them.
- **Execution channel:** upstream assumes the Scenario Blender Plugin's MCP. If a different Blender MCP is connected (for example blender-mcp's `execute_blender_code`), send the same bpy through it. With no bridge, run headless: `blender -b file.blend --factory-startup --python-exit-code 1 -P script.py`. The toolkit uses stock Blender only.

## Trust

`vendor/` is synced daily from upstream through a reviewed pull request (see README). Don't edit it here. Put local notes in this file.
