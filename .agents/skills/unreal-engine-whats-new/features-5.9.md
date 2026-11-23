# New features in UE 5.9, by area

**[notes]** items come from Epic's "Unreal Engine 5.9 Preview Release Notes" (<https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-9-release-notes>, last updated 2026-11-09) and its Unreal Canvas overview page. The notes give status labels for few items and almost no code names. **[disk]** items were read from the installed engine (CL 60351404) on 2026-11-12. Plugin names in backticks are listed with their status in [`plugins-added-in-5.9.md`](plugins-added-in-5.9.md).

## Gameplay, AI and Mass

- **Progressive navmesh build.** [notes] The navmesh can build progressively, with control over tiles built per tick, and can keep tiles outside the invoker radius. [disk] On `ARecastNavMesh`: `bEnableProgressiveBuild`, `MaxCoverageTilesPerTick` (default 16), `MaxCoverageInitialScanTilesPerTick` (default 256). On `UNavigationSystemV1`: `bPreserveTilesOutsideInvokerRadius`, `SetPreserveTilesOutsideInvokerRadius(bool)`.
- **StateTree editing from Blueprint or Python.** [notes] Tasks, considerations, evaluators and global tasks can be added and rearranged in code. [disk] `UStateTreeEditingSubsystem` (module `StateTreeEditorModule`) exposes node data getters and setters, `SetTaskEnabled`, `SetTaskConsideredForCompletion`, `SetConditionEvaluationMode` and `CompileStateTreeWithResult`; new headers `StateTreeBindingQuery.h`, `StateTreeEditorResult.h`, `StateTreeCompilerLogMessage.h`.
- **Mass Characters.** [notes] Mass traits for character interpolation and visualisation, selective pawn replication, and a game feature action that sets up Mass characters. [disk] Plugin `MassCharacters`, module `MassCharactersRuntime`, `MassCharacterSubsystem.h`; also a new `MassNetworkSubsystem.h` in `MassGameplay`.
- **EQS.** [disk] New item type `EnvQueryItemType_OrientedPoint`.

## Editor scripting (Python and Editor Utility Blueprints)

- [notes] New functions create and edit Blueprints, graphs, nodes and variables; Chooser tables, StateTrees, Dataflow graphs and PCG graphs are editable from script; PCG scripts can read and write custom HLSL node source and add and validate graph edges; Python can manage extra search paths.
- [disk] New script-facing classes: `UChooserTableEditorLibrary`, `UDataflowScriptingSubsystem`, `UDeformerGraphScriptingSubsystem`, `UMapCheckSubsystem` (Map Check with Blueprint logging), `UWidgetBlueprintEditorSubsystem`, `UUserAssetTagsEditorSubsystem`, `LandscapeEditorSubsystem.h`, `UControlRigAssetReferenceLibrary`, `URigHierarchyKeyLibrary`, `USequencerAnimToolsEditorLibrary`, `AssetScriptingUtils.h`, `PCGEditorScriptingTypes.h`, and audio editor subsystems (`AudioPreviewSubsystem.h`, `SoundCueEditorSubsystem.h`, `AudioEditorScriptingUtils.h`). Confirm the Python spelling with `help(unreal.<Class>)`.
- **`GraphDsl`** [disk]: an S-expression language for authoring and editing graph assets; `BlueprintToolsets` builds a Blueprint Graph DSL on it for agents.
- [notes] The Python Foundation Packages plugin was removed. [disk] `Engine/Plugins/Experimental/PythonFoundationPackages` is still present in this build, so treat the removal as pending.
- [disk] The embedded interpreter is Python 3.11.

## AI tooling inside the editor

- [notes] Unreal MCP gains Editor Preferences for the server port, allowed origins and the highest accepted protocol version, plus a project-level Model Context Protocol settings page. [disk] `UModelContextProtocolSettings` holds `bAutoStartServer`, `AdditionalAllowedOrigins`, `bEnableToolSearch`, `ClientSelection`; `UModelContextProtocolProjectSettings` holds project `Instructions`.
- [notes] A **Toolset Registry** controls which toolsets agents may use; an **MCP Client** toolset manages external MCP servers; a **Knowledge Base** answers queries from live engine state or markdown on disk. [disk] New runtime module `ToolsetCore`; plugins `KnowledgeBase`, `KnowledgeBaseToolset`, and 25 toolset plugins added under `Experimental/Toolsets` (Blueprint, console, file system, input injection, navmesh, performance, scene capture, widget animation, MetaSound and others).
- [notes] **Unreal Assistant**: notification preferences, hand-off to an external agent through a custom command, a live AI-processed viewport preview, and a tool-access setting with levels Ask, Read, Edit, Auto, Full. [disk] `EAIAssistantToolAccessPreference` in plugin `AIAssistant`.
- [notes] Generative-service integrations: Fab image and mesh generation, chat completion, ElevenLabs voice, Google Gemini, Claude Code.
- **Unreal Canvas** [notes, Experimental]: a web-based shared workspace, served locally, where people and agents create text, images, video and meshes. Plugins `UnrealCanvasBridge` (requires `ModelContextProtocol`; exposes Movie Render Graph as MCP tools), `UnrealCanvasAnnotations`, `UnrealCanvasGraph`. It downloads optional models (about 1.8 GB) after a consent dialog, imports to `/Game/Merlin` by default, and its cutout actors are editor-only and must be reviewed before cooking. It is unrelated to the UMG Canvas Panel.

## Rendering and lighting

- **Lumen World Cache** [notes]: Lumen stores lighting where rays hit surfaces, built at runtime by path tracing; no mesh cards; needs Hardware Ray Tracing; enabled per project. [disk] Console variables under `r.Lumen.WorldCache.*` (`Allowed`, `MaxBounces`, `CellDensity`, `Debug`, `Freeze`).
- **Adaptive Voxel-Based Order Independent Transparency (AVBOIT)** [notes]: correct blending of overlapping translucency regardless of draw order, for Nanite and non-Nanite; translucent materials must output only their own colour. [disk] Console variables under `r.AVBOIT.*`.
- **Far shadows** [notes]: can update at their own rate and be switched per component. [disk] `UPrimitiveComponent::bCastFarShadow`, `SetCastFarShadow(bool)`.
- **Shadow debugging** [notes]: a Virtual Shadow Map Overview mode, cascade-colouring and depth-tile views for cascaded shadow maps, and a Far Shadow view.
- **Nanite culling** [notes]: automatic; no content changes.
- **Dynamic Wind for Nanite foliage** [notes, Experimental]: GPU per-bone sway and flutter with radial, swirl, cone, directional and character-brush forces, and a lighter stylised mode. [disk] Plugin `DynamicWind`, which already existed in 5.8.
- [disk] New `AAmbientLightingVolume` / `UAmbientLightingVolumeComponent`, and plugin `GaussianSplat` (Experimental); neither is in the notes.

## Animation and rigging

- [notes] **IK Retargeter** gains Proximity IK, Pelvis Volume and Limb Twist operations.
- [notes] **Control Rig** can be referenced as an asset as well as a class; several older Blueprint nodes are deprecated for asset-reference versions. [disk] `ControlRigAssetReferenceLibrary.h`; 135 of the 376 `UE_DEPRECATED(5.9` markers are in the ControlRig module.
- [notes] **Unreal Animation Framework (UAF)**, still Experimental on disk: new node and layering settings, a notify system with Play Sound and Play Niagara Effect handlers (`UAFDefaultNotifies`), StateTree conditions "Animation Is Looping" and "Animation Time Remaining". [disk] UAF's public headers were reorganised (31 removed, 260 added across the `UAF` plugins): code written against 5.8's UAF needs re-reading.
- [notes] AI animation generation: `UAFAnimGen`, `AnimGenOffline` (generated animation in Sequencer), `Kimodo` (NVIDIA; trajectories, key poses, text prompts). All Experimental.

## World building

- [notes] **PCG**: a Concave Hull node; script access to custom HLSL node source and graph edges.
- [notes] **Mesh Partition**: simplification settings, a ray-tracing proxy option, better PCG interop. **Shallow-water rivers**: actor exclusion from capture, collision resolution, a water-input paint tool. **World Partition**: more Blueprint functions and Data Layer nodes (child layers; checking whether an actor can join a layer).

## Editor, UI and Sequencer

- [notes] **Sequencer** marked frames become marks and mark ranges, with Blueprint nodes and preferences for duration, snapping and playback (API change in `deprecations-5.9.md`).
- [notes] **UMG**: widget components can output depth and velocity; editable text gains selection events and colours; list and tile views gain orientation and selection options; Common UI adds editor passthrough commands. [disk] New debugging aids: `UMGDebuggerSubsystem.h`, a `CommonUIDebugging` module, and plugins `SlateDebugger` (on by default), `WidgetFinder`.
- [notes] **Forge**: web-based designer tools inside the editor. Not found as a plugin on disk under that name.
- [disk] New editor module `EditorViewport`; plugin `DebugDraw` (`UE::DebugDraw::*`, a high-volume alternative to `DrawDebugLine`).

## Core, build and platforms

- **Modular Test Framework** [notes]: write and run scoped plugin tests. [disk] Plugins `ModularTestFramework`, `ModularTestResolver`, `ModularTestRunnerEditor` (Experimental).
- **WebAssembly target** [notes, Experimental] with WebGPU rendering. [disk] `Engine/Platforms/Wasm`.
- [disk] New runtime modules: `AsyncFunctionResult`, `ShaderRuntime`, `ToolsetCore`, `PlatformWriteMonitor`. New Core headers include `Algo/ParallelSort.h`, `Containers/StripedSet.h`, `Misc/ScopedTemporaryDirectory.h`, `Tasks/TickingPipe.h`.
- [disk] Windows toolchain (`Engine/Config/Windows/Windows_SDK.json`): preferred MSVC 14.50.35717+ (VS 2026 18.0) or 14.44.35207+ (VS 2022 17.14); minimum 14.38.33130; Windows SDK 10.0.26100; .NET 10.
- [disk] Other new plugins outside the notes: `AssetProvenance` and `ProvenanceC2PA` (content credentials), `LoreSourceControl` (on by default), `IoStorePrioritization` (Beta), `NNERuntimeLiteRT`.
