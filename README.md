# morais-skills

Personal collection of AI agent skills. Each skill lives in `.agents/skills/<name>/` with a `SKILL.md` (YAML frontmatter `name` + `description`) plus optional references and scripts.

| Skill | Purpose |
| --- | --- |
| `anymachine` | Reference-first order of work for building machines and many-part props in Blender as one build script |
| `auditing-3d-geometry` | Verify 3D models are connected, clean and match references before calling them done |
| `blender-3d-modeling` | Modeling, texturing, rigging, simulation, rendering and export in Blender |
| `code-design-refactoring` | Code smells, refactorings, SOLID and design patterns |
| `subagent-models` | Choosing model and reasoning effort for subagents |
| `unreal-engine-whats-new` | Unreal Engine 5.8/5.9 changes that postdate model training |

## Upstream-derived skills

| Skill | Upstream | Synced files | How |
| --- | --- | --- | --- |
| `anymachine` | [apekshik/anymachine](https://github.com/apekshik/anymachine) (MIT) | `PIPELINE.md` (verbatim; commit in `UPSTREAM`) | `.github/workflows/sync-anymachine.yml` runs `scripts/sync-anymachine.sh` daily and commits to `main` when `PIPELINE.md` changes; it re-enables itself each run so GitHub's 60-day inactivity cutoff doesn't stop it |

`SKILL.md` in these folders is ours and is never overwritten. The anymachine `SKILL.md` quotes the upstream README's generated-mesh steps by hand; the workflow does not track those.
