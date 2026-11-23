# Assembly, Hierarchy & Attachment

A model that may later be animated, exploded, picked, simulated, or broken must be an **assembly**, not a decorative lump. Build the hierarchy while modeling; retrofitting it is the most expensive rework there is. Gate it with `scripts/scene_gates.py`.

## Contents
1. Hierarchy pattern
2. Pivot rules
3. Attachment contract
4. Left/right pairs are mirrors
5. Colliders, sockets, destruction groups
6. Explodable & pickable: one definition of "a part"
7. Part coverage gate
8. Export considerations

## 1. Hierarchy pattern

```
<Asset>_ROOT              (Empty; whole-object transform; custom props: asset, version, units, budget)
├── <Asset>_Body          (mesh; macro part; origin = its pivot)
│   ├── <Asset>_Lid       (mesh; child; origin on the hinge axis)
│   ├── SOCKET_Handle     (Empty; named attachment point, local coords)
│   └── COL_Body          (mesh; simplified collider; in COLLIDERS collection, hidden)
├── <Asset>_Leg.L / .R    (mesh; mirrored pair)
└── REF, CUTTERS, _hp     (collections; excluded from export)
```

- One object per part that can move, break, be picked, or receives a distinct material family; surface relief (rivet rows, panel lines) stays on its shell as geometry or texture and is *not* a part.
- Parent with `Object (Keep Transform)`; keep children's origins at their semantic pivot, not at the mesh center (`bpy.context.scene.cursor.location = pivot; origin_set(type='ORIGIN_CURSOR')`).
- Collections mirror the hierarchy for visibility management; the object parent chain is what exporters and engines read.
- Store metadata as custom properties on the ROOT and parts (`obj["part_id"]`, `obj["contact_type"]`, `obj["collider_for"]`, `obj["destruction_group"]`) — the Blender equivalent of runtime `userData`. Exporters (glTF `extras`, FBX custom props) carry them.

## 2. Pivot rules

- **Center pivot** only when the part rotates about its center of mass (wheel, propeller, planet).
- **Base pivot** for upright props: trees, poles, bottles, signs, legs (contact point with the ground/parent).
- **Hinge pivot** on the hinge axis for lids, doors, jaws, flaps, levers, wings; align the local axis to the hinge (use `Transform → Align to Transform Orientation` or set the rotation then apply).
- **Root pivot** for organic appendages that bend from one end (tail, branch, horn).
- **Mechanical joint** wherever the reference shows one (bolt through a bracket = pivot at bolt axis).
Set the pivot before any animation test and before duplicating mirrored parts.

## 3. Attachment contract

Every child appendage, connector, handle, limb, branch, cable, panel, or hinged part must be *attached*, not merely placed near its parent. Record in NOTES.md / custom props:

- `parent`, `socket` (named contact region or `SOCKET_*` empty),
- `root` and `tip` points (parent-local) for anything elongated — build the part *from* root *to* tip; don't center it on an arbitrary transform,
- `base_radius` / `tip_radius` for tube-like parts,
- `contact_type`: `embedded` (penetrates the parent), `socket` (sits in a recess), `overlap` (flange over surface), `hinge`, `surface-contact` (rests on), `glued`,
- `embed_depth` or `overlap` amount, and `gap_tolerance` (max visible gap, e.g. 0.5 mm),
- evidence: which reference shows this join.

In Blender: embedded parts should overlap the parent by a few percent of their radius (then boolean-union only if the surface must be continuous — cast metal, organic flesh); socket parts get a matching recess cut in the parent; surface-contact parts get a contact shadow/AO and ideally a tiny bevel/fillet where they meet. Butt-joined parts with a hairline gap are the #1 "glued on" tell.

If the reference doesn't show how a part attaches, say so and pick the most plausible joint — never leave it floating.

## 4. Left/right pairs are mirrors

A `.L`/`.R` pair is a **reflection across the sagittal plane** — negate one axis only: `(x, y, z) → (−x, y, z)`. Rotating a copy 180° about the vertical axis negates two axes and preserves handedness: both hands come out as the same hand, both brackets have the bolt on the same side. It looks symmetric from the front and is wrong from above.

Blender: use the **Mirror modifier** (or `Symmetrize`) for true mirrors; for duplicated objects use `Ctrl+M` / `bpy.ops.transform.mirror` with the correct constraint axis, then **recalculate normals** — reflection inverts face winding, and un-flipped normals shade the mirrored limb as if lit from behind. Name pairs with Blender's `.L`/`.R` suffix so rig symmetrize and `scene_gates.py` recognize them. The gate can't catch a pair that's wrong the same way on both sides — compare that against the reference.

## 5. Colliders, sockets, destruction groups

- **Colliders**: primitive proxies first (box, sphere, capsule, cylinder), compound proxies for complex silhouettes, never the visual mesh unless asked. Keep them in a `COLLIDERS` collection, hidden, named `COL_<part>` (Unreal reads `UCX_<mesh>` on FBX import). Mark triggers separately (`obj["collider_kind"] = "trigger"`).
- **Sockets**: Empties named `SOCKET_<purpose>` parented to the relevant part (grip, muzzle, attachment rail, effect emitter). Engines import empties as transform nodes.
- **Destruction**: break along seams, material boundaries, joints, weak points; large fragments as detachable parts; small debris via Cell Fracture (add-on) only where it improves readability; keep material continuity on exposed fracture faces; add effect sockets at expected impact points; group fragments with `obj["destruction_group"]`.
- Store this intent even when no engine is attached yet — it's cheap now, expensive later.

## 6. Explodable & pickable: one definition of "a part"

The model should survive two tests without special cases: **explode** (move every part apart to show the assembly) and **pick** (click any surface → get a named part). Both must agree on what a part is:
- a named object with anonymous surface relief = one part;
- a named Empty containing named children = a container, not a part;
- surface relief that's a separate object must be flagged `obj["explode_with_parent"] = True`.

Explode by **scaling the arrangement about the root** (each part's pivot moves away from the center proportionally), not by translating every part the same distance (that moves the whole arrangement without opening gaps). `scene_gates.py --explode-preview` does this non-destructively for a screenshot.

## 7. Part coverage gate

`scene_gates.py --parts parts.json` compares the contract (`{"parts": ["Receiver", "Barrel", "Stock", ...]}`) to the scene:
- **FAIL**: a contract part with no object; two contract parts fused into one mesh (test: one object matched by multiple part names, or a loose-part count that doesn't fit).
- **WARN**: objects belonging to no named part; inventory details that never became geometry or a texture decision.
It proves you built what you planned — not that the plan was complete. Say that when reporting.

## 8. Export considerations

- Apply transforms on parts but keep the hierarchy; freeze pivots where the engine needs them.
- glTF: custom props → `extras` (enable "Custom Properties" in the exporter); Empties export as nodes. FBX: `use_custom_props=True`; colliders by `UCX_` naming for Unreal; check `bake_space_transform` for Y-up.
- Export from a clean collection: exclude `REF`, `CUTTERS`, `_hp`, `_source`, but include `COLLIDERS` if the engine wants them.
- Test the assembly once in the target (or in a fresh Blender file via import) — parenting and pivots are where exports silently break.
