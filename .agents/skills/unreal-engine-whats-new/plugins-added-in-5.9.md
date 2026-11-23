# Plugins added in UE 5.9

Every engine plugin present in `UE_5.9/Engine/Plugins` (CL 60351404) and absent from `UE_5.8` (5.8.4), read from each `.uplugin` on 2026-11-12. The name column is what goes in a `.uproject` `Plugins` entry. All are off by default except `GPUReshapeEditor`, `LoreSourceControl` and `SlateDebugger`. An empty status means the descriptor carries neither the Experimental nor the Beta flag.

Removed in 5.9: `GPUReshape` (now `GPUReshapeEditor`), `SemanticSearchToolset`, `UMGToolSet`.

| Folder under `Engine/Plugins` | Plugin name | Status | Descriptor's description |
|---|---|---|---|
| `Developer/Provenance/AssetProvenance` | `AssetProvenance` |  | Reads and writes provenance data recording the origin and edit history of assets. |
| `Developer/Provenance/ProvenanceC2PA` | `ProvenanceC2PA` | Experimental | Implements AssetProvenance's read/write provenance data using the C2PA content credentials standard. |
| `Developer/UnrealCanvas/UnrealCanvasAnnotations` | `UnrealCanvasAnnotations` | Experimental | Self-contained 3D spatial annotation placement, the scene/GBuffer capture core (UnrealCanvasAnnotationsCapture module), rendering hooks, and MCP tools... |
| `Developer/UnrealCanvas/UnrealCanvasBridge` | `UnrealCanvasBridge` | Experimental | Exposes MRG rendering as MCP tools for Unreal Canvas. Requires the ModelContextProtocol plugin to be enabled. |
| `Developer/UnrealCanvas/UnrealCanvasGraph` | `UnrealCanvasGraph` | Experimental | Native Slate editor for Unreal Canvas canvases. UnrealCanvasClient owns the canvas document model and the server client; UnrealCanvasAssetCache turns result... |
| `Editor/GPUReshapeEditor` | `GPUReshapeEditor` |  | GPU Reshape editor integration |
| `Editor/ModularTestRunnerEditor` | `ModularTestRunnerEditor` |  | Editor utilities for Modular Test Framework. |
| `Experimental/AgentCapability` | `AgentCapability` | Experimental | Passive discovery of configured agent plugin and workspace capabilities. |
| `Experimental/AgentLook` | `AgentLook` | Experimental | Fixed-view camera driver for look comparisons (UE 5.9): Look.Run <views.json> puts the player's view on each listed camera, settles, captures (engine... |
| `Experimental/Animation/AnimGenOffline` | `AnimGenOffline` | Experimental | Add support for offline generated animations inside sequencer. |
| `Experimental/Animation/Kimodo` | `Kimodo` | Experimental | Kimodo plugin for the AnimGenOffline framework |
| `Experimental/ChaosComposableSolver` | `ChaosComposableSolver` | Experimental | Chaos Composable Solver |
| `Experimental/DebugDraw` | `DebugDraw` | Experimental | Lock-free, post-tonemap shape rendering for debug visualization (UE::DebugDraw::*). Alternative to ULineBatchComponent / DrawDebugLine for high-volume debug... |
| `Experimental/Doodle` | `Doodle` | Experimental |  |
| `Experimental/GameplayCaptureInterfaces` | `GameplayCaptureInterfaces` | Experimental | Shared modular-feature interfaces used by GameplayCapture related plugins. Hosts engine-level declarations so these plugins can interoperate without... |
| `Experimental/GraphDsl` | `GraphDsl` | Experimental | S-expression language runtime for authoring and editing Unreal graph assets. |
| `Experimental/KnowledgeBase` | `KnowledgeBase` | Experimental | Query interface over knowledge bases derived from live engine state or read from markdown on disk. |
| `Experimental/LoreCore` | `LoreCore` | Experimental | Provides a uniform way of loading and initializing the Lore library |
| `Experimental/LoreSourceControl` | `LoreSourceControl` | Experimental | Lore version control management |
| `Experimental/MassCharacters` | `MassCharacters` | Experimental |  |
| `Experimental/NNE/NNERuntimeLiteRT` | `NNERuntimeLiteRT` | Experimental | A Neural Network Engine (NNE) runtime backed by Google LiteRT. |
| `Experimental/SlateDebugger` | `SlateDebugger` | Experimental | Records Slate focus and navigation events in the editor and exposes them to Python and AI tools through USlateDebuggerSubsystem. |
| `Experimental/Toolsets/AgentPluginToolset` | `AgentPluginToolset` | Experimental | Reads Claude and Codex agent plugins, plus working-directory instruction files, through the AI Toolset Registry. |
| `Experimental/Toolsets/AllMetaHumanToolsets` | `AllMetaHumanToolsets` | Experimental | Aggregator plugin that depends on all MetaHuman Toolsets plugins. |
| `Experimental/Toolsets/BlueprintToolsets` | `BlueprintToolsets` | Experimental | AI assistant toolsets for Blueprint assets, including the Blueprint Graph DSL. |
| `Experimental/Toolsets/CaptureManagerToolset` | `CaptureManagerToolset` | Experimental | Toolset for ingesting Capture Manager takes (mono/stereo video, LiveLink Face, take archives, calibration) via the AI Assistant. |
| `Experimental/Toolsets/CheatsToolset` | `CheatsToolset` | Experimental | Toolset for listing and calling cheat commands on the local player's cheat manager. |
| `Experimental/Toolsets/CommonUIToolset` | `CommonUIToolset` | Experimental | AI debugger toolset for CommonUI activation & focus routing: activatable-tree snapshots, focus divergence diagnosis, activation/routing event recording, and... |
| `Experimental/Toolsets/ConsoleToolset` | `ConsoleToolset` | Experimental | Toolsets for driving the engine's console subsystem (CVars and Exec commands) via the AI Toolset Registry. |
| `Experimental/Toolsets/FileSystemToolset` | `FileSystemToolset` | Experimental | Reads files, writes text, and downloads HTTPS resources through the AI Toolset Registry. |
| `Experimental/Toolsets/GeometryToolset` | `GeometryToolset` | Experimental | Gives AI assistants the ability to author procedural geometry — spawn DynamicMesh actors, append primitive shapes (boxes, cylinders, cones, spheres,... |
| `Experimental/Toolsets/InputToolset` | `InputToolset` | Experimental | Toolset for injecting Enhanced Input actions and legacy keys into a live Play-In-Editor or standalone game session via the AI Toolset Registry. |
| `Experimental/Toolsets/KnowledgeBaseToolset` | `KnowledgeBaseToolset` | Experimental | Toolset for discovering, searching, and writing knowledge bases via the AI Toolset Registry. |
| `Experimental/Toolsets/MediaToolset` | `MediaToolset` | Experimental | Tools for reading images and sampling video files, and the shared video reader and writer other toolsets record with. |
| `Experimental/Toolsets/MetaHumanAnimatorToolset` | `MetaHumanAnimatorToolset` | Experimental | AI Assistant tools for MetaHuman Performance footage inspection and animation generation. |
| `Experimental/Toolsets/MetaHumanCalibrationProcessingToolset` | `MetaHumanCalibrationProcessingToolset` | Experimental | Toolset exposing MetaHuman stereo camera calibration (solve + automatic frame selection) to the AI Assistant. |
| `Experimental/Toolsets/MetaHumanDepthGeneratorToolset` | `MetaHumanDepthGeneratorToolset` | Experimental | Toolset exposing MetaHuman stereo depth generation for footage capture data to the AI Assistant. |
| `Experimental/Toolsets/MetaHumanToolsetCore` | `MetaHumanToolsetCore` | Experimental | Shared utilities and toast notifications for MetaHuman and related AI toolsets. |
| `Experimental/Toolsets/MetaSoundToolset` | `MetaSoundToolset` | Experimental | Toolset for authoring and inspecting MetaSound graphs |
| `Experimental/Toolsets/MovieRenderPipelineToolset` | `MovieRenderPipelineToolset` | Experimental | Agent skills for using Movie Render Queue (MRQ) and Movie Render Graph (MRG), and editing their associated presets and graphs, through Python. |
| `Experimental/Toolsets/NavMeshToolset` | `NavMeshToolset` | Experimental | Read-only navmesh query toolset for AI assistants: setup discovery, build health, generation inputs, point and path queries, tiles, and actors on the mesh. |
| `Experimental/Toolsets/PerfToolset` | `PerfToolset` | Experimental | Toolsets for runtime performance profiling and triage (CPU, GPU, frame timing) via the AI Toolset Registry. |
| `Experimental/Toolsets/RewindDebuggerToolset` | `RewindDebuggerToolset` | Experimental | Read-only Rewind Debugger recording inspection tools. |
| `Experimental/Toolsets/SceneCaptureToolset` | `SceneCaptureToolset` | Experimental | Viewport video recording, scene diagnostics, game framebuffer capture and editor-camera capture. |
| `Experimental/Toolsets/TextureGraphToolset` | `TextureGraphToolset` | Experimental | Toolset for creating and inspecting TextureGraph assets. |
| `Experimental/Toolsets/WidgetAnimationToolset` | `WidgetAnimationToolset` | Experimental | AI assistant tools for authoring UWidgetAnimation: lifecycle and widget bindings on UMG Widget Blueprints. |
| `Experimental/Toolsets/WidgetStaticAnalysisToolset` | `WidgetStaticAnalysisToolset` | Experimental | AI assistant static-analysis tools over UMG widgets: widget tree descriptions, property override tracing, and binding/event/delegate connection maps. |
| `Experimental/UAF/UAFACLPlugin` | `UAFACLPlugin` | Experimental | UAF extension to the ACL plugin. |
| `Experimental/UAF/UAFAnimGen` | `UAFAnimGen` | Experimental | AnimGen for UAF |
| `Experimental/UAF/UAFDefaultNotifies` | `UAFDefaultNotifies` | Experimental | Default UAF notify subclasses plus native C++ notify handlers (Play Sound, Play Niagara Effect). Demonstrates the UAF native (C++) notify handler API. |
| `Experimental/UnrealConsoleRuntime` | `UnrealConsoleRuntime` |  | Shared UnrealConsole startup tail and run-mode dispatch. Runtime-loaded by UnrealEditor.exe -unrealconsole and statically linked into UnrealConsole.exe. |
| `Experimental/WidgetFinder` | `WidgetFinder` | Experimental | Find live Slate widgets by query. Mirrors the running widget tree into a queryable store and adds a browser panel that searches it and highlights matches on... |
| `Experimental/WidgetHelper` | `WidgetHelper` | Experimental | Shared utilities for the Widget Finder, Slate Inspector plugins. |
| `GaussianSplat` | `GaussianSplat` | Experimental | Gaussian Splat asset and ES3.1+ rendering. |
| `Media/SharedMemoryMedia` | `SharedMemoryMedia` |  | Implements a media output and a media source that share GPU textures between processes on the same machine. |
| `ModularTestFramework` | `ModularTestFramework` | Experimental | Engine-level framework for authoring and running scoped plugin tests. |
| `ModularTestResolver` | `ModularTestResolver` | Experimental | Plugin resolution interface for the ModularTestFramework. |
| `MovieScene/MovieRenderGraphPSD` | `MovieRenderGraphPSD` |  | Adds PSD output support to Movie Render Graph. |
| `Online/PolarisSurveys` | `PolarisSurveys` |  | In-product surveys served by Polaris (PRM): fetch, present, and report survey interactions and answers. Products plug in their own auth, targeting context,... |
| `Runtime/IoStorePrioritization` | `IoStorePrioritization` | Beta | Expression-based dynamic prioritization of IoStore I/O requests during streaming. |
| `Runtime/OpenXRRenderModel` | `OpenXRRenderModel` | Experimental | Enables the XRDeviceVisualizationComponent to load controller render models from OpenXR XR_EXT_render_model + XR_EXT_interaction_render_model when the... |
| `Runtime/OpenXRSpatialEntities` | `OpenXRSpatialEntities` | Beta | Implements the OpenXR XR_EXT_spatial_entity family (base, anchor, persistence, persistence_operations) for cross-vendor persistent spatial anchors. |
| `Tests/MaterialEditorTests` | `MaterialEditorTests` |  | MTF tests for the Material Editor's Python scripting API. |
| `Tests/ModularTestFrameworkTests` | `ModularTestFrameworkTests` | Experimental | Companion plugin that smoke-tests the Modular Test Framework itself. |
| `Tests/ModularTestRunnerUITests` | `ModularTestRunnerUITests` | Experimental | Companion plugin that tests the Modular Tests Runner editor UI. |
| `Tests/ModularTestUnmountFixture` | `ModularTestUnmountFixture` |  | Inert fixture the framework self-tests mount and unmount. Not a test companion; contains no tests. |
