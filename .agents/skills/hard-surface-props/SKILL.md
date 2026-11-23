---
name: hard-surface-props
description: Game-art briefs for hard-surface props and vehicles driven live in Blender over an MCP bridge — sci-fi consoles, industrial and military props, weapons, spaceships, cars, trucks, aircraft, boats, mechs — with panel-line and greeble patterns, vehicle proportion blockout, object split, LOD targets and mechanical rigs (pistons, hinges, wheels). Use when the ask is an art-directed game asset or vehicle rather than a precise engineered part.
---

# Hard-surface props and vehicles

Vendored from [arjun988/blender-skills](https://github.com/arjun988/blender-skills) (MIT, see [vendor/LICENSE](vendor/LICENSE)). These are short design briefs. For the order of work on a many-part machine use `anymachine`. For how to cut, bevel and shade a surface, and for fixing shading, use `hard-surface-toolkit`. Before you call anything done, run `auditing-3d-geometry`.

## Pick the brief

- **Props, panels, greebles, mechanical surfaces** → [vendor/hard-surface/UPSTREAM-SKILL.md](vendor/hard-surface/UPSTREAM-SKILL.md), with [boolean-workflow](vendor/hard-surface/references/boolean-workflow.md) and [greeble-patterns](vendor/hard-surface/references/greeble-patterns.md).
- **Vehicles and mechs** → [vendor/vehicle-artist/UPSTREAM-SKILL.md](vendor/vehicle-artist/UPSTREAM-SKILL.md) and its `references/` (proportion blockout, object split, LOD targets).
- **Moving mechanical parts** → [vendor/rigging/references/mechanical-rig.md](vendor/rigging/references/mechanical-rig.md).

## Mapping upstream names to this repo

- Upstream drives Blender through [blender-mcp](https://github.com/ahujasid/blender-mcp) tools (`execute_blender_code`, `get_scene_info`, viewport screenshots). If that bridge isn't connected, run the same bpy headless with `blender -b ... -P script.py`.
- Related skills it names (`blender-modeler`, `materials`, `uv-workflow`, `asset-optimization`, `lod-pipeline`, `collision-proxy`, `export-pipeline`, `prop-artist`) are **not vendored**. Use `blender-3d-modeling` for those steps.

## Trust

`vendor/` is synced daily from upstream through a reviewed pull request (see README). Don't edit it here.
