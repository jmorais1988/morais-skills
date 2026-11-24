# morais-skills

Personal collection of AI agent skills. Each skill lives in `.agents/skills/<name>/` with a `SKILL.md` (YAML frontmatter `name` + `description`) plus optional references and scripts.

| Skill | Purpose |
| --- | --- |
| `anymachine` | Reference-first order of work for building machines and many-part props in Blender as one build script |
| `auditing-3d-geometry` | Verify 3D models are connected, clean and match references before calling them done |
| `blender-3d-modeling` | Modeling, texturing, rigging, simulation, rendering and export in Blender |
| `code-design-refactoring` | Code smells, refactorings, SOLID and design patterns |
| `hard-surface-props` | Game-art briefs for hard-surface props, vehicles and mechanical rigs driven over a Blender MCP |
| `hard-surface-toolkit` | Cutters, bevels and weighted normals for hard-surface parts, with a bpy toolkit and shading gates |
| `image-to-sculpt` | One image to a watertight sculpt measured against it, with registered generated views, Blender replay, films and exports |
| `subagent-models` | Choosing model and reasoning effort for subagents |
| `text-to-cad` | When to use parametric CAD (build123d, STEP, manufacturing checks) instead of Blender, and how to install the text-to-cad plugin |
| `unreal-engine-whats-new` | Unreal Engine 5.8/5.9 changes that postdate model training |

## Upstream-derived skills

| Skill | Upstream | Vendored files |
| --- | --- | --- |
| `anymachine` | [apekshik/anymachine](https://github.com/apekshik/anymachine) (MIT) | `PIPELINE.md`, `LICENSE` |
| `hard-surface-toolkit` | [scenario-labs/skills](https://github.com/scenario-labs/skills) (MIT) | `vendor/`: `scenario-blender-hard-surface` and `scenario-blender-expert` (docs and bpy scripts), `LICENSE` |
| `hard-surface-props` | [arjun988/blender-skills](https://github.com/arjun988/blender-skills) (MIT) | `vendor/`: `hard-surface`, `vehicle-artist`, `rigging/references/mechanical-rig.md`, `LICENSE` |
| `image-to-sculpt` | [gokayfem/image-to-sculpt](https://github.com/gokayfem/image-to-sculpt) (MIT) | `vendor/`: `image-to-sculpt` (skill, references, templates, `i2s` CLI and Blender script), `LICENSE` |
| `text-to-cad` | [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) (MIT) | None. It's a plugin that needs its `cad` CLI, so the skill only routes to it and explains how to install it |

Each skill's `UPSTREAM` file lists its repo, the commit the files match, and `path=<upstream>:<local>` lines. `scripts/sync-upstream.sh` mirrors those paths (sparse, shallow clone) and stores any vendored `SKILL.md` as `UPSTREAM-SKILL.md`, so agents don't load it as a second skill. Our own top-level `SKILL.md` is never overwritten. To vendor another skill, add an `UPSTREAM` file and run the script.

`.github/workflows/sync-upstream.yml` runs the script daily. If anything changed, it pushes the change to the `sync/upstream` branch and opens or updates a pull request. Claude (through `anthropics/claude-code-action`) then reviews the diff for risky code, prompt injection and broken links, and comments with a verdict. Merging is always done by hand. The workflow re-enables itself each run so GitHub's 60-day inactivity cutoff doesn't stop it. It needs the repo setting "Allow GitHub Actions to create and approve pull requests" and an `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` secret.
