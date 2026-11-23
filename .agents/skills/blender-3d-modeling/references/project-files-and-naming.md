# Project Files & Naming

Read this when organising multi-file Blender work: naming conventions, folder layout and external paths, linking/appending/packing, library overrides from code, versioning and Git LFS (`scripts/naming_lint.py`). USD/Alembic hand-off and unit/axis metadata are in `usd-and-alembic.md` (`scripts/interchange_check.py`); FBX/glTF delivery to engines is in `game-engine-delivery.md` (`scripts/export_check.py`; web/mobile: `web-and-mobile-delivery.md`). Everything API-level was checked in Blender 5.2.0 LTS.

## Contents
1. Naming conventions
2. Project layout & external paths
3. Linking, appending, packing, collection instances
4. Library overrides from code
5. Versioning, backups, Git LFS & locking
6. Naming lint & publish gate
7. Common failures

## 1. Naming conventions

| Thing | Working file | Export / engine copy | Check |
|---|---|---|---|
| Objects | `<ROLE>_<Name>`: `GEO_`, `KIT_`, `LGT_`, `CAM_`, `RIG_`; archviz `WALL_ SLAB_ FLR_ CEIL_ OPN_ CUT_ FRAME_ WIN_/GLASS_ DOOR_ FURN_` (the `archviz` lint profile also allows `GEO_`, `REF_`; same set as `archviz-modeling.md` §2) | `SM_<Asset>` static, `SK_<Asset>` skeletal | `naming_lint.py` |
| Collision / sockets | `COL_<part>` in a hidden `COLLIDERS` collection; `SOCKET_<role>` empties | `UCX_/UBX_/USP_<SM_name>_NN` (`UCP_` also accepted by the lint); `SOCKET_<role>` | `naming_lint.py --profile game_export` |
| LODs | `<Name>_LOD0.._LODn` (suffix at the end) | same | `lod_suffix` |
| Materials | `MAT_<Name>` | `M_<Name>` / `MI_<Name>` (instances) | `material_prefix` |
| Textures | `T_<Asset>_<Map>` files (`BaseColor`, `Normal`, `ORM`, `Roughness`...) — fine in the working file too | same | `image_pattern` |
| Collections | `KIT_<family>`, `SET_<name>`, `DIST_/BLK_` for cities | root collection = asset | `default_name` |
| Bones & mirrored parts | `.L` / `.R` suffix (mirror, symmetrize, weight mirror rely on it) | exporter may rename | `lr_unpaired`, `lr_convention` |
| Files | `<asset>[_<task>]_v###.blend`, no spaces | `<asset>.usdc`, `SM_<Asset>.fbx` | `file_name` |

- Allowed characters `A-Z a-z 0-9 _ . -`; no spaces, no `.001` in published names, no default names (`Cube`, `Material`). Name object data like the object (USD importers name objects after the mesh prim — `usd-and-alembic.md` §2).
- Only the **object** prefixes `SM_`/`SK_` and **material** prefixes `M_`/`MI_` are export-copy-only; they are applied when the export copy is built (`game-engine-delivery.md` §3), so a working file containing them is flagged. Collision meshes follow the same split: `COL_<part>` in the working file becomes `UCX_/UBX_<SM_name>_NN` in the export copy (`game-engine-delivery.md` §5). `T_` texture names are correct at every stage; the `working` profile of `naming_lint.py` still reports them as `engine_prefix_in_working` (warning) — silence it with a rules file: `--rules rules.json` holding `{"engine_prefixes": {"images": []}}`.
- One version pattern everywhere: `<asset>_v###.blend`, with an optional `_<task>` segment before `_v###` (`crate_v012.blend`, `crate_wip_v013.blend`, `sh010_lay_v003.blend`); three digits, never "final".
- 5.0+ allows 255-byte names — 4.5 truncates them and cannot link them.

## 2. Project layout & external paths

```
project/
  assets/<asset>/<asset>_v012.blend      # one asset per file, published versions only
  assets/<asset>/_wip/<asset>_wip_v013.blend
  assets/<asset>/textures/T_<Asset>_<Map>.png
  kit/<family>.blend                     # modular kits / kitbash libraries (asset-library folder)
  shots/<seq>/<shot>/<shot>_lay_v003.blend  # layout/anim/light files link assets
  caches/<shot>/<asset>.abc|.usdc        # generated: never hand-edited, not in Git
  renders/<shot>/v003/####.exr
  _publish/                              # what other departments/DCCs consume (USD, FBX, GLB)
```
- **WIP vs publish**: artists save `_wip` increments freely; a publish is a deliberate copy that passed the gates (`naming_lint.py`, `interchange_check.py`, domain gates — §6) and is what shots link. Shots never link a `_wip` file.
- **Relative paths** (`//` = folder of the .blend) keep a project movable. Preference *Default to Relative Paths* is on by default. Fix a file: `bpy.ops.file.make_paths_relative()` (needs a saved file; paths on another Windows drive stay absolute; stored with the OS separator, e.g. `//tex\wood.png` on Windows — Blender resolves both). `bpy.data.file_path_map()` lists every external path per ID for audits.
- **Missing files**: `bpy.ops.file.report_missing_files()`; `bpy.ops.file.find_missing_files(directory=..., find_all=False)` searches a folder by file name. Images: `Image.filepath`, resolve with `bpy.path.abspath(p, library=img.library)`; check `os.path.exists` (UDIM: replace `<UDIM>` per `img.tiles`).
- **Packing**: `file.pack_all()` embeds images/sounds/fonts (portable single file, bigger saves, textures no longer editable in place); `file.unpack_all(method='USE_LOCAL'|'WRITE_LOCAL'|...)`. Pack only for hand-off/archive, not in a live project.
- **Moved libraries**: `Library.filepath` + `Library.reload()` or `bpy.ops.wm.lib_relocate(library=lib.name, directory=dir + os.sep, filename=name, filepath=full)` — works headless; the Library data-block is renamed to the new file name. *Measured*: after moving `lib.blend`, reopening marks `Library.is_missing=True` and each linked ID becomes a placeholder with `ID.is_missing=True`; `lib_relocate` restored all of them and the override edits survived.

## 3. Linking, appending, packing, collection instances

| Method | Data lives in | Editable here | Updates from source | Use for |
|---|---|---|---|---|
| Link | source file | no (override it, §4) | yes, on load/reload | assets in shots, kits, sets |
| Link + Pack (5.0+) | copy inside this file (archive library) | no | no (frozen snapshot, de-duplicated) | asset-browser drops, hand-off without dependency files |
| Append | this file (local copy) | yes | no | one-off reuse, forking an asset |

- **Code**: `with bpy.data.libraries.load(path, link=True, relative=True) as (src, dst): dst.collections = ["COL_Asset"]`. 5.2 signature also has `pack`, `reuse_local_id`, `assets_only`, `clear_asset_data`, `create_liboverrides`, `reuse_liboverrides`, `create_liboverrides_runtime`. Operators: `wm.link` / `wm.append` (`instance_collections`, `do_reuse_local_id`, `set_fake`, `use_recursive`).
- **Collection instances**: link the root collection, then an Empty with `instance_type='COLLECTION'` (`scripts/asset_library.py place` reuses one Library data-block per file). Cheapest way to repeat an asset; instances are not editable per copy — override if needed.
- **Packed linked data (5.0+)**: still linked (not editable), stored in the current file inside *archive* libraries (`Library.is_archive`, `archive_parent_library`); unaffected by later source changes; `bpy.data.pack_linked_ids_hierarchy(root_id)` packs from code; `file.pack_libraries` / `file.unpack_libraries`. 4.5 opens such files as appended local data.
- **Asset system** (kitbash/library structure, catalogs, 5.2 per-asset preferred import method and online libraries): `kitbashing.md` §4–5. 5.0 import methods: Link / Append / **Pack** (default for custom libraries).
- Keep every collection an asset needs **under one root collection**; overrides and relocation rely on that hierarchy (`large-sets-and-cities.md` §8).

## 4. Library overrides from code

Overrides make a linked hierarchy locally editable while still following the source. *System overrides* are created only to keep the hierarchy valid (non-editable, greyed); *editable* (user) overrides are the ones you change.

```python
coll = dst.collections[0]                                    # linked root collection
inst = ...                                                   # the Empty instancing it (optional reference)
root = coll.override_hierarchy_create(scene, view_layer, reference=inst, do_fully_editable=False)
# API does NOT delete the instancing Empty (the 3D-viewport "Make Library Override" does) -> remove it yourself
ob = next(o for o in bpy.data.objects if o.name == "GEO_Crate" and o.override_library and o.library is None)
ob.override_library.is_system_override = False               # make editable
ob.location.x = 5.0
ob.override_library.operations_update()                      # record the rule now (also happens on save)
[p.rna_path for p in ob.override_library.properties]         # -> ['location']
```
- Other API (5.2): `ID.override_create(remap_local_usages=False)` (single ID), `IDOverrideLibrary.reset(do_hierarchy, set_system_override)`, `.destroy(do_hierarchy)`, `.resync(scene, view_layer, residual_storage, do_hierarchy_enforce, do_whole_hierarchy)` → success, `.hierarchy_root`, `.reference`, `Library.needs_liboverride_resync`. Outliner operators: `outliner.liboverride_operation(type='OVERRIDE_LIBRARY_CREATE_HIERARCHY'|'..._RESET'|'..._CLEAR_SINGLE', selection_set='SELECTED_AND_CONTENT')`, `outliner.liboverride_troubleshoot_operation(type='OVERRIDE_LIBRARY_RESYNC_HIERARCHY'|'..._ENFORCE'|'..._DELETE_HIERARCHY')` (UI context).
- **Resync** happens automatically when a file is opened if the source hierarchy changed (can be disabled in Experimental prefs). Manual *Resync Enforce* rebuilds broken hierarchies at the cost of ID-pointer overrides.
- *Measured* (`scripts/interchange_check.py library-selftest`): source gains an object, moves a vertex, renames one overridden object and deletes another, then the shot is reopened →
  | Source change | Result in shot |
  |---|---|
  | new object added to the root collection | appears, as a system override |
  | vertex moved in linked mesh | visible (mesh stays linked) |
  | untouched object with a local `location` edit | edit kept (5.0, 0, 0) |
  | overridden object **renamed** in source | old override removed, new override created at source values: **local edit lost** |
  | overridden object deleted in source | override removed |
  | library file moved | `is_missing` placeholders; override edits preserved; relocate restores |
- Rules that follow: never rename or re-parent published asset objects (add, don't rename); keep edits on the few editable IDs (armature/pose, a root Empty); animation on overrides needs a **new local action** (existing linked F-curves can only be muted); Edit Mode is not available on overrides — shape the asset in its source file.
- Posed-but-not-animated armatures lose their pose if the Armature data goes missing and was not itself overridden (manual warning).

## 5. Versioning, backups, Git LFS & locking

- **Incremental names**: `<asset>[_<task>]_v###.blend` (§1). `wm.save_mainfile(incremental=True)` (File → Save Incremental) appends a number (*measured*: `orph.blend` → `orph1.blend`), which does not follow `_v###` — script your own: `re.sub(r"_v(\d{3})", lambda m: f"_v{int(m[1])+1:03d}", stem)` then `save_as_mainfile(filepath=..., copy=False)`.
- **Backups**: Preferences → Save & Load → *Save Versions* (`preferences.filepaths.save_version`, default 1) keeps `.blend1…blend32`; a second save creates `.blend1` (*measured*). Auto-save: `use_auto_save_temporary_files`, `auto_save_time`; 5.2 adds `wm.save_auto_save()` and stores edited-image info in autosaves. File compression is **on by default since 5.0** (`use_file_compression`; `save_as_mainfile(compress=...)`) — compressed .blend deltas poorly in Git/Perforce; many studios turn it off for versioned trees.
- **Orphans**: data-blocks with 0 users and no fake user are **not written** on save (*measured* in 5.2: an unused mesh vanished after save/reopen; a fake-user mesh survived). Give library-only materials/node groups a fake user or mark them as assets.
- **Git + LFS**: binary files never diff/merge — lock them.
  ```gitattributes
  *.blend  filter=lfs diff=lfs merge=lfs -text lockable
  *.blend1 -filter -diff -merge
  *.exr    filter=lfs diff=lfs merge=lfs -text
  *.png    filter=lfs diff=lfs merge=lfs -text
  *.jpg    filter=lfs diff=lfs merge=lfs -text
  *.usdc   filter=lfs diff=lfs merge=lfs -text
  *.abc    filter=lfs diff=lfs merge=lfs -text
  ```
  Add the same line for `.tif .hdr .usdz .vdb .fbx .glb`; keep `.usda` as text.
  `.gitignore`: `*.blend1`, `*.blend[0-9]*`, `caches/`, `renders/`, `__pycache__/`, `*.bak`. Lock before editing: `git lfs lock assets/crate/crate_v012.blend`; `lockable` makes unlocked files read-only on checkout.
- **Perforce** (exclusive checkout, `+l` filetype for `.blend`) or **SVN** (`svn:needs-lock`) suit large art teams; Git LFS suits small, code-adjacent teams. Never commit caches, renders or bakes.

## 6. Naming lint & publish gate

```bash
# naming + file hygiene (profiles: working | archviz | game_export)
blender -b asset_v012.blend --python scripts/naming_lint.py -- --profile working
blender -b asset_v012.blend --python scripts/naming_lint.py -- --fix --relative --save
# libraries & overrides in a shot; relocate missing libraries found under a folder
blender -b shot_v003.blend --python scripts/interchange_check.py -- library --search-dir //../../assets --save
```
- `naming_lint.py` checks role/material/texture prefixes, default names, illegal characters, `.001` suffixes, `.L/.R` pairs, `_LOD<n>` form, engine prefixes in the working file, orphans, absolute paths and missing images/caches/libraries. `--fix` applies only safe renames (illegal chars → `_`, `.001` → base name, data name = object name for single-user data); nothing linked, no bones, no collisions. `--rules rules.json` deep-merges over the defaults; live use: `NAMING_OPTS = {"profile": "working", "fix": False}`.
- `interchange_check.py library` reports missing/absolute/needs-resync/archive libraries, missing linked IDs and override hierarchies (system vs editable, overridden properties, broken references); `--search-dir` relocates missing libraries, `--resync [--enforce]` rebuilds hierarchies.
- **Publish gate**: `naming_lint` 0 errors (warnings reviewed), `interchange_check usd` pass for the target units/axis (`usd-and-alembic.md` §5), `library` pass (no missing libraries/IDs, no broken overrides, no pending resync), domain gates (`quality-gates.md`).

## 7. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Pink textures after moving project | absolute paths | `file.make_paths_relative`, `file.find_missing_files(directory=)` |
| Shot opens with missing objects | library moved/renamed | `library --search-dir`, or `wm.lib_relocate` |
| Local override edits vanished after asset update | object renamed/re-parented in the library, resync recreated it | never rename published asset objects; re-apply edits; keep edits on a few stable IDs |
| Two copies of a linked asset after override | API `override_hierarchy_create` keeps the instancing Empty | delete the Empty after creating the hierarchy |
| Can't edit mesh of an overridden object | Edit Mode not allowed on overrides | edit the source file; override only transforms/modifiers/poses |
| Unused materials disappear after save | orphans not written | fake user or mark as asset |
| Git repo balloons / merges corrupt .blend | .blend not in LFS, no locking, compression on | `.gitattributes` above, `git lfs lock`, consider uncompressed saves |
| `Material.001`, `Cube.003` everywhere | appends/duplicates without renaming | `naming_lint.py --fix` (safe renames) then name by role |
| `engine_prefix_in_working` on every `T_` texture | `working` profile still lists `T_` as an engine prefix | rules file with `{"engine_prefixes": {"images": []}}`; textures keep `T_` |
