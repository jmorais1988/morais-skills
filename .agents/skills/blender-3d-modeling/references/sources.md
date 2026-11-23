# Sources for 3D Modeling Best Practices

Consult these when a decision is unclear, when the user asks "why", or when the target pipeline is unusual. Re-search (`web_search`) for the target engine's *current* documentation — budgets and export conventions change every couple of years.

## Contents
1. Topology
2. Hard surface
3. Organic & sculpting
4. Poly budgets & pipelines
5. Precision / print / CAD
6. Add-ons
7. Reference imagery
8. Materials, shaders, texturing
9. Environment, flora, fauna
10. Blender bridges / MCP
11. 3D printing, jewelry & CAD
12. Pipeline & interchange
13. Texture painting & Ucupaint
14. Vector, text & voxel
15. Mesh repair & intake
16. Rendering & compositing
17. Simulation
18. Stylized / NPR & Grease Pencil
19. UV & baking
20. Vehicle interiors & automotive paint
21. Anime face shading
22. Blender release notes (5.x) used for API fixes
23. Animation & rigging (5.x)
24. Rigging & lip-sync
25. Game & web delivery
26. Archviz
27. Large sets & cities
28. Modular kits & WFC
29. Kitbashing
30. Hard Ops
31. Merged from the img2threejs skill (image→procedural 3D)

## 1. Topology
- CG Cookie — *The Art of Good Topology* (poles, loops, quads/tris/ngons under subdivision): https://blog.cgcookie.com/posts/the-art-of-good-topology-blender/
- Yarsa Labs — *Blender Topology Guide* (artifacts from ngons/tris, hiding non-quads on flat areas): https://blog.yarsalabs.com/blender-topology-guide/
- Meshy — *3D Mesh Topology: The Complete Guide* (loops around eyes/mouth, manifold rules): https://www.meshy.ai/blog/mesh-topology
- Michael Steppig — *Squeaky Clean Topology in Blender* (Packt book; quad-based and non-quad retopology)
- Polycount wiki (Topology, Limb topology, Face topology) — search "polycount wiki topology"

## 2. Hard surface
- Propgon — *Hard Surface Modeling in Blender for Game Art* (subd cage vs boolean+bevel, bake checklist): https://propgon.com/en/hard-surface-modeling-blender-game-art-guide/
- Blender Base Camp — custom normals / Weighted Normal for beveled edges: https://www.blenderbasecamp.com/custom-normals-blender-hard-surface-tip/
- Hyper-casual.games — boolean workflow & hard-surface pitfalls (scale application, over-beveling): https://hyper-casual.games/blog/blender-hard-surface-modeling
- Blender Manual — Modifiers (Bevel, Boolean, Weighted Normal, Smooth by Angle): https://docs.blender.org/manual/en/latest/modeling/modifiers/index.html

## 3. Organic & sculpting
- Sofia Pahaoja — *Remesh + Multires workflow in Blender* (why to avoid Dyntopo, voxel sizes): https://medium.com/@skarkkai/remesh-multires-workflow-in-blender-2ae97ae5176d
- Blender Manual — Sculpting (brushes, remesh, multires): https://docs.blender.org/manual/en/latest/sculpt_paint/sculpting/index.html
- Yelzkizi — auto retopology (Voxel/Quadriflow/Quad Remesher + reproject): https://yelzkizi.org/auto-retopology-in-blender/
- Blender sculpt release notes 4.2–5.2 (brush assets, Plane brush, Blur, Scene Project, diameter sizes, per-mode unified settings): https://developer.blender.org/docs/release_notes/4.3/sculpt/ … https://developer.blender.org/docs/release_notes/5.2/sculpt/ ; Python API notes (4.4 stroke/pen_flip, 5.0 sculpt_brush_type, 5.1 stroke_method/brush_toggle): https://developer.blender.org/docs/release_notes/5.0/python_api/
- API reference: https://docs.blender.org/api/current/bpy.ops.sculpt.html , https://docs.blender.org/api/current/bpy.ops.brush.html , https://docs.blender.org/api/current/bpy.types.OperatorStrokeElement.html
- Manual — Adaptive resolution (voxel/dyntopo), Multiresolution: https://docs.blender.org/manual/en/latest/sculpt_paint/sculpting/introduction/adaptive.html , https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/multiresolution.html
- Sculpt-mode refactor (4.3 performance): https://code.blender.org/2024/11/this-summers-sculpt-mode-refactor/
- Anatomy: Anatomy for Sculptors (Uldis Zarins), *Anatomy 360*, Scott Eaton; animal skeletons via museum/veterinary references

## 4. Poly budgets & pipelines
- Neural4D — *Polygon Count for 3D Game Assets, Printing, and WebAR*: https://blog.neural4d.com/user-guide/polygon-count-for-3d-game-assets-printing-and-webar/
- CGAxis — *Polygon Count Guide 2026*: https://cgaxis.com/polygon-count-guide-how-many-polys-do-you-really-need-in-2026/
- Trumble — *Polygon Count Guide* (LOD0 budgets, LOD-friendly topology): https://trumble.app/polygon-count-guide.html
- MessyPoly — *Polygon budgets for mobile games* (scene-level budgeting, micro-triangles): https://www.messypoly.com/learn/polygon-budgets-mobile-games
- Unreal Engine docs — Static Mesh / Nanite / FBX import; Unity docs — Model import & optimization; Godot docs — Importing 3D scenes (search current versions)
- Khronos glTF sample viewer & three.js docs for web budgets/compression

## 5. Precision / print / CAD
- Blender 3D Print Toolbox docs: https://extensions.blender.org/add-ons/print3d-toolbox/
- Manifold (definition of manifold meshes; solid modeling): https://manifoldcad.org/docs/jsuser/
- CadQuery / Build123d docs for true parametric CAD from Python

## 6. Add-ons
- Blender Extensions platform: https://extensions.blender.org/add-ons/ (LoopTools, Bool Tool, F2, 3D Print Toolbox, Node Wrangler…)
- MESHmachine: https://machin3.gumroad.com/l/MESHmachine ; Hard Ops/Boxcutter (Blender Market); Quad Remesher (Exoside); RetopoFlow (Orange Turbine)

## 7. Reference imagery
- Wikimedia Commons, manufacturer spec sheets, the-blueprints.com, museum digital collections, Sketchfab (topology study), Pinterest boards for style (do not copy designs), PureRef for board layout.

## 8. Materials, shaders, texturing
- Blender Manual — Shader nodes, Image Texture (Box projection), Normal Map, Bump, Displacement, Cycles Baking: https://docs.blender.org/manual/en/latest/render/shader_nodes/
- glTF-Blender-IO docs (occlusion via "glTF Material Output", Non-Color requirements): https://github.com/KhronosGroup/glTF-Blender-IO/blob/main/docs/blender_docs/scene_gltf2.rst
- Node Wrangler map-name tags: https://github.com/blender/blender/blob/main/scripts/addons_core/node_wrangler/preferences.py
- Adobe — OpenGL vs DirectX normal maps: https://experienceleague.adobe.com/en/docs/substance-3d/bakers/common-questions/what-is-the-difference-between-the-opengl-and-directx-normal-format
- Marmoset — *Physically Based Rendering, And You Can Too!* (roughness/albedo independence): https://marmoset.co/posts/physically-based-rendering-and-you-can-too/
- Poly Haven license (CC0, no scraping): https://polyhaven.com/license ; ambientCG license (CC0): https://docs.ambientcg.com/license/
- Materialize (image → height/normal/AO): https://boundingboxsoftware.com/materialize/ ; NormalMap-Online: https://cpetry.github.io/NormalMap-Online/
- Moisan, periodic + smooth decomposition (seam removal): https://helios2.mi.parisdescartes.fr/~moisan/papers/2009-11.pdf
- PhysEditBench (image editors vs specialized models for normal/roughness): https://arxiv.org/abs/2605.13493
- ComfyUI PBR generation: Ubisoft CHORD https://blog.comfy.org/p/ubisoft-open-sources-the-chord-model ; QFX PBR Generator https://github.com/qornflex/ComfyUI-QFX-PBRGenerator ; StableGen (Blender add-on) https://github.com/sakalond/StableGen
- blender-mcp (Poly Haven / Sketchfab / Hyper3D tools): https://github.com/ahujasid/blender-mcp
- US Copyright Office — AI and copyrightability: https://www.copyright.gov/ai/
- Agent skills reviewed and partly merged (MIT): RobLe3/cc-blender-skill (`blender-materials`, `blender-uv-texturing`: disabled-socket lookup, glass absorption, bake active-node rule) https://github.com/RobLe3/cc-blender-skill ; ra100/blender-claude-plugin (`blender-shader-nodes`: bl_idname traps, 5.x node changes) https://github.com/ra100/blender-claude-plugin ; arjun988/blender-skills (`texture-workflow`: ORM packing, cage values) https://github.com/arjun988/blender-skills. Others surveyed were too thin to use.

## 9. Environment, flora, fauna
- Blender 5.0 modeling release notes (Geometry-Nodes modifiers: Array, Scatter on Surface, Curve to Tube…): https://developer.blender.org/docs/release_notes/5.0/modeling/
- Distribute Points on Faces, Realize Instances, Ocean modifier, Sky Texture, Simplify (manual): https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/point/distribute_points_on_faces.html , https://docs.blender.org/manual/en/latest/modeling/modifiers/physics/ocean.html , https://docs.blender.org/manual/en/latest/render/shader_nodes/textures/sky.html
- EEVEE 4.2 migration (Render Method, world volume behavior, thickness): https://developer.blender.org/docs/release_notes/4.2/eevee_migration/
- A.N.T. Landscape: https://extensions.blender.org/add-ons/antlandscape/ ; Sapling Tree Gen: https://extensions.blender.org/add-ons/sapling-tree-gen/ ; BlenderGIS SRTM: https://github.com/domlysz/BlenderGIS/wiki/SRTM
- Phyllotaxis / golden angle: https://mathworld.wolfram.com/Phyllotaxis.html ; Leonardo's rule (Eloy 2011): https://arxiv.org/pdf/1105.2591
- Unity LOD import naming: https://docs.unity3d.com/6000.0/Documentation/Manual/importing-lod-meshes.html ; Unreal Impostor Baker: https://dev.epicgames.com/documentation/en-us/unreal-engine/impostor-baker-plugin-in-unreal-engine ; Pivot Painter 2: https://dev.epicgames.com/documentation/unreal-engine/pivot-painter-tool-2.0-in-unreal-engine
- Hair node groups & Sculpt Curves (manual): https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/hair/index.html , https://docs.blender.org/manual/en/latest/sculpt_paint/curves_sculpting/index.html ; Principled Hair (Chiang/Huang): https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/hair_principled.html
- Foot posture: https://www.britannica.com/science/digitigrade-posture ; Rigify metarigs: https://docs.blender.org/manual/en/latest/addons/rigify/basics.html ; Lengyel et al., real-time fur (shells & fins): https://hhoppe.com/fur.pdf

## 10. Blender bridges / MCP
- Official Blender MCP (add-on + server; tools, NUL-framed protocol, deferred replies): https://projects.blender.org/lab/blender_mcp ; https://www.blender.org/lab/mcp-server/
- Community blender-mcp (addon.py + server command protocol): https://github.com/ahujasid/blender-mcp

## 11. 3D printing, jewelry & CAD
- Formlabs, *Jewelry 3D Printing: Basic Design Parameters, Supports and Orientation* (white paper); Covestro/Bayer, *Snap-Fit Joints for Plastics — A Design Guide*; Stuller Bench Jeweler, *Creating Master Models*
- 3D Print Toolbox source: https://projects.blender.org/extensions/print3d_toolbox ; ring size chart (ISO 8653): https://ringsize.io ; build123d docs: https://build123d.readthedocs.io
- Round brilliant proportions (Tolkowsky ideal cut) and ISO 8653 ring sizes (inner circumference in mm) — used by `scripts/ring_builder.py`
- Wall-thickness guides from print services (JLC3DP, Formlabs, Sinterit) — values differ by process; check the chosen service

## 12. Pipeline & interchange
- Blender manual: Library Overrides https://docs.blender.org/manual/en/latest/files/linked_libraries/library_overrides.html ; Link & Append https://docs.blender.org/manual/en/latest/files/linked_libraries/link_append.html ; USD https://docs.blender.org/manual/en/latest/files/import_export/usd.html ; Alembic https://docs.blender.org/manual/en/latest/files/import_export/alembic.html
- Release notes 5.0–5.2 Pipeline & I/O, Core (packed data), Assets: https://developer.blender.org/docs/release_notes/5.2/pipeline_io/

## 13. Texture painting & Ucupaint
- Blender manual — Texture Paint: https://docs.blender.org/manual/en/latest/sculpt_paint/texture_paint/index.html
- Ucupaint: https://extensions.blender.org/add-ons/ucupaint/ ; wiki https://ucupumar.github.io/ucupaint-wiki/ ; source https://github.com/ucupumar/ucupaint (operators `bpy.ops.wm.y_*`)

## 14. Vector, text & voxel
- Blender manual — Text properties (fill solver/rule): https://docs.blender.org/manual/en/latest/modeling/texts/properties.html ; SVG as Grease Pencil: https://docs.blender.org/manual/en/latest/files/import_export/grease_pencil_svg.html ; 5.1 modeling notes (Delaunay text fill): https://developer.blender.org/docs/release_notes/5.1/modeling/
- MagicaVoxel .vox extension: https://extensions.blender.org/add-ons/blender-magicavoxel/ ; bundled `io_curve_svg` add-on source (unit table, 90 px/in)

## 15. Mesh repair & intake
- bmesh operators (holes_fill, remove_doubles, symmetrize, triangle_fill, bisect_plane): https://docs.blender.org/api/current/bmesh.ops.html
- Manual — Remesh, Decimate, Retopology (QuadriFlow), Cycles baking: https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/remesh.html , https://docs.blender.org/manual/en/latest/modeling/modifiers/generate/decimate.html , https://docs.blender.org/manual/en/latest/modeling/meshes/retopology.html , https://docs.blender.org/manual/en/latest/render/cycles/baking.html

## 16. Rendering & compositing
- Release notes: 5.0 compositor/Python API/Cycles/EEVEE https://developer.blender.org/docs/release_notes/5.0/compositor/ ; 5.1 compositor https://developer.blender.org/docs/release_notes/5.1/compositor/ ; 5.2 Cycles https://developer.blender.org/docs/release_notes/5.2/cycles/
- Manual — Cycles object settings (caustics/MNEE flags, shadow catcher): https://docs.blender.org/manual/en/latest/render/cycles/object_settings/object_data.html
- Cycles source (MNEE implementation) `intern/cycles/kernel/integrator/mnee.h`, blender-v5.2-release branch

## 17. Simulation
- Physics release notes 5.0 / 5.2: https://developer.blender.org/docs/release_notes/5.0/physics/ , https://developer.blender.org/docs/release_notes/5.2/physics/
- Manual — Rigid Body Constraints (breaking), Fluid Flow (source, initial velocity), Fluid Domain (adaptive domain): https://docs.blender.org/manual/en/latest/physics/rigid_body/constraints/index.html , https://docs.blender.org/manual/en/latest/physics/fluid/type/flow.html , https://docs.blender.org/manual/en/latest/physics/fluid/type/domain/index.html
- XPBD node-based simulation design: https://developer.blender.org/docs/features/nodes/xpbd_simulation/ ; Cell Fracture extension: https://extensions.blender.org/add-ons/cell-fracture/

## 18. Stylized / NPR & Grease Pencil
- Grease Pencil v3 migration (4.3): https://developer.blender.org/docs/release_notes/4.3/grease_pencil_migration/ ; 5.0 Python API renames: https://developer.blender.org/docs/release_notes/5.0/python_api/ ; 5.1 / 5.2 Grease Pencil notes: https://developer.blender.org/docs/release_notes/5.1/grease_pencil/ , https://developer.blender.org/docs/release_notes/5.2/grease_pencil/

## 19. UV & baking
- Blender 4.3 modeling & UV notes (Minimum Stretch / SLIM unwrap): https://developer.blender.org/docs/release_notes/4.3/modeling/ ; UDIM baking (3.2 Cycles): https://developer.blender.org/docs/release_notes/3.2/cycles/
- Manual — UV editing & UDIMs: https://docs.blender.org/manual/en/latest/modeling/meshes/uv/index.html
- Adobe Substance 3D Painter — project configuration & bake matching by mesh name: https://helpx.adobe.com/substance-3d-painter/baking/common-parameters.html ; Marmoset Toolbag bake groups: https://marmoset.co/toolbag/learn/

## 20. Vehicle interiors & automotive paint
- Seating reference (SAE J1100 dimensions, H-point): https://engineeringcheatsheet.com/sae-j1100-motor-vehicle-dimensions/ ; interior gap/flush measurement: http://www.origintech.com/uploaded/files/LaserGauge/LaserGauge-ApplicationDatasheet-Gap-and-Flush-Automotive-Interior.pdf
- Plastic grain depth: https://www.plasticomould.com/info/how-to-define-the-leather-lines-on-the-plastic-77541788.html ; perforated leather patterns: https://www.coast2coastleather.com/pages/perforated-leather ; steering wheel sizes: https://engineerfix.com/what-is-the-standard-size-of-a-steering-wheel/

## 21. Anime face shading
- NoiRC256/URPSimpleGenshinShaders (FdotL flip + step((-FdotL+1)/2, map) convention): https://github.com/NoiRC256/URPSimpleGenshinShaders ; akasaki1211/sdf_shadow_threshold_map (SDF interpolation of shadow masks): https://github.com/akasaki1211/sdf_shadow_threshold_map

## 22. Blender release notes (5.x) used for API fixes
- Rendering 5.2 (Thin Wall) https://developer.blender.org/docs/release_notes/5.2/rendering/ ; Rendering 5.1 (Normal Map convention) https://developer.blender.org/docs/release_notes/5.1/rendering/ ; Python API 4.4 (stroke pen_flip) https://developer.blender.org/docs/release_notes/4.4/python_api/ ; 3MF import/export extension https://extensions.blender.org/add-ons/threemf-io/
- Release notes 5.1, 5.2 LTS and 5.3, all pages, read as raw Markdown (source of `blender-version-changes.md`, checked 2026-11-12): https://projects.blender.org/blender/blender-developer-docs/src/branch/main/docs/release_notes ; index https://developer.blender.org/docs/release_notes/

## 23. Animation & rigging (5.x)
- Slotted actions upgrade guide: https://developer.blender.org/docs/release_notes/4.4/upgrading/slotted_actions/ ; 5.0 Python API: https://developer.blender.org/docs/release_notes/5.0/python_api/ ; 5.2 animation & rigging: https://developer.blender.org/docs/release_notes/5.2/animation_rigging/
- glTF and FBX exporters (manual): https://docs.blender.org/manual/en/latest/addons/import_export/scene_gltf2.html , https://docs.blender.org/manual/en/latest/files/import_export/fbx.html
- Viseme / blend shape sets: ARKit https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation ; Oculus Lipsync https://developers.meta.com/horizon/documentation/unity/audio-ovrlipsync-viseme-reference/

## 24. Rigging & lip-sync
- Rhubarb Lip Sync (output formats, Preston Blair mouth shapes): https://github.com/DanielSWolf/rhubarb-lip-sync
- Rigify source bundled with Blender 5.2 (`addons_core/rigify/generate.py`, `base_generate.py`)

## 25. Game & web delivery
- Meta performance targets (standalone): https://developers.meta.com/horizon/documentation/unity/unity-perf/ ; PC VR guidelines: https://developers.meta.com/horizon/documentation/native/pc/dg-performance-guidelines/
- Unreal FBX static mesh pipeline: https://dev.epicgames.com/documentation/en-us/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine ; Unity LOD mesh import: https://docs.unity3d.com/6000.0/Documentation/Manual/importing-lod-meshes.html ; Godot scene import (node type customization, mesh LOD): https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/
- glTF Transform CLI (meshopt/KTX2/WebP, validation workflows): https://gltf-transform.dev/cli
- glTF 2.0 specification (GLB container: header + JSON chunk): https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html ; KHR_materials_variants: https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_materials_variants

## 26. Archviz
- Blender manual — Sky Texture, Light objects (power units, portals), Cycles light settings, Principled BSDF (Thin Wall): https://docs.blender.org/manual/en/latest/render/shader_nodes/textures/sky.html , https://docs.blender.org/manual/en/latest/render/lights/light_object.html , https://docs.blender.org/manual/en/latest/render/cycles/light_settings.html , https://docs.blender.org/manual/en/latest/render/shader_nodes/shader/principled.html
- Release notes 5.0–5.2 (Sky types, color management working space, EEVEE rename/raytracing, Cycles, I/O, remote assets): https://developer.blender.org/docs/release_notes/5.0/color_management/ , https://developer.blender.org/docs/release_notes/5.2/cycles/ , https://developer.blender.org/docs/release_notes/5.2/eevee/ , https://developer.blender.org/docs/release_notes/5.2/pipeline_io/
- Thin Wall mode (5.2): https://80.lv/articles/how-blender-5-2-lts-s-thin-wall-mode-works ; Khronos PBR Neutral: https://www.khronos.org/news/press/khronos-pbr-neutral-tone-mapper-released-for-true-to-life-color-rendering-of-3d-products
- NOAA solar position equations (General Solar Position Calculations): https://gml.noaa.gov/grad/solcalc/solareqns.PDF
- Albedo reference chart: https://shinsoj.artstation.com/blog/Q9j6/pbr-color-space-conversion-and-albedo-chart
- Extensions: Bonsai https://extensions.blender.org/add-ons/bonsai/ ; Import AutoCAD DXF https://extensions.blender.org/add-ons/import-autocad-dxf-format-dxf/ ; MeasureIt https://extensions.blender.org/add-ons/measureit/ ; Sun Position https://extensions.blender.org/add-ons/sun-position/ ; DWG→DXF via ODA File Converter https://www.blender3darchitect.com/cad/convert-dwg-files-without-autocad-for-blender/
- Dimensions: stairs (Blondel / IRC) https://remodelcalculators.com/blog/stairs-building-guide ; doors https://www.sizemarker.com/dimensions/standard-door-sizes ; worktops https://www.egger.com/en/blog/kitchen-worktop-height-guide ; wall thickness https://plan7architect.com/wall-thickness-for-interior-walls-exterior-walls-and-load-bearing-walls-ai1/
- Blender → Unreal 5.7 pipeline notes: https://www.strayspark.studio/blog/blender-5-to-unreal-engine-57-asset-pipeline-2026

## 27. Large sets & cities
- Insomniac — *Procedurally Crafting Manhattan for Marvel's Spider-Man* (GDC 2019): https://media.gdcvault.com/gdc2019/presentations/santiago_david_procedurally_crafting_manhattan.pdf
- Lynch's five elements (paths, edges, districts, nodes, landmarks): https://www.architecturecourses.org/design/kevin-lynchs-5-elements-city-guide-urban-design
- NACTO Urban Street Design Guide (lane widths, sidewalks): https://nacto.org/publication/urban-street-design-guide/
- Parish & Müller 2001, *Procedural Modeling of Cities*: https://cgl.ethz.ch/Downloads/Publications/Papers/2001/p_Par01.pdf ; Chen et al. 2008, *Interactive Procedural Street Modeling*: https://www.sci.utah.edu/~chengu/street_sig08/street_project.htm ; Vanegas et al. 2012, *Procedural Generation of Parcels*: https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-8659.2012.03047.x
- CityEngine CGA split/extrude/comp: https://doc.arcgis.com/en/cityengine/latest/cga/cga-split.htm
- Blosm (OSM import) premium vs free: https://github.com/vvoovv/blosm/wiki/Premium-Version ; Building Tools: https://github.com/ranjian0/building_tools ; iCity: https://superhivemarket.com/products/icity
- Godot large world coordinates (float precision by distance): https://github.com/godotengine/godot-docs/blob/4.2/tutorials/physics/large_world_coordinates.rst
- Unreal World Partition / HLOD / Level Instancing / Nanite content: https://dev.epicgames.com/documentation/en-us/unreal-engine/world-partition-in-unreal-engine ; Unity static batching & GPU Resident Drawer: https://docs.unity3d.com/6000.0/Documentation/Manual/urp/gpu-resident-drawer.html ; Godot visibility ranges: https://docs.godotengine.org/en/stable/tutorials/3d/visibility_ranges.html

## 28. Modular kits & WFC
- Joel Burgess — *Skyrim's Modular Level Design* (GDC 2013): http://blog.joelburgess.com/2013/04/skyrims-modular-level-design-gdc-2013.html
- The Level Design Book — modular kits (loopback/stack/gap tests): https://book.leveldesignbook.com/process/blockout/metrics/modular
- Beyond Extent — balancing modularity and uniqueness: https://www.beyondextent.com/articles/balancing-modularity-and-uniqueness-in-environment-art ; Ian London — modular kit geometry: https://ianlondon.github.io/posts/modular-level-kit-geometry/
- mxgmn/WaveFunctionCollapse (overlapping & simple tiled models, XML format): https://github.com/mxgmn/WaveFunctionCollapse
- marian42 — infinite city WFC (socket connectors): https://marian42.de/article/wfc/ ; Martin Donald's WFC video notes: https://christianjmills.com/posts/wave-function-collapse-for-3d-notes/index.html ; Primarter/WaveFunctionCollapse (Blender face profiles): https://github.com/Primarter/WaveFunctionCollapse
- Boris the Brave — tileset classification, quarter-tile autotiling, WFC tips; DeBroglie constraints; Tessera: https://www.boristhebrave.com/2021/11/14/classification-of-tilesets/ , https://www.boristhebrave.com/2020/02/08/wave-function-collapse-tips-and-tricks/ , https://boristhebrave.github.io/DeBroglie/articles/constraints.html , https://www.boristhebrave.com/docs/tessera/6/
- Godot GridMap/MeshLibrary: https://github.com/godotengine/godot-docs/blob/master/tutorials/3d/using_gridmaps.rst ; Unreal WFC plugin API: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/PluginIndex/WaveFunctionCollapse

## 29. Kitbashing
- ILM greebles history: https://www.denofgeek.com/movies/greebles-how-tiny-details-make-a-huge-star-wars-universe/
- Neil Blevins — primary/secondary/tertiary shapes and areas of visual rest: http://www.neilblevins.com/art_lessons/art_lessons.htm
- Blender asset catalogs (cats.txt format): https://developer.blender.org/docs/features/asset_system/backend/asset_catalogs/ ; 5.0 asset changes (Pack import): https://developer.blender.org/docs/release_notes/5.0/assets/ ; remote asset libraries (5.2): https://docs.blender.org/manual/en/latest/files/asset_libraries/remote_asset_libraries.html ; snapping (4.0 Snap Base): https://developer.blender.org/docs/release_notes/4.0/modeling/
- KIT OPS: https://chippwalters.com/kit-ops.html ; MESHmachine plugs: https://machin3.io/MESHmachine/docs/plug_creation/ ; DECALmachine: https://machin3.io/DECALmachine/docs/
- Licenses: KitBash3D https://kitbash3d.com/pages/licenses ; Big Medium Small https://www.bigmediumsmall.com/license-agreement ; BlenderKit https://www.blenderkit.com/docs/licenses/ ; Sketchfab https://sketchfab.com/licenses ; third-party assets in client work (OWE Legalities 45) https://www.owe.com/resources/legalities/legalities-45-photobashing-kitbashing-what-are-best-practices-for-using-third-party-digital-assets-in-client-projects/

## 30. Hard Ops
- Hard Ops manual (hotkeys, sSharpen/cSharpen/Step, booleans, sorting, bWidth): https://hardops-manual.readthedocs.io/en/latest/
- Product pages: https://superhivemarket.com/products/hardopsofficial ; https://masterxeon1001.gumroad.com/l/hardops
- Hard Ops thread (version/compatibility notes, 4.1 smoothing issues): https://blenderartists.org/t/hard-ops-thread/657591
- Blender 4.1 auto smooth removal: https://developer.blender.org/docs/release_notes/4.1/modeling/

## 31. Merged from the img2threejs skill (image→procedural 3D)
- Layered image-observation protocol, detail inventory taxonomy, surface-class decision tree, head-unit/landmark measurement, review-by-layer, turntable and cross-section ("2.5D slab") checks, mirror-vs-rotation for L/R pairs, and the "report what changed vs. what still doesn't match" discipline were adapted from https://github.com/img2threejs/img2threejs (Apache-2.0). Its pipeline machinery was translated into Blender-native equivalents rather than copied: state/gate discipline → `quality-gates.md` + `project_state.py`/`silhouette_compare.py`/`scene_gates.py`; layer ontology → `character-modeling.md`, rig/animation gates → `rigging-and-weights.md` + `rig_check.py`/`scalp_exposure.py`; action-ready hierarchy and attachment contract → `assembly-and-hierarchy.md`; Three.js material recipes → `materials-and-lookdev.md` (Principled BSDF).
