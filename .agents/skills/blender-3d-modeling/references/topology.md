# Topology

Topology is how vertices, edges and faces are connected — independent of shape. It decides whether a mesh subdivides cleanly, deforms without pinching, unwraps sanely, and decimates/LODs predictably. Audit it every pass with `scripts/mesh_report.py`.

## Contents
0. Surface class → technique (decide this first)
1. What good topology looks like
2. Quads, triangles, ngons
3. Poles
4. Edge flow for deformation
5. Density
6. Manifold & hygiene rules
7. Edge cases and how to resolve them
8. Retopology workflow (organic → clean quads)
9. Audit checklist (run before calling any stage done)

## 0. Surface class → technique (decide this first)

Before choosing a primitive or a modifier stack, classify *what kind of surface* each part is. The most common geometry mismatch is structural, not a matter of polish: a smoothly tapering blade built as a box, a cable as a stack of cylinders, a continuous organic bulge as glued primitives. Size doesn't change the class; surface behaviour does.

| Class | Looks like | Build with | Never |
|---|---|---|---|
| **continuous-sculpt** | one smoothly varying volume, no seams: horn, muscle mass, vessel, worn stone, blade | sculpt (remesh) + retopo; lathe/Screw for revolved; curve-sweep/Skin for tapered tubes; subd cage | box/cylinder stacks that merely abut |
| **assembled-solid** | rigid part with faces you can count: crate, canister, chassis panel, receiver | primitives + booleans + bevels | sculpting it soft |
| **conforming-shell** | thin skin following another form: cowling, fitted cloth, armor plate, phone case | Shrinkwrap over the base form + Solidify; or offset duplicate of the base's faces | independent solid with its own volume |
| **surface-relief** | changes the surface but not the silhouette-defining volume: ridges, panel lines, rivets, embossing | geometry only if it alters the silhouette at viewing distance; otherwise normal/bump/decal | modelling every rivet on a background prop |
| **fiber-strand** | long, thin, path-following or repeated: cable, rope, vine, hair clump, wire | Curve + bevel depth, tube along path, instanced clusters, hair curves | box or flat card (except game hair cards) |
| **material-only** | no geometric footprint: printed logo, sticker, painted marking | texture/decal on the parent; a thin carrier only if it has a visible edge | cutting it into the mesh |

Decision order: material-only? → fiber-strand? → silhouette affected only by fine relief? → countable hard faces (assembled-solid)? → thin skin over another form (conforming-shell)? → otherwise continuous-sculpt. Record the class per component in `references/NOTES.md`; it also predicts the topology rules that apply (continuous-sculpt and conforming-shell need quad flow; assembled-solid tolerates ngons on flat faces).

## 1. What good topology looks like

- **Quad-dominant** with edges that follow the surface's form: contour lines on organic shapes, panel/feature lines on hard surface.
- **Even density** relative to curvature: more polys where the surface bends or deforms, fewer where it's flat.
- **Loops** — continuous rings of edges — around every feature that moves or reads as a distinct form (eyes, mouth, joints, a button, a wheel arch).
- **Few poles**, placed on flat, non-deforming, low-visibility areas.
- **Watertight** where it needs to be, clean normals, no duplicate/degenerate geometry.
- **Readable**: someone else can tell what a loop does. Random crisscrossing edges are the tell of bad topology.

Bad topology: ngons on curved surfaces, long thin triangles ("slivers"), spiraling loops (a loop that doesn't close on itself), star-poles at joints, dense mesh on flat planes, overlapping faces, hidden interior geometry, terminating loops that create pinching.

## 2. Quads, triangles, ngons

| Face type | Fine when | Avoid when |
|---|---|---|
| **Quad** | Always the default. Subdivides predictably, loops flow through, deforms evenly, unwraps cleanly. | — |
| **Triangle** | Final game-export meshes (GPUs render tris anyway); flat areas; terminating a loop on a flat plane; hidden spots. | On curved subdivided surfaces (creates a 3-pole → pinching); at joints; anywhere a loop needs to continue. |
| **Ngon** | Perfectly flat faces in non-deforming hard surface (a flat panel with boolean holes) as long as it stays flat and isn't subdivided or exported as-is to an engine that needs triangulation. | Anything curved, anything under Subdivision Surface (creates an N-pole in the center), anything that deforms, game exports without controlled triangulation. |

Rule of thumb: model in quads; let tris/ngons exist only on flat, hidden, static faces, and triangulate deliberately (Triangulate modifier, "Beauty"/"Fixed" methods) at export so the engine doesn't choose for you.

## 3. Poles

A pole is a vertex with ≠4 edges. Every closed quad mesh needs some — the problem is where they are and how many.

- **E-pole (5 edges)** and **N-pole (3 edges)** are unavoidable and fine when placed on flat areas or areas that don't deform.
- Poles under Subdivision create density changes → pinching/artifacts. Poles at joints → creases and collapsing when the joint bends.
- **6+ edges**: almost always a mistake (result of merging loops carelessly or dissolving). Redirect loops instead.
- Place poles: cheek (not lip corner), top of skull, back of a hand, where cylinder meets flat plane away from the edge.
- Use poles *on purpose* to turn edge flow: e.g. two E-poles let a loop around an eye peel off into the loop around the mouth.

## 4. Edge flow for deformation

Rig-ready meshes need loops that mimic how the surface stretches and compresses:

- **Face**: concentric loops around each eye and around the mouth; a loop from nose bridge around the nasolabial fold; loops following the jaw and the brow. Typically 8–12 loops around eye/mouth for animation-quality faces (fewer for games).
- **Joints (knee, elbow, finger)**: at least 3 loops across the bend — one at the joint center, one either side — biased so there's more geometry on the outside of the bend (it stretches) than the inside (it compresses). Shoulder needs radial loops flowing from armpit to neck.
- **Torso/hips**: loops following the pelvis crease and the belly.
- **Hard-surface deforming parts** (hoses, cables, treads, cloth straps): even quad rings along the length.
- Avoid: triangles at joints; a pole exactly at a joint center; loops that spiral instead of closing.

Static hard-surface models don't need this — that freedom is why booleans/ngons are acceptable there.

## 5. Density

- Match density to curvature, not uniformly. Cylinder: 8 sides for mobile bolts, 16–32 for hero props, 64+ for high-poly bake sources. Sphere: use quad spheres (cube + subdivision + cast) rather than UV spheres when you'll subdivide/deform.
- Silhouette first: spend polygons where the outline of the object bends. Interior flat faces can be almost empty.
- Transition density with quad reduction patterns (e.g. 4→2 via a diamond, 3→1 via a pair of poles) placed on flat areas — not with random triangles.
- Micro-triangles (smaller than a pixel on screen) cost GPU time while adding nothing; remove them on game assets.

## 6. Manifold & hygiene rules

Non-manifold geometry breaks booleans, sculpting, 3D printing, some engines, and shading. Check `mesh_report.py` for:

- Edges with 1 face (holes) or 3+ faces (internal faces) → fill / delete interior.
- Loose verts/edges → delete.
- Duplicate vertices → Merge by Distance (`bmesh.ops.remove_doubles`) with a **size-relative** threshold ≈ bbox diagonal × 1e-5, never a fixed 0.0001 m (it welds sub-mm features — measured in `mesh-repair.md` §3) — and never on intentionally split-normal edges.
- Zero-area/degenerate faces → dissolve degenerate.
- Inverted normals → recalc outside; inspect face orientation overlay (blue = out, red = in).
- Unapplied scale/rotation on objects → apply before bevels, booleans, export.
- Overlapping/coplanar faces (z-fighting) → remove.
- Concave ngons / self-intersecting faces → split.

## 7. Edge cases and how to resolve them

- **Cylinder into flat surface** (pipe into wall, bolt into plate): either boolean + bevel + weighted normals (hard surface, static) or manually route loops: give the plane a grid whose loop count matches the cylinder's sides (or half, with a redirect), and keep the ngon-free ring one loop away from the cylinder.
- **Hole in a curved surface**: use booleans only if you won't subdivide; otherwise inset an even-sided loop and bridge. Keep supporting loops around the hole.
- **Many loops into few** (arm into torso, tower into building): use the reduction patterns on a flat-ish area; never terminate loops as a fan of triangles on a curve.
- **Sharp edges under Subdivision**: add support loops (Bevel with 2 segments and profile 1.0, or Loop Cut) rather than creasing everything — creases (`edge crease`) work but stop artifacts less cleanly on curved edges.
- **Shading errors on flat ngon faces** after boolean: the face isn't perfectly planar, or normals are being averaged with the side faces. Fix: make planar (`bmesh.ops.planar_faces`), Auto Smooth by angle (Blender 4.1+: "Shade Auto Smooth"/Smooth by Angle modifier), add Weighted Normal modifier, or bevel the edge.
- **Long thin faces** after boolean intersecting near an existing edge: slide the boolean object so cuts land mid-face, or dissolve the sliver and re-cut.
- **Mirror seam artifacts**: verts on the mirror plane must sit at x=0 exactly; enable Clipping and Merge on the Mirror modifier; remove any face crossing the plane.
- **Overlapping shells** (teeth into gum, eyeball into socket): fine for renders/games; unify with boolean + remesh only for printing.
- **Text/logos**: geometry for large flat text, textures/decals for small text.

## 8. Retopology workflow (organic → clean quads)

First decide whether the mesh needs quads at all:

| Mesh will be… | Do | Why |
|---|---|---|
| Static (prop, environment, archviz dressing, print), never subdivided | Decimate (COLLAPSE to the tri budget; DISSOLVE on flat CAD areas) → triangulate → UV → bake from the source | Topology is invisible on static meshes; baked normals carry the detail |
| Deformed (rig, cloth, shape keys), subdivided, or a hero close-up needing clean shading/UVs | Quad retopology below (steps 1–7) → bake | Loops must follow deformation and subdivision needs quads |

Scans, photogrammetry and AI-generated meshes need intake repair (weld, floaters, holes, normals, scale) before either path: `mesh-repair.md`, `scripts/mesh_repair.py`.

1. Finish the sculpt's forms; duplicate it into a `_hp` collection.
2. Create a new mesh, add **Shrinkwrap** (target = sculpt, mode Nearest Surface/Project) and **Mirror**; enable snapping to faces with "Project Individual Elements"; turn on the Retopology overlay.
3. Draw the main loops first (eye, mouth, jaw, neck, limbs, joints) using Poly Build / F2 / extrude + slide; fill the fields between loops with grids (LoopTools Gridfill / `bmesh.ops.grid_fill`).
4. Keep density even; place poles deliberately; triangles only on flat hidden areas.
5. Automatic first pass when time matters: **QuadriFlow remesh** (Object Data → Remesh → QuadriFlow) or **Quad Remesher** (paid). From code: `bpy.ops.object.quadriflow_remesh(target_faces=N, mode='FACES', use_mesh_symmetry=..., use_preserve_sharp=..., use_preserve_boundary=..., seed=...)` — all quads at the target face count, sharp edges and symmetry respected. It replaces the mesh (run it on a copy) and needs one welded **manifold** surface: weld, fill holes, remove inner shells or voxel remesh first (intake prerequisites: `mesh-repair.md` §4; measured face yield: `sculpting.md` §1). Auto-retopo gives even quads but *not* deformation-aware loops — hand-fix face and joints afterwards.
6. Transfer the detail: Multires reproject/shrinkwrap or bake from `_hp` (maps, cage and ray distance: `sculpting.md` §8).
7. Run `mesh_report.py`; unwrap.

## 9. Audit checklist (run before calling any stage done)

- [ ] Tri/quad/ngon ratio appropriate for target (quads ≥ 90 % on subdivided/deforming meshes; tris fine on final game export)
- [ ] No poles ≥ 6; poles ≤ 5 not on joints or visible curved surfaces
- [ ] No non-manifold edges (unless intentional open mesh like a plane/cloth)
- [ ] No loose verts/edges, no duplicate verts, no degenerate faces
- [ ] Normals consistent and outward
- [ ] Object scale = 1, rotation applied (or deliberately kept)
- [ ] Loops close on themselves around features and joints
- [ ] Density matches curvature; no micro-triangles
- [ ] Mirror-plane verts at exactly x=0 if mirrored
- [ ] Face count within budget (see poly-budgets-and-targets.md)
