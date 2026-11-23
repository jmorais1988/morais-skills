# USD & Alembic

Read this when moving geometry, animation or caches between Blender and other DCCs through USD or Alembic without silent unit, axis or data loss (`scripts/interchange_check.py`). FBX/glTF delivery to engines is in `game-engine-delivery.md` (`scripts/export_check.py`; web/mobile: `web-and-mobile-delivery.md`); project layout, linking, library overrides and naming are in `project-files-and-naming.md`. Everything API-level was checked in Blender 5.2.0 LTS.

## Contents
1. USD export
2. USD import & round-trip results
3. Alembic caches
4. Units, axes & color between DCCs
5. Round-trip gates
6. Common failures

## 1. USD export

`bpy.ops.wm.usd_export` key options (5.2 defaults in brackets):

| Option | Default | Use |
|---|---|---|
| `selected_objects_only` / `collection` | False / "" | limit the export; instanced objects count as selected when their instancer is |
| `export_animation` | False | whole scene range as time samples (`startTimeCode/endTimeCode`) |
| `export_meshes/lights/cameras/curves/points/volumes/armatures/shapekeys/hair` | True (hair False) | type filter; hair = parent strands only |
| `export_uvmaps`, `rename_uvmaps` | True, True | active UV map written as `st` |
| `export_normals`, `export_mesh_colors` | True | custom normals included |
| `export_subdivision` | `BEST_MATCH` | last Subdivision modifier becomes a USD subdiv scheme (other DCCs subdivide); `TESSELLATE` bakes it |
| `export_materials`, `generate_preview_surface`, `generate_materialx_network` | True, True, False | UsdPreviewSurface is an approximation (Principled/Image/UVMap/Separate RGB only); MaterialX writes Principled as OpenPBR Surface (4.5+) |
| `export_textures_mode` | `NEW` | `KEEP` original paths, `PRESERVE` imported ones, `NEW` copy to `textures/` next to the file |
| `convert_scene_units`, `meters_per_unit` | `METERS`, 1.0 | sets stage `metersPerUnit` and scales data (4.4+) |
| `convert_orientation`, `export_global_forward_selection`, `export_global_up_selection` | False, `NEGATIVE_Z`, `Y` | author a Y-up stage for Y-up consumers |
| `use_instancing` | False | experimental: duplicates → USD references/PointInstancer |
| `root_prim_path` | `/root` | parent Xform + default prim; set `/<Asset>` for referencing |
| `xform_op_mode` | `TRS` | `TOS` (quaternion) or `MAT` |
| `evaluation_mode` | `RENDER` | modifier/visibility settings used |
| `triangulate_meshes`, `merge_parent_xform`, `export_custom_properties`, `allow_unicode` | False, False, True, True | |
| `.usdz` extension, `usdz_downscale_size` | `KEEP` | zipped package for AR Quick Look |

Not exported (manual + measured): USD layers/variants/references — only flattened data; hidden objects; time-sampled geometry subsets (topology-changing meshes with several materials break); non-perspective cameras. Double-sidedness comes from the first material; a Geometry Nodes object must output only its own component type; 5.1 writes indexed UVs (island connectivity survives); 5.2 tags color spaces on prims/textures.

## 2. USD import & round-trip results

`wm.usd_import`: `scale`, `apply_unit_conversion_scale` [True], `set_frame_range` [True], `import_subdivision` [False], `import_usd_preview` [True], `mtl_purpose` [`MTL_FULL`], `mtl_name_collision_mode` [`MAKE_UNIQUE`], `import_textures_mode` [`IMPORT_PACK`] (USDZ), `support_scene_instancing` [True], `prim_path_mask`, `import_visible_only` [True], `merge_parent_xform` [True], `property_import_mode` [`ALL`]. Y-up stages are rotated to Z-up on the root objects. Animated transforms import as *Transform Cache* constraints, animated geometry as *Mesh Sequence Cache* modifiers. Per-file USD sequences are not imported; 5.2 converts colors to the working space on import.

*Measured* (`scripts/interchange_check.py usd`, 5.2, cube + keyed cylinder + Wave-deformed grid, frames 1–24): METERS, CENTIMETERS, Y-up (`convert_orientation`) and `.usdz` round-trips all pass with 0.000 mm max vertex deviation at frames 1/12/24; triangles, materials and frame range preserved; active UV map comes back named `st`; keyed transforms return as Transform Cache, the Wave deformation as Mesh Sequence Cache. The importer names each mesh object after its **mesh prim = source data name** (`Cube`, not `GEO_Crate`) — name object data like the object (`project-files-and-naming.md` §1). `convert_scene_units='CENTIMETERS'` writes `metersPerUnit = 0.01` **plus** `xformOp:scale = (100,100,100)` on the root prim, so Blender re-imports the same size with `apply_unit_conversion_scale` on or off; a consumer that honours only one of the two is off by 100×. A Subdivision modifier with `BEST_MATCH` re-imports as the cage (192 → 12 tris, size ratio 1.19, flagged); `TESSELLATE` passes.

## 3. Alembic caches

Alembic stores baked results (vertex positions, transforms, curves, points), not rigs, materials or modifiers — use it for animated/simulated geometry handed to lighting or other DCCs.

| `wm.alembic_export` option | Default | Note |
|---|---|---|
| `start`, `end` | scene range | sentinel `-2147483648` = scene range |
| `selected`, `collection`, `flatten` | False, "", False | flatten writes world transforms, no hierarchy |
| `xsamples`, `gsamples`, `sh_open`, `sh_close` | 1, 1, 0, 1 | sub-frame samples for motion blur (e.g. 5 samples, −0.25..0.25) |
| `uvs`, `packuv`, `normals`, `vcolors`, `orcos`, `face_sets` | T, T, T, F, T, F | face sets = material **names** only |
| `apply_subdiv`, `subdiv_schema` | False, False | bake subdivision or write SubD schema |
| `curves_as_mesh`, `export_hair`, `export_particles` | F, T, T | hair → zero-width curves, particles → points |
| `use_instancing`, `global_scale`, `triangulate`, `evaluation_mode`, `export_custom_properties` | T, 1.0, F, `RENDER`, T | keep scale 1.0 = Blender units |

`wm.alembic_import`: `scale`, `set_frame_range`, `is_sequence` (one file per frame), `validate_meshes`, `always_add_cache_reader` (so reloading picks up re-exports), `relative_path`. The `CacheFile` data-block (`filepath`, `scale`, `forward_axis/up_axis`, `frame_offset`, `override_frame`, `velocity_name/unit`, `layers`) drives Mesh Sequence Cache / Transform Cache — point it at a newer cache instead of re-importing. Alembic has no frames: Blender converts with the scene fps, so matching fps matters. 5.2 imports animated visibility and camera data as F-curves. Custom normals are written only if the mesh has custom normals or flat faces; a mesh without normals imports smooth.

*Measured* (`scripts/interchange_check.py alembic`): Wave-deformed grid (192 tris) + keyed cylinder, frames 1/7/13/24 → 0.000 mm vertex deviation, frame range kept, Mesh Sequence Cache + Transform Cache created, material slots dropped. Planted `global_scale=0.01` → diagnosed `x0.01 (cm->m)`, deviations up to 3960 mm.

## 4. Units, axes & color between DCCs

Engine export presets and FBX/glTF axis & scale: `game-engine-delivery.md` §2 (`scripts/export_check.py`).

| Target | Up | Linear unit | What to set |
|---|---|---|---|
| Blender | Z | m (1 BU = 1 m) | apply scale before export |
| Houdini, Maya (default), Unity | Y | m (Houdini, Unity), cm (Maya) | USD `convert_orientation` Y-up; Maya: `convert_scene_units='CENTIMETERS'` or let its USD importer honour `metersPerUnit` |
| Unreal | Z (left-handed) | cm | USD/FBX importers convert m→cm; verify axis on a test asset [unverified per engine version] |
| 3ds Max | Z | often in/cm | check system unit before import |
| Omniverse / USD viewers | stage metadata (`upAxis`, `metersPerUnit`) | — | always author both; `interchange_check.py` reads them via `pxr` |

- **Rule**: the unit lives in metadata and the numbers must agree. Blender's cm export keeps geometry in metres under a ×100 root scale plus `metersPerUnit=0.01`; a consumer reading only the metadata or only the transform is 100× off. Gate it with `interchange_check.py usd --expect-units CENTIMETERS` (fails when the stage says otherwise), then open one asset in the real consumer. *Measured*: re-importing a Blender-authored stage in Blender ignores both `apply_unit_conversion_scale` and the import `scale` (size ratio stayed 1.0 with `scale=100`), so Blender cannot stand in for a mis-reading consumer; scale errors inside the data itself are caught (Alembic `global_scale=0.01` → `x0.01 (cm->m)`).
- Scene *Unit Scale* (`scene.unit_settings.scale_length`) only changes display and some exporters; keep 1.0 and convert at export.
- **Color**: exchange linear EXR for renders/data, sRGB 8-bit for base color, Non-Color for normal/roughness/ORM. OCIO/ACES and the 5.0 per-file working space: `archviz-lighting-and-rendering.md` §3 (general color management: `rendering-and-lighting.md` §6). 4.5 reads/writes ACES2065-1 EXR metadata; 5.0 writes Color Interop IDs in EXR; 5.2 USD tags color spaces.

## 5. Round-trip gates

```bash
# USD / Alembic round-trips of the selection or named objects
blender -b asset_v012.blend --python scripts/interchange_check.py -- usd --objects GEO_Crate,GEO_Lid --animation --units CENTIMETERS
blender -b shot.blend --python scripts/interchange_check.py -- alembic --collection CHAR_Hero --frames 1,50,100
```
- `usd`: exports the targets with `wm.usd_export`, re-imports into a temporary scene and compares mesh object count, triangles, world bbox and per-vertex deviation (`--tol-mm 0.1`), materials, UV map count, frame range and animated positions at `--frames`; reads `metersPerUnit`, `upAxis` and time codes through `pxr` when available; diagnoses scale factors (×100 cm/m, ×0.0254 in…) and axis swaps. Options mirror the exporter: `--units`, `--meters-per-unit`, `--no-apply-units`, `--expect-units`, `--import-scale`, `--convert-orientation --forward NEGATIVE_Z --up Y`, `--subdiv BEST_MATCH|TESSELLATE|IGNORE`, `--no-materials`, `--materialx`, `--instancing`, `--usdz`, `--root-prim`, `--out DIR --keep`.
- `alembic`: `wm.alembic_export` → `wm.alembic_import` → per-vertex world deviation at sampled frames; `--export-scale` plants/tests a scale factor.
- Targets default to the selection; live use: `INTERCHANGE_OPTS = {"op": "usd", "objects": ["GEO_Crate"], "units": "CENTIMETERS"}` (imported data and the temporary scene are removed afterwards). Limits: objects matched by name; per-vertex deviation needs equal vertex counts and order (a subdiv scheme re-imports as the cage → triangle mismatch is reported, not hidden); materials compare names only; Alembic carries no materials.
- **Publish gate**: `interchange_check usd` pass for the target units/axis, plus `naming_lint` and `library` (`project-files-and-naming.md` §6) and the domain gates (`quality-gates.md`).

## 6. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Asset 100× too big/small in another DCC | consumer honours `metersPerUnit` or the root ×100 scale but not both | export in the consumer's unit, test one asset there; `interchange_check.py usd --expect-units` |
| USD re-import objects named `Cube`, `Cylinder` | importer names objects after mesh prims (= data names) | rename data to match objects (`naming_lint.py --fix` does it) |
| Asset lies on its back in Maya/Houdini | Z-up stage read as Y-up | `convert_orientation=True`, up `Y`, forward `NEGATIVE_Z` |
| Smooth asset arrives low-poly | Subdivision exported as subdiv scheme, consumer ignores it | `export_subdivision='TESSELLATE'` or enable subdivision on import |
| Materials grey/flat in USD viewer | node tree beyond UsdPreviewSurface support | Principled + image textures only, or MaterialX; bake complex shaders |
| Cache "swims" in time | fps mismatch (Alembic stores seconds) | same fps in both scenes; check `CacheFile.frame_offset` |
| Round-trip reports a triangle mismatch on a clean mesh | `BEST_MATCH` wrote a subdiv scheme; importer returns the cage | `--subdiv TESSELLATE`, or accept and subdivide in the consumer |
