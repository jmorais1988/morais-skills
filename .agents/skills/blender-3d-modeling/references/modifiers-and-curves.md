# Modifiers, Curves & Procedural Construction — pick by what the object IS

Most objects have a construction that is obviously right once you name the pattern: a belt is a cross-section repeated along a closed path; a spring is a circle swept along a helix; a fence is a post instanced at intervals along a curve. Modeling these by hand vertex-by-vertex is slower, less accurate, and impossible to edit. **Before building any part, look it up in the table below; if it matches, build it with that stack.** Keep the stack live until export (see `hard-surface-modeling.md` §5 for hard-surface stacks, `organic-modeling.md` §3 for organic stacks).

## Contents
1. Object → construction table
2. Stack order rules
3. Recipe: belt along a spline (tested in Blender 5.2)
4. Curve objects vs Geometry Nodes curves
5. Modifier cheat sheet (non-obvious settings)
6. Blender 5.x Geometry-Nodes-based modifiers
7. Common failures

## 1. Object → construction table

| Object / part | Pattern | Construction |
|---|---|---|
| Drive/timing/fan belt, conveyor belt, strap loop | unit repeated along closed path | Curve path (cyclic) + unit mesh → **Array (fixed count) → Curve** → Weld (§3) |
| Tank/tractor track, bicycle chain, watch band | rigid links along closed path | same as belt with a link/tread-plate unit; chain = 2-link unit (second link rotated 90° about X) |
| Cable, wire, hose, rope, vine, tentacle (static) | circular section swept along path | Curve with `bevel_depth` + `bevel_resolution` (or `bevel_mode='OBJECT'` custom profile); Hooks on end points to attach to sockets; 5.x **Curve to Tube** modifier |
| Twisted rope / braided cable | N strands twisted around an axis | 3 circles offset from center → Screw/array twist on a straight strip → Curve deform; or GN: Curve to Mesh with a multi-circle profile + tilt |
| Hanging cable with sag | catenary | Bezier with the middle point lowered (sag ≈ 2–5 % of span), or physics (cloth/soft body pinned ends) then apply |
| Spring, coil, thread, screw, auger, drill | profile swept on a helix | **Screw** modifier: profile offset from axis, `screw_offset` = pitch, `iterations` = turns; threads: triangle profile |
| Vase, bottle, wheel rim, lampshade, column, bowl, lathe parts | profile revolved | Screw modifier, `angle=360°`, `screw_offset=0`, `use_merge_vertices`, steps 32–64 |
| Pipe runs, handrails, tubular frames, roll cages | section along polyline with bends | Curve POLY/Bezier + bevel depth (radius the corners with handles), or Skin modifier on an edge skeleton |
| Fence, railing, guardrail posts, street lamps, poles along a road | instances at intervals along path | GN: Resample Curve (length) → Instance on Points, rotation from Curve Tangent (Align Rotation to Vector); 5.x **Array** modifier in curve mode |
| Stitching, seams on upholstery/leather/garments, rivet rows, weld beads along an edge | instances at fixed pitch along a curve that sits on a surface | Seam curve offset from the panel edge → GN **Curve to Points** (Length = pitch 3–4 mm) → snap to the panel (Geometry Proximity) + lift along its normal → **Instance on Points** with the Curve to Points Rotation (§3 "Stitches"; steering-wheel wraps and quilted-seat grooves: `hard-surface-categories.md` §2) |
| Bolt circle, spokes, petals, gear teeth, turbine blades, clock marks | radial repeat | Array with `use_object_offset` + Empty rotated 360°/n, relative offset off; or 5.x Array (circle) |
| Stairs, shelves, tiles, planks, windows on a façade | linear repeat | Array relative/constant offset (stairs: constant X *and* Z); 2D grids = two Arrays |
| Tire tread, bracelet, ring with pattern | strip bent into a circle | tread unit → Array along X to length = circumference → **Simple Deform Bend 360°** (or Curve onto a circle) |
| Leaf spring, bent tube, horn, tail, banana | straight part bent/tapered/twisted | Simple Deform (Bend/Taper/Twist) with an Empty as origin; Lattice for freeform |
| Sheet metal, walls, cloth, leaves, petals, bark shells | thin shell | model the surface → **Solidify** (even thickness, rim fill) |
| Grilles, meshes, cages, lattices, scaffolds | wire along edges | Wireframe modifier on a quad grid; Skin for thick struts |
| Straps, harnesses, decals, cladding conforming to a body | surface following another surface | Shrinkwrap (Project or Target Normal Project, offset) → Solidify; deforming target → Surface Deform |
| Terrain, rock surface detail, bark relief | height field | Subdivision/dense grid → **Displace** (texture, `texture_coords='OBJECT'`/'UV', midlevel, strength) — see `environment-modeling.md` |
| Ocean / large water | spectral waves | Ocean modifier (see `environment-modeling.md`) |
| Tree trunk & branches, creature armature blockout | tapered tubes from a skeleton | Skin modifier (per-vertex radius) + Subdivision |
| Organic blockout blobs | implicit surfaces | Metaballs → convert → Remesh |
| Scattered rocks, grass, debris, scales, studs | instances on a surface | GN Distribute Points on Faces → Instance on Points (`scripts/scatter_on_surface.py`, or 5.x Scatter on Surface modifier) |
| LODs, proxies | reduction | Decimate (Collapse ratio / Un-Subdivide / Planar), Remesh; for foliage LOD see `flora.md` |
| Moving attachments (cable ends, pistons, hydraulic rams) | constrained endpoints | Hook modifier on curve/mesh verts + object constraints (Damped Track/Stretch To) |

If a part matches no row, ask: *is it a section × path, a profile × revolution, a unit × repetition, a shell × thickness, or a height × surface?* One of those almost always fits hard-surface and many organic parts.

## 2. Stack order rules

Top → bottom: **generate** (Mirror, Array, Screw, Solidify, Boolean, Skin) → **refine** (Bevel, Subdivision) → **deform** (Curve, Simple Deform, Lattice, Shrinkwrap, Surface Deform, Armature) → **finish** (Weld, Weighted Normal, Triangulate at export).

- Array must come **before** Curve, or every copy deforms onto the same spot.
- Deformers bend only existing vertices: the unit needs edge loops along the deform axis (≥ 3–4 per unit around tight radii) or add Subdivision *before* the deformer. Faceted bends = too few loops, not a wrong modifier.
- Bevel before a deformer when bevel width must be uniform on the final shape; after it when you want the bevel computed on the deformed result (rarely).
- Mirror first; Weld last to close seams created by Array/Curve end-to-end joins. This is the order for hand-built stacks; Hard Ops sorts Mirror/Array *after* Booleans and Bevel so cuts repeat in every copy (`hard-ops.md` §3) — pick one order per object.
- Weighted Normal after anything that changes geometry.

## 3. Recipe: belt along a spline (tested in Blender 5.2)

The same recipe gives tank tracks and chains (swap the unit). Unit axes: **X along the belt, Y radial thickness, Z belt width** for a path in the XY plane (pulley axes along Z).

```python
import bpy, bmesh
# path: any closed curve around the pulleys; POLY or Bezier, cyclic, twist_mode MINIMUM (no flipping)
path = bpy.data.objects["CRV_BeltPath"]; sp = path.data.splines[0]
sp.use_cyclic_u = True; path.data.twist_mode = 'MINIMUM'
L = sp.calc_length()
pitch_target, thick, width = 0.008, 0.002, 0.012
n = round(L / pitch_target); pitch = L / n          # integer count → belt closes exactly

me = bpy.data.meshes.new("GEO_BeltUnit"); bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=(pitch, thick, width), verts=bm.verts)
bmesh.ops.translate(bm, vec=(pitch / 2, 0, 0), verts=bm.verts)   # unit spans x ∈ [0, pitch]
for x in (0.25, 0.5, 0.75):                                     # loops so it bends smoothly
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(pitch * x, 0, 0), plane_no=(1, 0, 0))
bmesh.ops.delete(bm, geom=[f for f in bm.faces if abs(f.normal.x) > 0.9], context='FACES_ONLY')  # open ends → copies merge into one tube
bm.to_mesh(me); bm.free()
belt = bpy.data.objects.new("GEO_Belt", me); bpy.context.scene.collection.objects.link(belt)
belt.matrix_world = path.matrix_world                           # same space as the path

arr = belt.modifiers.new("Array", 'ARRAY'); arr.fit_type = 'FIXED_COUNT'; arr.count = n
arr.relative_offset_displace = (1, 0, 0); arr.use_merge_vertices = True; arr.merge_threshold = pitch * 0.01
crv = belt.modifiers.new("Curve", 'CURVE'); crv.object = path; crv.deform_axis = 'POS_X'
weld = belt.modifiers.new("Weld", 'WELD'); weld.merge_threshold = pitch * 0.01   # joins last unit to first
```

Verified result (r = 100 mm and 50 mm pulleys 400 mm apart, 8 mm pitch): 160 units, one closed shell, 0 non-manifold edges, belt surface 97–101 mm from the pulley center. **Delete the unit's end faces** — otherwise Array's merge leaves a pair of coincident internal faces at every joint (4 non-manifold edges per unit). Teeth/tread: extrude the unit's inner face before arraying.

- **Animate** the belt running: drive the unit mesh's X offset (or the Curve modifier object's offset via a driver on the belt object's local X, wrapped modulo `pitch`); pulley rotation = distance / radius. For a simple textured belt, scroll the UV/Mapping X instead.
- **Where the path sits**: the unit is centered on the path, so the path is the belt's *neutral line* — radius = pulley contact radius (groove pitch radius) + thickness/2. Otherwise the belt sinks half its thickness into the pulley.
- **Two unequal pulleys**: two arcs joined by the external tangents; a Bezier with auto handles is not tangent-exact. Tested generator (centers (0,0) and (d,0), radii already offset as above):
  ```python
  import math
  def belt_path_points(r1, r2, d, n_arc=48):
      phi = math.asin((r1 - r2) / d)                 # external tangent angle
      a0, a1 = math.pi/2 + phi, 3*math.pi/2 - phi     # wrap around pulley 1
      b0, b1 = -math.pi/2 + phi, math.pi/2 + phi      # wrap around pulley 2
      pts  = [(r1*math.cos(a0 + (a1-a0)*i/n_arc), r1*math.sin(a0 + (a1-a0)*i/n_arc), 0) for i in range(n_arc + 1)]
      pts += [(d + r2*math.cos(b0 + (b1-b0)*i/n_arc), r2*math.sin(b0 + (b1-b0)*i/n_arc), 0) for i in range(n_arc + 1)]
      return pts   # straight runs are the implicit segments between the arcs
  cu = bpy.data.curves.new("CRV_BeltPath", 'CURVE'); cu.dimensions = '3D'
  sp = cu.splines.new('POLY'); pts = belt_path_points(0.10, 0.05, 0.40); sp.points.add(len(pts) - 1)
  for p, co in zip(sp.points, pts): p.co = (*co, 1.0)
  bpy.context.scene.collection.objects.link(bpy.data.objects.new("CRV_BeltPath", cu))
  ```
- **Tracks on uneven wheels / suspension**: Hook the path's control points to the wheel empties so the track follows the suspension.
- **Twisted belt (Möbius, figure-8)**: set point tilt (`point.tilt`) and `twist_mode='TANGENT'`.

### Stitches / seams along a panel edge (tested in Blender 5.2)

A seam curve drawn 5–8 mm in from the panel edge carries a Geometry Nodes modifier. Stitches are snapped onto the *evaluated* panel and lifted along its normal, so faceted or curved panels don't swallow them. Pitch is 3–4 mm for upholstery and leather, 2–3 mm for garments.

```python
ng = bpy.data.node_groups.new("GN_Stitches", 'GeometryNodeTree'); nd, L = ng.nodes, ng.links.new
for nm, st in (("Geometry", 'NodeSocketGeometry'), ("Pitch", 'NodeSocketFloat'), ("Lift", 'NodeSocketFloat'),
               ("Surface", 'NodeSocketObject'), ("Stitch", 'NodeSocketObject')):
    ng.interface.new_socket(nm, in_out='INPUT', socket_type=st)
ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
gi, go = nd.new('NodeGroupInput'), nd.new('NodeGroupOutput')
c2p = nd.new('GeometryNodeCurveToPoints'); c2p.mode = 'LENGTH'
L(gi.outputs["Geometry"], c2p.inputs["Curve"]); L(gi.outputs["Pitch"], c2p.inputs["Length"])
srf = nd.new('GeometryNodeObjectInfo'); srf.transform_space = 'RELATIVE'; L(gi.outputs["Surface"], srf.inputs["Object"])
prox = nd.new('GeometryNodeProximity'); prox.target_element = 'FACES'; L(srf.outputs["Geometry"], prox.inputs["Geometry"])
sns = nd.new('GeometryNodeSampleNearestSurface'); sns.data_type = 'FLOAT_VECTOR'
L(srf.outputs["Geometry"], sns.inputs["Mesh"]); L(nd.new('GeometryNodeInputNormal').outputs["Normal"], sns.inputs["Value"])
lift = nd.new('ShaderNodeVectorMath'); lift.operation = 'SCALE'; L(sns.outputs["Value"], lift.inputs[0]); L(gi.outputs["Lift"], lift.inputs["Scale"])
pos = nd.new('ShaderNodeVectorMath'); pos.operation = 'ADD'; L(prox.outputs["Position"], pos.inputs[0]); L(lift.outputs["Vector"], pos.inputs[1])
setp = nd.new('GeometryNodeSetPosition'); L(c2p.outputs["Points"], setp.inputs["Geometry"]); L(pos.outputs["Vector"], setp.inputs["Position"])
unit = nd.new('GeometryNodeObjectInfo'); L(gi.outputs["Stitch"], unit.inputs["Object"])
iop = nd.new('GeometryNodeInstanceOnPoints'); L(setp.outputs["Geometry"], iop.inputs["Points"])
L(unit.outputs["Geometry"], iop.inputs["Instance"]); L(c2p.outputs["Rotation"], iop.inputs["Rotation"])
real = nd.new('GeometryNodeRealizeInstances'); L(iop.outputs["Instances"], real.inputs["Geometry"]); L(real.outputs["Geometry"], go.inputs["Geometry"])

mod = seam.modifiers.new("Stitches", 'NODES'); mod.node_group = ng
ids = {i.name: i.identifier for i in ng.interface.items_tree if getattr(i, "in_out", None) == 'INPUT'}
for nm, v in (("Pitch", 0.0035), ("Lift", 0.0005 + 0.0004 / 2), ("Surface", panel), ("Stitch", stitch_unit)):
    getattr(mod.properties.inputs, ids[nm]).value = v        # 5.2: mod[identifier] = v raises TypeError
```

- **Unit axes**: Curve to Points' Rotation puts local **Z along the tangent** and X along the curve normal. Model the stitch with its *length on Z* (e.g. 0.4 × 0.6 × 2.5 mm for X/Y/Z). A unit modelled length-on-X stood on end and sank 0.75 mm into the panel.
- **Lift** = wanted gap + half the stitch thickness (the instance origin is its centre).
- **Count**: an open curve gives floor(L / pitch) + 1 stitches. Round the pitch to L/n when both ends must land exactly.
- Verified: 60° cylinder-section panel (r = 0.30 m, 60 × 40 quads), seam curve 6 mm above the edge, L = 314.16 mm, pitch 3.5 mm. Result: **90 stitches** (= floor(L/p) + 1), centres 0.70 mm off the surface, undersides **0.49–0.50 mm** clear of the faceted mesh, spacing 3.53–3.54 mm. The seam curve sat on the ideal cylinder, 0.011 mm above the facets; Geometry Proximity absorbs that.
- Drop Realize Instances to keep the stitches as lightweight instances. Thread detail smaller than the silhouette belongs in a normal map (`hard-surface-modeling.md` §6).

## 4. Curve objects vs Geometry Nodes curves

Logos, SVG paths and text → solid with exact size and a clamped bevel: `vector-and-text.md` §2 (`scripts/svg_to_solid.py`).

- **Curve object** (`bpy.data.curves`, type CURVE): bevel/extrude/taper built in, Curve & Hook modifiers target it, easy to edit. Best for cables, pipes, paths for Array+Curve.
  - `bevel_depth` = radius; `bevel_resolution` 2–6; `use_fill_caps`; `taper_object` (a curve whose Y profile scales radius along length — tapered tentacles, vines, horns); `bevel_mode='OBJECT'` for custom cross-sections (belt profiles, rails, moldings).
  - `resolution_u` controls evaluated smoothness; set per spline for poly count control.
  - Convert to mesh (`bpy.ops.object.convert(target='MESH')`) only at export; keep a `_source` copy.
- **Geometry Nodes curves** (Curves/hair objects or GN on curve objects): Resample Curve, Curve to Mesh (with profile curve and scale), Fillet Curve, Trim Curve, Set Curve Tilt/Radius, Instance on Points along curves with Curve Tangent. Best when counts/spacing must stay parametric (fences, cable bundles, vines on a wall) and for hair/fur (`fauna.md`).

## 5. Modifier cheat sheet (non-obvious settings)

Bevel and Weighted Normal (width, limit method, harden normals, width vs panel thickness): `hard-surface-modeling.md` §3; their place relative to deformers: §2.

- **Array**: `fit_type` FIXED_COUNT / FIT_LENGTH / FIT_CURVE; FIT_CURVE uses the curve's length but *doesn't* close cleanly — prefer computed integer count. `use_merge_vertices` + `use_merge_vertices_cap` for continuous surfaces; `start_cap`/`end_cap` objects for ends of chains and rails; `offset_u/v` to tile UVs per copy.
- **Curve**: `deform_axis` must be the unit's length axis; mesh and curve in the same space (equal transforms, applied scale); the curve's **radius** scales the mesh and **tilt** rotates it.
- **Screw**: `axis`, `angle`, `screw_offset` (pitch per full turn), `iterations`, `steps`/`render_steps`, `use_merge_vertices` (closes lathed seams), `use_normal_calculate` + `use_normal_flip` for inside-out results.
- **Simple Deform**: `deform_method` BEND/TAPER/TWIST/STRETCH, `origin` Empty sets pivot and axis, `limits` restrict the region, `deform_axis`.
- **Solidify**: `offset` −1 (inward) / 0 / +1, `use_even_offset`, `use_rim`, `use_flip_normals`; Complex mode for non-manifold edges; `thickness_vertex_group` for varying thickness (leaf thinner at edges).
- **Displace**: needs density; `texture_coords` OBJECT for world-stable noise, UV for painted maps; `mid_level` 0.5 for signed displacement; `direction` NORMAL vs Z (terrain: Z avoids overhang self-intersection).
- **Shrinkwrap**: `wrap_method` NEAREST_SURFACEPOINT (quick), PROJECT (along normal/axis, `use_negative_direction`), TARGET_PROJECT; `wrap_mode` ABOVE_SURFACE + `offset` to avoid z-fighting.
- **Skin**: mark a root vertex (Ctrl+A radius in edit mode), `use_smooth_shade`, follow with Subdivision 2.
- **Weld**: `mode` CONNECTED only merges along edges (safer for thin shells).
- **Decimate**: COLLAPSE with `use_symmetry`, `vertex_group` to protect silhouette areas; UNSUBDIV for grid-based meshes; DISSOLVE (planar) for hard surface.
- **Data Transfer**: Face Corner Data → Custom Normals from a proxy (foliage normals from a sphere/hemisphere → soft volumetric shading; hard-surface seams).
- **Hook**: `object` + vertex indices/vertex group; `falloff_type` for soft pulls on cables and lids.

Modifier helper for scripts: `add_mod(obj, name, kind, **props)` in `addons-and-scripting.md` §4.

## 6. Blender 5.x Geometry-Nodes-based modifiers

Blender 5.0 added built-in node-group modifiers (Add Modifier → Generate / Deform): **Array** (line, circle, curve, or custom transform, with gizmos and randomization; legacy Array remains), **Scatter on Surface** (Density or Amount, Random or Poisson Disk with minimum distance, distribution mask, instance object/collection with Pick Instance, viewport display percentage, Realize toggle), **Instance on Elements** (points/edges/faces/corners), **Randomize Instances**, **Curve to Tube** (round caps, generates UVs), **Geometry Input** (bring another object's evaluated geometry into the stack). 5.2 improved Array rotation alignment. Check `bpy.app.version >= (5, 0, 0)` before relying on them; they are node-group assets, so scripts add them via the asset (or build the equivalent graph — `scripts/scatter_on_surface.py` works on 4.2+).

Graphs built from code (5.2 facts were run in a 5.2.0 session unless marked *release notes*):
- **Modifier inputs** are RNA properties since 5.2: `mod.properties.inputs.<identifier>.value`, `.type = 'ATTRIBUTE'` + `.attribute_name` to read an attribute, `mod.properties.outputs.<identifier>.attribute_name` for output attributes; an input's `type` is `'VALUE'` or `'ATTRIBUTE'`, and `mod[identifier] = v` raises `TypeError` (worked example in the stitch recipe above).
- **Address sockets by name.** 5.2 changed the socket identifiers of the Compare and Random Value nodes (*release notes*); in 5.2 their enabled sockets are `A`, `B` → `Result` and `Min`, `Max`, `ID`, `Seed` → `Value`. Look sockets up by name and type on the live node, as `scripts/scatter_on_surface.py` does, instead of reusing identifiers from code written for an older version.
- **New mesh nodes (5.2)**: `GeometryNodeMeshBevel` (Mesh, Selection, Affect Kind, Offset, Segments, Shape, Profile → Mesh plus Vertex Face / Edge Face / Outer Edge / Mid Edge selections: a procedural bevel whose new faces can get their own material or UVs); `GeometryNodeClusterByDistance` / `GeometryNodeClusterByConnected` → `GeometryNodeMergePoints` (Merge by Distance split into steps, so the graph decides what welds); `GeometryNodeTransferAttributes` and `GeometryNodeRenameAttribute` (copy or rename UV, color and weight attributes between geometries). 5.1 (*release notes*; sockets present in 5.2): the UV Unwrap node gained the Minimum Stretch method and No Flip, Pack UV Islands a custom region (Bottom Left / Top Right), and `GeometryNodeBoneInfo` reads a bone's pose.
- **Empties take Geometry Nodes modifiers** (5.2), so a fully generated object needs no placeholder mesh. A mesh created from scratch inside the graph no longer inherits the original mesh data-block's name (5.2, *release notes*): match evaluated geometry by object name.

## 7. Common failures

- Hand-placing 160 belt teeth / 48 fence posts / 36 bolts instead of Array/instances — uneditable and slightly uneven.
- Array after Curve; Curve with unapplied scale on either object; unit length ≠ L/n → gap or overlap at the seam.
- Unit with no loops along the deform axis → faceted wrap.
- Bezier auto handles pretending to be tangent lines around pulleys → belt lifts off or cuts into the pulley.
- `twist_mode='Z_UP'` on a vertical path → the section flips 180° mid-run; use MINIMUM.
- Screw modifier with merge off → open seam on lathed objects; with iterations > 1 and offset 0 → overlapping duplicate geometry.
- Solidify on inconsistent normals → thickness goes both ways; recalc normals first.
- Converting curves to mesh early, then needing to change the path.
