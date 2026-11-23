# CAD Bridge & Enclosures

Read this when a request is CAD-shaped — mating fits, screw bosses, hinges, snap lids, STEP/IGES deliverables, dimension changes likely — or when a CAD part must come into Blender: the build123d / CadQuery bridge, STEP ↔ Blender routes, the `scripts/cad_enclosure_template.py` enclosure generator with connector cut-outs, and enclosure design rules. The Blender-or-CAD decision table and all print tolerances (walls, clearances, holes) live in `3d-printing.md` (§1, §3–4); this file defers to them.

## Contents
1. CAD bridge (build123d / CadQuery, STEP ↔ Blender)
2. Enclosure generator and connector cut-outs (`scripts/cad_enclosure_template.py`)
3. Enclosure design rules
4. Common failures

## 1. CAD bridge (build123d / CadQuery, STEP ↔ Blender)

- **build123d** (used by the template) and **CadQuery** both sit on OpenCascade; `pip install build123d` / `pip install cadquery` in a venv (Python 3.10–3.13 wheels; both import on Windows). Export: `export_step(part, "x.step")`, `export_stl(part, "x.stl", tolerance=0.005, angular_tolerance=0.1)` — `tolerance` is the linear chord deviation in mm.
- **STEP → Blender**: Blender has no STEP importer. Routes: (a) export STL/OBJ/glTF from the CAD tool with an explicit chord tolerance (0.01 mm for print, 0.05–0.1 mm for renders); (b) `build123d.import_step()` → `export_stl`/`export_gltf`; (c) FreeCAD (Mesh Design → from shape, deviation) for STEP/IGES; third-party STEP importer add-ons exist `[unverified]`. Import STL with `wm.stl_import(global_scale=0.001)` into a metre scene. Tessellated CAD meshes are triangle soup with long slivers — fine for print and render, bad for subdivision; don't retopologize CAD, re-export at the needed density.
- **Blender → CAD**: meshes stay meshes (FreeCAD "shape from mesh" is faceted, not parametric). Rebuild parametric features in CAD using measured dims.
- build123d on Windows: if import dies with `TTLibError: Not a TrueType or OpenType font`, a malformed system font broke its font scan — the template retries with the scan disabled.

## 2. Enclosure generator and connector cut-outs (`scripts/cad_enclosure_template.py`)

`scripts/cad_enclosure_template.py --out-dir out --pcb 50x30x1.6` → base + snap lid STEP/STL + `enclosure_params.json`. Verified by importing the STLs headless into Blender: boss OD, pilot, boss centres, cavity/PCB clearance, lid fit gap and hook engagement all within 0.01 mm of the parameters (see CHANGELOG entry). Its default interlocking clearance is 0.3 mm per side (`3d-printing.md` §3).

Connector cut-outs: `--cutouts cutouts.json` (or inline JSON), e.g. `[{"face":"+x","shape":"rect","center":[0,1.8],"size":[9,3.4],"r":1,"from":"pcb_top"}, {"face":"lid","shape":"circle","center":[-5,4],"size":5}]`. Walls: u = along the wall from the box centre, v = height above `from` (`base`, `floor`, `pcb_bottom`, `pcb_top`); `bottom`/`lid`: top-view x/y. Through-cuts of the wall/floor/lid plate only; warnings when a cut leaves the free wall band (floor, lid lip zone), overlaps a snap window/tab, a screw boss or the lid lips. Measured on the written STLs (outer and inner wall faces): rect, rounded-rect and circle cuts on ±x, ±y, bottom and lid within 0.0025 mm of size (circle radius error 1e-5 mm), parts valid, 0 open edges; 5 planted misplacements → 6 warnings.

## 3. Enclosure design rules

| Feature | Rule (printed; molded where noted) |
|---|---|
| Wall | 1.5–2.5 mm printed (never below the process minimum in `3d-printing.md` §3); molded: uniform nominal wall, change ≤ 25 %/step `[unverified]` |
| PCB to wall | ≥ 0.5–1 mm per side + connector cut-outs |
| Connector cut-out | opening = plug overmold (not the receptacle) + 0.3–0.5 mm per side printed (clearance rule: `3d-printing.md` §3) `[unverified; measure the cable]`; ≥ 1 wall from corners, bosses and snap windows; reference v from `pcb_top` so it follows standoff changes |
| Standoff/boss height | clears through-hole pin protrusion (≥ 2–3 mm) and parts under the board |
| Screw boss | OD ≈ 2–2.5 × screw d; pilot for thread-forming screws ≈ 0.8–0.85 × d (M2.5 → 2.0–2.1) `[screw vendor]`; heat-set insert → vendor hole; fillet the boss root |
| Ribs/gussets | 50–60 % of wall (molded, avoids sink); printed: equal to wall is fine |
| Draft | molded 0.5–1°/side (textured 1–2°+); printed: none needed |
| Lid fit | 0.2–0.3 mm per side (FDM 0.3–0.4); the general clearance rule is `3d-printing.md` §3 |
| Snap-fit cantilever | strain ε = 1.5·t·y / l² (constant section; y = deflection/undercut, t thickness at root, l length); arm tapering to t/2: y = 1.09·ε·l²/t (Covestro guide). Keep ε below permissible: amorphous plastics ≈ 70 % of yield strain, partially crystalline near yield, glass-filled ≈ ½ elongation at break (one-time assembly); halve for repeated use. Lengthening l is the strongest lever (squared). Orient the arm so it bends along print layers. |

Holes, heat-set insert diameters, fit classes and layer orientation for the printed enclosure: `3d-printing.md` §4.

## 4. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| STEP needed but only a mesh exists | modeled in Blender | rebuild in build123d/CadQuery (§1) |
| "Make it 2 mm wider" means remodeling | dimensions baked into a mesh | parametric script; re-export the mesh from CAD (§1) |
| CAD STL imports into Blender with a few boundary edges on fillets | OCC tessellation of a moved/rotated shape leaves sub-micron cracks; Blender's STL import merges only bit-identical verts | snap verts to a 1e-5 mm grid (template `weld_stl`; measured 12 → 0 open edges) or Merge by Distance ≤ 0.001 mm (§1; feature-relative rule ≤ 1/10 of the smallest feature: `3d-printing.md` §2) |
| CAD mesh subdivides into slivers | tessellated triangle soup | don't retopologize CAD; re-export at the needed chord tolerance (§1) |
| CAD part imports 1000× too big | mm STEP/STL into a metre scene | `wm.stl_import(global_scale=0.001)` (§1) |
| build123d import dies with `TTLibError` on Windows | malformed system font in its font scan | retry with the scan disabled (the template does) (§1) |
| Snap tab snaps off | strain above material limit, layer-direction bending | lengthen arm, taper, reorient; compute ε (§3) |
| Cut-out warning from the template | cut leaves the free wall band, or overlaps a snap window/tab, screw boss or lid lip | move the cut ≥ 1 wall from those features; reference v from `pcb_top` (§2–3) |
| Connector doesn't fit the cut-out | opening sized to the receptacle, not the plug overmold | plug overmold + 0.3–0.5 mm per side; measure the cable (§3) |
| Screw strips or boss splits | pilot wrong for thread-forming screws | pilot ≈ 0.8–0.85 × d, OD 2–2.5 × d, fillet the root (§3) |
