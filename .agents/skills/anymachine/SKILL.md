---
name: anymachine
description: Reference-first pipeline for building a machine or a many-part hard-surface object in Blender as one Python build script — reference sheets, parts breakdown, build, check renders, rig and animation, export and verify. Use when planning or starting a rigged machine (drone, vehicle, robot, anything with working joints), a static prop with many real parts, or a rig of 0–1 parameters on a generated mesh.
---

# AnyMachine

Vendored from [apekshik/anymachine](https://github.com/apekshik/anymachine) (MIT). This skill fixes the **order of work**; `blender-3d-modeling` is how to do each step in Blender, and `auditing-3d-geometry` gates any claim that the result is done or matches its references. For surface technique (cutters, bevels, shading fixes) use `hard-surface-toolkit`. For art-directed props and vehicles use `hard-surface-props`. For parts that must be manufactured to dimension use `text-to-cad`.

## Pick the route

- **Machine that moves, built from references** → [PIPELINE.md](PIPELINE.md), Part 1 (steps 1–10).
- **Static object with a lot on it** → [PIPELINE.md](PIPELINE.md), Part 2.
- **Everyday object rigged on a generated mesh** (a lid on a hinge, legs that walk). Not in PIPELINE.md; from the upstream README:
  1. **Generate** the object in an articulated pose (Meshy and Tripo, both tried).
  2. **Treat the mesh as a skin.** Measure the joint axes off it, then rebuild the moving parts as clean geometry on those axes: coaxial hinge barrels, side-by-side joint slabs, so nothing can pass through anything.
  3. **Expose parameters.** Each joint gets a 0-1 custom property with drivers and limits, and bakes to linear glTF actions, so `seek(t = value)` poses the GLB in any engine.
  4. **Check.** Sweep every parameter for triangle overlaps, clamp out-of-range values, measure foot slip, then re-import the GLB to confirm it matches.

Read the chosen part of PIPELINE.md in full before writing geometry, and stop for the person's approval where it says to.

## Worked examples

PIPELINE.md links to `stilt/`, `hardsurface/` and other folders that are **not vendored**. They resolve against the upstream repo at the commit in [UPSTREAM](UPSTREAM); fetch a file from there when you need to copy a script such as `build_stilt.py`, `verify_glb.py`, `hs.py` or a `jobs_*.json` template.
