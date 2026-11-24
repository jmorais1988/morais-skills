---
name: image-to-sculpt
description: Turn one image (AI render, photo of a figurine or product, drawing, or an idea rendered first) into a watertight 3D sculpt that is measured against that image — front maps (mask, metric depth, normals), registered and screened generated views, a visual hull, recorded fit passes, Blender replay, timelapse/turntable films and GLB/OBJ/STL export — via the `i2s.py` CLI. Use when the person wants a 3D model or sculpt "from this image", a figurine or character turned into a mesh, a sculpting timelapse, or a check of a 3D model against a reference image. Not for scenes or rooms, text-to-3D with no image, rigging, PBR texturing or CAD-accurate parts.
---

# Image to sculpt

Vendored from [gokayfem/image-to-sculpt](https://github.com/gokayfem/image-to-sculpt) (MIT, see [vendor/LICENSE](vendor/LICENSE)). For hard-surface machines use `anymachine` / `hard-surface-toolkit`; for exact-dimension parts use `text-to-cad`; for cleanup, retopology, UVs or rigging after the sculpt use `blender-3d-modeling`. Before calling a mesh done, run `auditing-3d-geometry`.

## Read first

[vendor/image-to-sculpt/UPSTREAM-SKILL.md](vendor/image-to-sculpt/UPSTREAM-SKILL.md) is the skill itself: input routing, the 8-step workflow, hard rules. Its `references/` load on demand.

## Mapping upstream names to this repo

- `scripts/i2s.py` → `.agents/skills/image-to-sculpt/vendor/image-to-sculpt/scripts/i2s.py`. On Windows call it with `python`, not `python3`.
- Python deps first: `numpy scipy scikit-image Pillow`, plus `fal-client` (paid steps) and `matplotlib` (report chart). Install into a venv, not system Python. Without numpy even `doctor` fails on import.
- Then `i2s.py doctor`: it checks the packages, Blender (5.2+, via `$BLENDER` or PATH), `ffmpeg` and whether `FAL_KEY` is set (without printing it).
- `i2s.py demo DIR` runs the whole pipeline offline on a synthetic subject: use it to prove the install before spending anything.

## Local overrides

- **Paid calls need a yes first.** `prep`, `views`, `parts`, `imagine` and `run` call fal (about $2 per typical case). Before the first paid call in a case, tell the person the estimate and the case budget (`new --budget`, default $4), and wait for a go-ahead. Never raise the budget or rerun a paid stage without asking.
- No `FAL_KEY`: offer the free path (cut-out PNG plus their own photos via `views --import`, or front-only) rather than asking them to set up a key.
- Never print, echo or write `FAL_KEY`, including in logs or reports.
- Put cases outside this repo (for example in the person's project folder). They hold large images, meshes and films.
- Show the checkpoint images (mask, normals, views sheet, map sheets, a turntable frame) to the person; don't summarise them from numbers alone.

## Trust

`vendor/` is synced daily from upstream through a reviewed pull request (see README). Don't edit it here. Put local notes in this file.
