---
name: auditing-3d-geometry
description: Use when reviewing, finishing, or claiming a 3D model (Blender, kitbash, hard-surface, vehicle, prop) matches a reference or is "done" - before saying parts are connected, clean, non-overlapping, or a percentage confident; also when a user reports overlapping, floating, buried, clipping, or badly blended parts.
---

# Auditing 3D Geometry

## Overview

Eyes at 5 m and bounding boxes cannot see a 1-5 cm penetration, a lens sunk into its bezel, or a
block that meets its neighbours at bare seams. **Only mesh-level tests and close-range isolated
shots count as evidence.** A confidence number stated without both is a guess.

## When to Use

- About to write "everything matches", "all parts connected", "N% confident"
- After adding, moving, scaling, or mirroring any part
- User says: overlapping, colliding, clipping, floating, buried, disconnected, "doesn't merge"
- Not for: sculpting/topology quality, UV/texture review (different problems)

## Procedure (do all four, in order)

1. **Run the tool.** `mesh_audit.py` (this folder) inside Blender - see its docstring. It reports
   INTERSECT (cross-assembly penetration), BURIED, FLOATING, GAP, ASYMMETRY, BELOWGROUND using BVH
   triangle overlap and ray-parity containment on evaluated meshes. Define `groups` for real
   assemblies (frame+crossmembers, wheel hub+rim); do not silence a hit by widening a group.
2. **Triage every INTERSECT/BURIED line** into one of: *defect* (fix), *hidden join* (both parts'
   overlap fully enclosed by a third solid, kitbash-acceptable), *seated part* (lens in bezel:
   acceptable ONLY if the receiving part has a matching recess, otherwise cut one with a boolean).
   Write the triage down; "expected nesting" without the enclosing part named is not a triage.
3. **Junction shots.** For every place three or more parts meet (cowl-mirror-windshield frame,
   bumper-fender-flare, tire-arch-flare) take an isolated shot at <= 1.5 m camera distance in
   SOLID and in WIREFRAME with x-ray, hiding everything but the parts and their neighbours
   (`viewport_shots.py`: `shot(name, view, mode, only=(...), dist=..., target=...)`).
   Look for: seam lines that outline a box, surfaces of one part passing through another, a
   part that stops short of what it should touch, primitives sharing no edge with their neighbour.
4. **Moving-part clearance.** Wheels, doors, steering, hinged/rotating parts must have measured
   clearance (>= 10 mm, or the reference's) from every non-assembly part. The tool reports
   contact; check the rest with an explicit min-distance query.

Claim done only when steps 1-4 produce zero unresolved defects and the triage list is written.

## Quick Reference

| Symptom in report | Usual cause | Fix |
|---|---|---|
| `INTERSECT tire <-> body/step/floor` | body panel or step modelled through wheel travel | move/shorten part, keep >= 10 mm clearance |
| `INTERSECT lens <-> bezel/ring` | stacked solids instead of a seated lens | boolean recess in bezel, lens thickness inside it |
| `BURIED small part <-> big block` | part placed inside a solid primitive (block, tub) | cut cavity or move part to the surface |
| `FLOATING` / `GAP` | mount forgotten, part scaled about wrong origin | add bracket/base or snap to surface |
| box seam lines at a junction | primitive placed, never blended | extend/bevel/merge or add trim covering the seam |
| `0 tri pairs` but `% inside` | open (non-watertight) mesh confuses containment | check report's open-mesh list; test the other way |

## Common Mistakes

- Trusting the axis-aligned bounding box: it cannot tell touching from penetrating.
- Judging close-ups at 4-9 m distance without isolating the parts.
- Excusing geometry with "at the stylized level" - style never licenses interpenetration.
- Editing object location/scale when the mesh is stored in world coordinates (part flies away).
- Stopping after the user's reported items instead of running the full audit again.
- Auditing a few merged meshes. The tool compares objects, so contacts *inside* one merged mesh, such as every strut of a generated frame merged per material, are invisible to it. Write one debug object per part, tagged by assembly, audit those, and delete them afterwards.
- Auditing objects hidden from render: `mesh_audit.run` skips `hide_render = True` objects, so the report shows "0 parts". Keep audit objects render-visible during the run.
- Computing a member's end as an offset in free space ("joint + 0.2 m up") instead of from the part it attaches to. This is the usual source of FLOATING/GAP on struts and legs. End members inside fittings, collars or balls.

## Generated rocks and organic props

- **Thickness and fold check before accepting a procedural prototype.** Cast a ray inward along -normal from every face; less than ~15% of the size means paper-thin. Adjacent faces more than ~150 deg apart mean a fold.
- **Build fractured rocks star-shaped.** Move each vertex only along its own direction, to the smooth minimum of the base radius and the fracture planes. Pushing along each plane's normal makes flaps.
- **Seat rocks on the lowest ground under their footprint, and cull fully buried faces.** A squashed base plate sticks out as a sheet on slopes.

## Red Flags - stop and run the procedure

- "The remaining hits are expected nesting"
- "Looks fine in the screenshot"
- "Stylized, so close enough"
- "I already checked that area" (after moving anything)
- Any confidence percentage before the tool has run on the current state
