# Hard Ops (paid hard-surface add-on)

Hard Ops (HOps) is an interactive hard-surface toolkit: menus, hotkeys and modal tools that automate Blender's own Bevel, Boolean, Mirror, Array, Solidify, Weighted Normal and edge-marking workflows. It is built for a human with a mouse. An agent driving Blender through code can **detect** it, **call a few one-shot operators**, **build objects in its conventions** so the user can keep working with it, and **hand interactive tools to the user** — but should build most geometry with plain bpy. Facts below were verified against Hard Ops 26.1.7 on Blender 5.2 unless marked `[unverified]`; each Hard Ops build targets a Blender version range, so re-check after updates.

## Contents
1. Detect, and enable only with consent
2. What to call from code (tested)
3. Hard Ops-compatible recipes in plain bpy (tested)
4. Handing interactive tools to the user
5. State and preferences that change results
6. Blender 4.1+ / 5.x notes
7. Common mistakes

## 1. Detect, and enable only with consent

```python
import bpy, addon_utils
is_hops = lambda name: name.split(".")[-1].lower() in ("hardops", "hops")
installed = [m.__name__ for m in addon_utils.modules() if is_hops(m.__name__)]   # e.g. bl_ext.<repo>.hardops (4.2+ extension)
enabled = [k for k in bpy.context.preferences.addons.keys() if is_hops(k)]
version = next((getattr(m, "bl_info", {}).get("version") for m in addon_utils.modules() if is_hops(m.__name__)), None)
result = {"installed": installed, "enabled": enabled, "version": version,
          "ops_available": hasattr(bpy.ops, "hops") and hasattr(bpy.ops.hops, "soft_sharpen")}
```

- **Installed but disabled** → ask the user before enabling. Enabling registers global hotkeys that replace Blender defaults (Q, Shift+Q, Alt+M, Alt+V, Alt+X, Ctrl+Numpad operators…) and, with auto-save preferences on, persists. `bpy.ops.preferences.addon_enable(module=<name>)` once they agree.
- **Not installed** → don't recommend buying it for a task plain bpy handles; mention it only if the user works interactively in hard surface.
- **Headless/background sessions (subagent lanes)**: Hard Ops fails to import without a GPU context (it builds draw shaders at import). A throwaway `--factory-startup` session can load it with `gpu.init()` followed by `addon_utils.enable(name, default_set=True, persistent=False)` and `preferences.use_preferences_save = False`, but its operators then raise errors from their on-screen notification drawing. **Don't use Hard Ops in headless lanes** — use the recipes in §3.

## 2. What to call from code (tested)

Of ~341 registered operators, ~89 are modal (wait for mouse/keyboard) and many others read the mouse event in `invoke()`. **Results depend on how you call them**:

**Live GUI session, `INVOKE_DEFAULT` inside a 3D View override (window + VIEW_3D area + WINDOW region) — tested on synthetic hard-surface parts, all FINISHED with no errors:**

| Operator | What it actually did |
|---|---|
| `hops.soft_sharpen` | kept existing sharp marks, added **bevel weight and crease** on the same edges (crease affects any later Subdivision), added a *Smooth by Angle* modifier (named with a `!!` prefix so Hard Ops' sort keeps it last) |
| `hops.complex_sharpen` | added Bevel **width 0.02 m (absolute), 3 segments, ANGLE limit 30°, profile 0.7, clamp overlap off**; sharp + bevel weight + crease marks; Smooth by Angle; `hops.status` stayed UNDEFINED |
| `hops.step` | non-destructive: kept the first Bevel, added a second Bevel at ~45 % of its width, 6 segments, ANGLE 60°; removed the Smooth by Angle modifier |
| `hops.mod_weighted_normal` | Weighted Normal (Face Area, Keep Sharp) inserted *above* the Smooth by Angle modifier |
| `hops.bool_difference` (cutter + target selected, target active) | Boolean DIFFERENCE with the preference solver (Fast/Float by default); cutter set to wire, hidden in renders, moved to `Cutters`, status BOOLSHAPE, **not parented**; clean through-cut, no stray objects (the duplicate seen headless is a background-mode artifact); Exact gave the same volume on a simple cut |

So in a live session these tools are usable from code — **but their defaults are absolute and blind to part size** (see §7: thin panels). After each call, check bevel width against the part's thickness and the evaluated mesh for zero-area faces.

**Headless / `EXEC_DEFAULT` without a UI** (synthetic cubes, background session):

| Operator | Result | Use from code? |
|---|---|---|
| `hops.soft_sharpen` (sSharpen) | FINISHED: smooth shading, edges above the sharpness angle marked sharp **and** bevel-weighted, *Smooth by Angle* modifier added | yes |
| `hops.mod_subdivision` | FINISHED: Subdivision modifier | yes (or plain bpy) |
| `hops.clean_reorigin` | FINISHED: apply/convert, remove doubles, recenter origin — destructive | yes, after saving a version |
| `hops.mod_weighted_normal` | adds Weighted Normal (Face Area, Keep Sharp) + Smooth by Angle, then errors while drawing its notification when there is no UI | effect ok; verify result |
| `hops.bool_difference` / `bool_union` / `bool_intersect` / `slash` / `bool_inset` | Boolean modifier with the preference solver (default Fast/Float), cutter set to wire; then a notification error; headless run also left an extra duplicate object with Solidify + Intersect boolean `[unverified in a GUI session]` | prefer §3 |
| `hops.step` | added a Bevel (6 segments, Angle limit) then errored | prefer §3 |
| `hops.complex_sharpen` (cSharpen), `hops.mod_triangulate`, `hops.mod_lattice`, `hops.cut_in` | AttributeError — state is set only in `invoke()` from the mouse event | no (use §3 or hand to user) |
| `hops.bev_multi`, `hops.apply_modifiers` (Smart Apply), `hops.sharp_n` | PASS_THROUGH — invoke-only, nothing happens | no |
| `hops.complex_split_boolean` | crashes on Blender 5.2 (API change) | no |
| Modal tools: bevel helper/bWidth, `bool_modal`, dice, mirror/array gizmos, mod scroll, hopsTool, Q/pie menus | need live mouse interaction | never from code — hand to the user (§4) |

Rules when calling any `bpy.ops.hops.*` in the live session (prefer `INVOKE_DEFAULT` for invoke+execute operators; it runs the same path as a click with the current modifier-key state):
- Object mode, active + selected meshes set explicitly, applied scale; call inside `bpy.context.temp_override(window=..., area=<VIEW_3D area>, region=<its WINDOW region>, active_object=..., selected_objects=[...])` so notification drawing has a region.
- Never start a modal operator from code: it waits for input and leaves the UI in a modal state.
- After every call, **verify** the modifier stack, edge attributes (`sharp_edge`, `bevel_weight_edge`) and new/hidden objects; undo (`bpy.ops.ed.undo()`) or remove leftovers if the result isn't what you expected.

## 3. Hard Ops-compatible recipes in plain bpy (tested)

These reproduce the Hard Ops conventions deterministically — the user can continue on the result with Hard Ops' interactive tools (it reads `obj.hops.status`, the `Cutters` collection and the modifier order). Hard Ops creates and reads its own `Cutters` collection; hand-built cutters elsewhere in this skill live in `CUTTERS` (`hard-surface-modeling.md` §2) — keep the two apart. Tested on Blender 5.2 with and without Hard Ops enabled.

<!-- hops-recipe -->
```python
import bpy, bmesh, math

STACK_ORDER = {'BOOLEAN': 0, 'BEVEL': 1, 'MIRROR': 2, 'ARRAY': 2, 'NODES': 3, 'WEIGHTED_NORMAL': 4, 'TRIANGULATE': 5}

def sort_stack(obj):
    """Booleans → Bevel → Mirror/Array (cuts repeat in copies) → smoothing → Weighted Normal → Triangulate."""
    wanted = sorted(obj.modifiers, key=lambda m: STACK_ORDER.get(m.type, 1))
    for i, m in enumerate(wanted):
        obj.modifiers.move(obj.modifiers.find(m.name), i)

def set_status(obj, status):
    if hasattr(obj, "hops"):              # only when Hard Ops is enabled
        obj.hops.status = status          # UNDEFINED | CSHARP | CSTEP | BOOLSHAPE | BOOLSHAPE2

def hops_boolean(target, cutter, operation='DIFFERENCE', solver='EXACT'):
    col = bpy.data.collections.get("Cutters") or bpy.data.collections.new("Cutters")
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    for c in list(cutter.users_collection):
        c.objects.unlink(cutter)
    col.objects.link(cutter)
    bpy.context.view_layer.update()       # new objects have a stale (identity) matrix_world until evaluated
    mw = cutter.matrix_world.copy(); cutter.parent = target; cutter.matrix_world = mw
    cutter.display_type = 'WIRE'; cutter.hide_render = True
    set_status(cutter, 'BOOLSHAPE')
    mod = target.modifiers.new(f"{operation.title()} {cutter.name}", 'BOOLEAN')
    mod.operation, mod.object, mod.solver = operation, cutter, solver
    sort_stack(target)
    return mod

def hops_csharpen(obj, angle_deg=30.0, width=0.02, segments=3, profile=0.7):
    """cSharpen equivalent: smooth faces, sharp + bevel weight on edges above angle, weight-limited Bevel, Weighted Normal."""
    bm = bmesh.new(); bm.from_mesh(obj.data)
    bw = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    limit = math.radians(angle_deg)
    for e in bm.edges:
        sharp = len(e.link_faces) == 2 and e.calc_face_angle(0.0) > limit
        e.smooth = not sharp
        e[bw] = 1.0 if sharp else 0.0
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(obj.data); bm.free()
    bev = obj.modifiers.get("Bevel") or obj.modifiers.new("Bevel", 'BEVEL')
    bev.limit_method, bev.width, bev.segments, bev.profile = 'WEIGHT', width, segments, profile
    wn = obj.modifiers.get("WeightedNormal") or obj.modifiers.new("WeightedNormal", 'WEIGHTED_NORMAL')
    wn.mode, wn.keep_sharp = 'FACE_AREA', True
    sort_stack(obj); set_status(obj, 'CSHARP')

def hops_step(obj, width_factor=0.5, segments=2, angle_deg=60.0):
    """Step equivalent: apply booleans + current bevel, clear weights, add a smaller angle-limited bevel."""
    prev = None
    with bpy.context.temp_override(object=obj, active_object=obj):
        for m in [m for m in obj.modifiers if m.type in ('BOOLEAN', 'BEVEL')]:
            if m.type == 'BEVEL':
                prev = m.width
            bpy.ops.object.modifier_apply(modifier=m.name)
    attr = obj.data.attributes.get("bevel_weight_edge")
    if attr:
        obj.data.attributes.remove(attr)
    bev = obj.modifiers.new("Bevel Step", 'BEVEL')
    bev.limit_method, bev.angle_limit = 'ANGLE', math.radians(angle_deg)
    bev.width, bev.segments, bev.profile = (prev or 0.02) * width_factor, segments, 0.7
    sort_stack(obj); set_status(obj, 'CSTEP')
```
<!-- /hops-recipe -->

- Bevel width is absolute: apply scale first and pick widths from the object size (`hard-surface-modeling.md` §3); Hard Ops' 0.02 default suits ~1–2 m parts.
- Hard Ops' own boolean helpers default to the **Fast/Float** solver; the recipe uses **Exact** for correctness — switch to Fast only for simple convex cutters or speed.
- Stack order differs from "Mirror first" advice in `hard-surface-modeling.md` §2: with Mirror/Array *after* booleans the cuts repeat in every copy (Hard Ops' sort); with Mirror first, cutters must be placed on both sides. Pick one per object and keep it consistent.
- Keep cutters live until export; applying (`hops_step`) is a deliberate, versioned step.

## 4. Handing interactive tools to the user

When a step is faster by hand, tell the user which tool and hotkey to use, what to aim for (numbers), and what you'll check afterwards. Default hotkeys registered by Hard Ops 26 (users can remap):

| Hotkey | Tool |
|---|---|
| Q / Shift+Q | Hard Ops main menu / pie menu (context-sensitive) |
| Ctrl+` | Helper panel (modifiers, bevel settings, workflow status) |
| Shift+Alt+B | Bevel helper; Ctrl+Shift+B multi-bevel (modal width/segments adjust) |
| Alt+X | Mirror gizmo |
| Ctrl+Numpad − / + / * / / | Boolean difference / union / intersect / slash (object mode; select cutter(s) then target) |
| Shift+Alt+Numpad / | Inset boolean |
| Ctrl+Alt+Numpad − / + | Edit-mode boolean difference / union (selected geometry cuts the rest) |
| Alt+M / Alt+V | Material menu / viewport & render settings menu |
| Shift+Alt+W | hopsTool (topbar tool) |
| Ctrl+K | Hard Ops preferences helper |

Hand-off template: "Select the cutter, then the body, press Ctrl+Numpad − (boolean difference), then Shift+Alt+B and drag the bevel to about 2 mm, 3 segments. Tell me when done — I'll check the modifier stack and shading."

## 5. State and preferences that change results

- `obj.hops.status` (UNDEFINED / CSHARP / CSTEP / BOOLSHAPE / BOOLSHAPE2): tools behave differently per status (e.g. bevel helper uses Weight limit on CSHARP/CSTEP, Angle limit on undefined meshes; Smart Apply applies booleans only on CSHARP). Set it when building with §3 so hand-offs behave as the user expects.
- Preferences (Hard Ops add-on preferences): boolean solver (default = first solver in Blender's list, Fast/Float on 5.x), global sharpness angle, "sharpening uses crease" (on by default — marks crease too, which affects Subdivision), bevel defaults (width, segments, profile), modifier sorting during boolean operations.
- Read preferences before relying on defaults: `bpy.context.preferences.addons[<module>].preferences` (property names differ by version — inspect, don't assume).

## 6. Blender 4.1+ / 5.x notes

- Auto Smooth was removed in 4.1: old "autosmooth 30/60°" advice now means the *Smooth by Angle* modifier or explicitly marked sharp edges. Duplicate *Smooth by Angle* modifiers/node groups can pile up after many Hard Ops operations — remove extras and keep one before Weighted Normal.
- Weighted Normal must stay last (Keep Sharp on). Bevel *Harden Normals* changed in 4.1 (verified behaviour: `hard-surface-modeling.md` §3); on Hard Ops stacks rely on the Weighted Normal modifier it adds.
- Changes made by scripts through a code-execution bridge may leave `bpy.data.is_dirty` False (observed), so Blender won't prompt to save on close — back up before testing, and save or revert deliberately; tell the user which.
- Hard Ops releases track Blender versions; after a Blender update, re-run detection and a quick smoke test (one `soft_sharpen` on a test cube) before planning on it.

## 7. Common mistakes

- Calling modal or invoke-only Hard Ops operators from code and assuming they worked (PASS_THROUGH or silent partial results).
- Enabling Hard Ops without asking (hotkey conflicts, persistent preference change).
- Using Hard Ops in headless/background lanes.
- Open/planar cutters (no volume) → boolean artifacts; give them Solidify or close them.
- Cutters left visible in renders or outside the `Cutters` collection; applying booleans too early.
- A second bevel at 30° re-catching the first bevel (use ≥ 60° for stepped bevels).
- **Absolute bevel defaults on thin panels**: cSharpen/Step add fixed widths (0.02 m, then ~45 % of that) whatever the part size, so on sheet parts the bevel folds through the panel (clamp overlap off — a ridged double lip standing proud) or collapses into zero-area faces (clamp on). After any Hard Ops bevel tool, set each width to ≤ ~40 % of that part's thickness and re-run both evaluated-mesh checks (rule and measured counts: `hard-surface-modeling.md` §3).
- Duplicate *Smooth by Angle* modifiers piling up, or Weighted Normal not last (§6).
