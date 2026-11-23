# Add-ons, Scripting, and Building Your Own Tools

Blender ships lean; since 4.2 most former bundled add-ons live on **extensions.blender.org** and must be installed (Edit → Preferences → Get Extensions, or `bpy.ops.extensions.package_install`). Check what's available before relying on it:

```python
import bpy, addon_utils
installed = sorted(m.__name__ for m in addon_utils.modules())
enabled = sorted(bpy.context.preferences.addons.keys())
result = {"blender": bpy.app.version_string, "enabled": enabled, "installed": installed}
```

If a needed add-on is absent, either ask the user to install it (one click), install a free extension yourself with the user's OK, or **write the operation with bmesh** — most modeling add-ons are convenience wrappers over things bmesh can do.

## Contents
1. Free add-ons & extensions
2. Paid add-ons (mention when relevant; verify installed)
3. Built-in tools people forget
4. bmesh recipes
5. Writing your own operator/panel
6. Geometry Nodes for procedural modeling
7. Headless / batch use

## 1. Free add-ons & extensions

| Name | Use for |
|---|---|
| **LoopTools** (extension; needed for Relax, Bridge, Curve, Gridfill) | Retopo and cleaning up loops. 5.2 builds in three of its tools, scriptable in Edit Mode without the extension: `mesh.circularize` (To Circle: make a boolean hole perfectly round), `mesh.space_edge_loops_evenly`, `mesh.flatten` |
| **Bool Tool** (extension) | Fast brush/auto booleans, Carver cutting tools, managing cutter collections |
| **F2** (extension) | Fill faces from one vert/edge — retopology speed |
| **3D Print Toolbox** (extension) | Non-manifold/intersection/thickness/overhang checks, volume, clean up, export to STL (3MF is not built in — it needs the separate 3MF Import/Export extension, `3d-printing.md` §6) |
| **Node Wrangler** (extension) | Fast PBR texture setup (Ctrl+Shift+T) for checking models with materials |
| **Ucupaint** (extension, GPL) | Layer-based texture painting for EEVEE/Cycles: image / solid-color / procedural / color-attribute layers with blend modes, opacity and masks, built as node groups on the material; bakes channels to images and flattens for export. Module `bl_ext.blender_org.ucupaint`, operators `bpy.ops.wm.y_*` (bake needs a UI session). Detect + wrappers: `scripts/ucupaint_ops.py`; details `texture-painting.md` §6 |
| **Native Texture / Vertex Paint** (built in) | Scripted strokes, fill, save: `scripts/paint_ops.py`; workflow and pitfalls `texture-painting.md` |
| **Human Base Meshes** / **Base Mesh Bundle** (Blender Studio asset library) | Rigged-ready starting meshes |
| **Extra Objects** (Mesh/Curve) | Gears, gems, pipe joints, math surfaces, bolts (Bolt Factory) |
| **Edit Mesh Tools** | Offset edges, extrude along path, vertex align, etc. |
| **Simple Lattice / Auto Mirror / Copy Attributes** | Deformation and mirroring helpers |
| **MeasureIt** | Dimension annotations for archviz/CAD checks |
| **Archipack / Archimesh** | Parametric walls/doors/windows/stairs for archviz blockouts |
| **Sapling Tree Gen** | Procedural trees (v0.3.7 needs 4.4+; verify it registers on 5.x — see `flora.md`) |
| **A.N.T. Landscape** | Noise terrain & displace (extension since 4.2, limited support) |
| **Quadriflow** (built in: Object Data → Remesh) | Auto quad retopology with target face count |
| **PolyQuilt** (free, GitHub) | Retopology pen tool |
| **BlenderKit** | Asset browser for base meshes/materials/HDRIs (check license) |
| **Rigify** (bundled) | Test deformation of your topology quickly |

## 2. Paid add-ons (mention when relevant; verify installed)

- **Hard Ops + Boxcutter** (hard surface: bevel/boolean/mesh-cleanup pipeline, cutting workflows) — detection, scripting limits, compatible recipes and hotkey hand-offs: `hard-ops.md`
- **MESHmachine** (fillets/chamfers/unbevel, boolean cleanup, normal transfer, plugs)
- **DECALmachine** (normal-map decals for detail on games/hard surface)
- **Quad Remesher** (best auto-retopo; also inside ZBrush as ZRemesher)
- **RetopoFlow** (dedicated retopo toolset: Contours, PolyStrips, Strokes)
- **SpeedSculpt / SpeedRetopo** (sculpt base-mesh and retopo helpers)
- **Fluent**, **KIT OPS** (kitbash/parametric hard-surface)
- **normalMagic / Abnormal** (custom normal editing)
- **Auto-Rig Pro** (test rigs), **Cloth Weaver**, **Simply Cloth** (garments)

Describe what they'd speed up; don't fabricate features or claim they're present.

## 3. Built-in tools people forget

Edit mode: Loop Cut & Slide, Offset Edge Slide, Inset (individual, thickness/depth), Bridge Edge Loops (twist/cuts/smoothness), Grid Fill (span/offset), Knife Project (cut with a curve/text silhouette), Bisect, Shear, To Sphere, Smooth Vertices, Poke Faces, Split Normals, Mark Sharp/Seam, Select Similar, Select Loops/Rings/Boundary/Non-Manifold/Interior Faces, Checker Deselect, Mesh → Clean Up (Merge by Distance, Limited Dissolve, Degenerate Dissolve, Make Planar, Fill Holes), Symmetrize / Snap to Symmetry, Proportional Editing with connected-only, Snapping to face with "Project Individual Elements" (retopo). Object mode: Join, Separate by Loose Parts/Material, Convert (curve/text ↔ mesh), Origin to geometry/3D cursor, Apply Transforms, Make Instances Real, Data linking (Alt+D), Collection instances, Overlays (Face Orientation, Wireframe, Statistics, Retopology), MatCaps and Cavity shading for form review, Measure tool, Edge length/angle overlays.

## 4. bmesh recipes

Use bmesh for reliable, selection-independent geometry edits from scripts (`from_mesh` → edit → `to_mesh` → `mesh.update()`; use `bmesh.from_edit_mesh` when in edit mode).

```python
import bpy, bmesh
from mathutils import Vector

def with_bmesh(obj, fn):
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    out = fn(bm)
    bm.to_mesh(me); bm.free(); me.update()
    return out

# Topology stats
def stats(bm):
    faces = {3: 0, 4: 0, 5: 0}
    for f in bm.faces: faces[min(len(f.verts), 5)] += 1
    poles = {}
    for v in bm.verts:
        n = len(v.link_edges)
        if n != 4 and n > 2: poles[n] = poles.get(n, 0) + 1
    nonman = [e for e in bm.edges if not e.is_manifold]
    return {"tris": faces[3], "quads": faces[4], "ngons": faces[5], "poles": poles, "non_manifold_edges": len(nonman)}

# Cleanup
def cleanup(bm, dist=1e-4, angle_deg=1.0):
    # dist: pass ~bbox diagonal * 1e-5 (mesh-repair.md §3); a fixed 1e-4 welds sub-mm detail. 1-5 deg for cleanup, up to 10 only for LODs
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=dist)
    bmesh.ops.dissolve_limit(bm, angle_limit=angle_deg*3.14159/180, verts=bm.verts, edges=bm.edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

# Bevel weight by angle (Blender 4.x float layer)
def weight_sharp_edges(bm, angle_deg=30):
    layer = bm.edges.layers.float.get("bevel_weight_edge") or bm.edges.layers.float.new("bevel_weight_edge")
    import math
    for e in bm.edges:
        if e.is_manifold and len(e.link_faces) == 2:
            a = e.calc_face_angle(0)
            e[layer] = 1.0 if a > math.radians(angle_deg) else 0.0

# Common ops: bmesh.ops.bevel, inset_region, extrude_face_region, bridge_loops, grid_fill, subdivide_edges,
# triangulate, join_triangles, symmetrize, bisect_plane, create_circle/cone/cube, solidify, wireframe, planar_faces
```

Modifier helpers:
```python
def add_mod(obj, name, kind, **props):
    m = obj.modifiers.new(name, kind)
    for k, v in props.items(): setattr(m, k, v)
    return m
# add_mod(obj, "Bevel", 'BEVEL', width=0.002, segments=3, limit_method='WEIGHT', harden_normals=True)
# add_mod(obj, "WN", 'WEIGHTED_NORMAL', keep_sharp=True); bpy.ops.object.shade_smooth()
# add_mod(obj, "Bool", 'BOOLEAN', operation='DIFFERENCE', object=cutter, solver='EXACT')
```

Viewport verification from script: `bpy.ops.object.mode_set(mode='OBJECT')`, set `space.shading.type='SOLID'`, `.show_wireframe`, `.light='MATCAP'`, `.cavity_type='BOTH'` on the VIEW_3D space, then `Blender:get_screenshot_of_area_as_image("VIEW_3D")`. Use `bpy.ops.view3d.view_axis(type='FRONT')` with a context override when you need specific ortho views.

**New faces have no normal yet.** A face made with `bm.faces.new(...)` reports `normal == (0, 0, 0)` until `bm.normal_update()` (or `face.normal_update()`); measured in a fresh 5.2 session. Orientation fixes such as `if f.normal.dot(to_centre) < 0: f.normal_flip()` then silently do nothing, and whole walls ship facing the wrong way (invisible under back-face culling, even though solid/Workbench viewport shading shows them). Call `bm.normal_update()` right before any loop that reads `f.normal`.

## 5. Writing your own operator/panel

When a task repeats (batch-bevel all hard-surface parts by angle, generate a bolt ring, check all meshes and color the bad ones, place reference images, build a stair from parameters), write it as an operator so it's reusable and undoable. Start from `scripts/addon_template.py`: it registers an `Operator` with properties (exposed in the redo panel), an `N`-panel button, and a `register()/unregister()` pair. Register it in the live session via `execute_blender_code` (run the file's text), then call `bpy.ops.model_helpers.<id>()`. Name your tools clearly, keep them idempotent, and say what you built in the reply so the user can keep it.

Good candidates for custom tools in modeling sessions:
- Topology linter that selects offending faces/verts (tris on curved areas, ≥6 poles, ngons) so you can *see* them.
- "Hard-surface prep": shade smooth + Smooth by Angle + Bevel(weight) + Weighted Normal for all selected.
- Reference image loader (already provided).
- Radial/linear fastener placer along an edge loop or on a face.
- LOD generator + tri-count report per LOD.
- Export-per-collection to FBX/GLB with correct axes and naming.

## 6. Geometry Nodes for procedural modeling

Use Geometry Nodes when counts/dimensions should stay editable (fences, stairs, bolt patterns, panel greebles, foliage scattering, cables). Ready-made: `scripts/scatter_on_surface.py` (surface scatter with masks); Blender 5.0+ also ships node-group modifiers (Array, Scatter on Surface, Curve to Tube, Instance on Elements…) — see `modifiers-and-curves.md` §6. Setting modifier inputs from code changed in 5.2 (`mod[identifier] = value` raises; look identifiers up in `node_group.interface.items_tree`): `modifiers-and-curves.md` §6. Build with `bpy.data.node_groups.new(name, 'GeometryNodeTree')`, add nodes via `nodes.new('GeometryNodeInstanceOnPoints')`, link with `links.new(a.outputs[0], b.inputs[0])`, and expose parameters on the group interface (`interface.new_socket(...)`). Convert to a real mesh (Apply modifier) only at export.

## 7. Headless / batch use

`Blender:execute_blender_code_for_cli(blend_file, code)` opens a file in background mode — use it for batch audits, exports and renders over many `.blend` files. Screenshots are unavailable headless; render to a path instead (`scene.render.filepath` + `bpy.ops.render.render(write_still=True)`). In the live session `Blender:render_viewport_to_path` renders the **scene camera**, not the viewport (`blender-bridges.md` §3); framed viewport captures come from `scripts/viewport_capture.py` (`blender-bridges.md` §7).

After `bpy.data.objects.remove()` in the same script, iterating `view_layer.objects` can yield `None` entries until `bpy.context.view_layer.update()` (measured, 5.2 headless); call it, or iterate `scene.objects`.

Blender 5.1+ embeds Python 3.13 and no longer loads the user site-packages directory, so a module installed with `pip install --user` is invisible to scripts run inside Blender. Start Blender with `--python-use-user-env` to load it (flag listed by `blender --help` in 5.2); this skill's Blender-side scripts need only the standard library, `bpy` and `numpy`.
