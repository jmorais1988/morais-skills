---
name: unreal-engine-whats-new
description: Unreal Engine 5.8 and 5.9 changes that postdate model training - changed defaults, removed and deprecated API, Cascade's move out of the Engine module, new plugins, scripting libraries and renderer features. Use before writing or reviewing Unreal C++, Python or Blueprint for a UE 5.8/5.9 project, choosing or enabling an engine plugin or feature, or answering what a given Unreal version has.
---

Written against **UE 5.9 Preview** (`Build.version` 5.9.0). A model's Unreal knowledge stops at its training cutoff, so 5.9 is absent from it and 5.8 is thin at best. The installed engine is the source of truth: when memory and the engine disagree, the engine wins.

**Place yourself first.** Name the newest Unreal version whose features you can describe in detail without looking anything up. Everything after it is your gap. This skill covers 5.9 from Epic's Preview notes and an engine diff, and 5.8 from Epic's release notes and its deprecation markers.

## Look it up in the installed engine

Engine root: the Epic launcher installs to `C:\Program Files\Epic Games\UE_5.9\Engine` by default; otherwise read `InstalledDirectory` under the registry key `HKLM\SOFTWARE\EpicGames\Unreal Engine\5.9`. If `UE_5.8` is installed beside it, any question about what changed is a diff away.

| Question | Lookup |
|---|---|
| Does this class, function or property exist in 5.9? | Search `Engine/Source` and `Engine/Plugins` for it. Read the header before calling anything you recall from memory. |
| Which module and plugin own a header? | Its path: `.../Source/<Module>/Public/...`. Add `<Module>` to your module's `.Build.cs`, and the plugin to your `.uproject` when the path is under `Engine/Plugins`. |
| What was deprecated, and what replaces it? | Search headers for `UE_DEPRECATED(5.9` (376 hits) or `UE_DEPRECATED(5.8` (2,570 hits); the message names the replacement. |
| Is a plugin Experimental or Beta? | `IsExperimentalVersion` and `IsBetaVersion` in its `.uplugin`. |
| What console variables does a feature have? | Search `Engine/Source/Runtime/Renderer` (or the owning module) for `TEXT("r.<Prefix>`. |
| What can Python reach? | In the editor's Python console (or an MCP tool that runs editor Python): `help(unreal.<Class>)` or `dir(unreal)`. |

Treat a build warning `C4996` naming your own code as a fact about 5.9: read the message and switch to the replacement in the same change.

## 5.9 changes that break code written from memory

Each was read from the 5.9 source on 2026-11-12.

- **Cascade left the Engine module.** `UParticleSystemComponent`, `UParticleSystem`, the `Particles/...` module headers and the particle anim notifies (`AnimNotify_PlayParticleEffect`, `AnimNotifyState_TimedParticleEffect`, `AnimNotifyState_Trail`) now live in module `CascadeRuntime` of the `Cascade` plugin (`Engine/Plugins/FX/Cascade`, enabled by default); the Engine module keeps no forwarding headers. The shared base classes stay in Engine under new includes: `UFXSystemComponent` in `FXSystemComponent.h` and `UFXSystemAsset` in `FXSystemAsset.h`, which is what Niagara code includes. `UGameplayStatics::SpawnEmitterAtLocation` and `SpawnEmitterAttached` are deprecated for the same-named functions on `UCascadeFunctionLibrary` (`CascadeFunctionLibrary.h`). Prefer Niagara for new effects; code that must touch Cascade adds `"CascadeRuntime"` to its `.Build.cs`.
- **Sequencer marked frames are ranges.** `FMovieSceneMarkedFrame::FrameNumber` no longer drives the mark: read `GetStartFrame()` / `GetEndFrame()`, write `SetRange()` / `SetRangeStartAndEnd()`.
- **`TLazyObjectPtr` is deprecated** ("to be removed in 6.0"): use `TSoftObjectPtr`.
- **Type traits became concepts:** `TIsArray`, `TIsBoundedArray`, `TIsUnboundedArray` are deprecated for `UE::CArray`, `UE::CBoundedArray`, `UE::CUnboundedArray`.
- **StateTree:** compile from script with `UStateTreeEditingSubsystem::CompileStateTreeWithResult`, which returns the compiler's messages; `K2_CompileStateTree` is deprecated.
- **UMG editor scripting:** `FWidgetBlueprintOperationUtils` is replaced by `UWidgetBlueprintEditorSubsystem`.
- **Enhanced Input:** ignored keys are managed on `UEnhancedPlayerInput` (`IsKeyIgnored`, `AddIgnoredKey`, `RemoveIgnoredKey`).
- **Asset Manager:** `ScanPathsForPrimaryAssets` takes a `const FPrimaryAssetTypeInfo*`; the `UClass*` overload and the singular `ScanPathForPrimaryAssets` are deprecated.
- **Material IR headers were renamed:** `Materials/MaterialIR*.h` is now `Materials/MIR/MIR*.h`.

The full list for gameplay-facing modules is in [`deprecations-5.9.md`](deprecations-5.9.md): read it before touching Mass, MVVM, PCG, Movie Scene, navmesh queries, audio or the renderer's scene proxies.

## 5.8 changes

Read these when 5.8 is inside your gap.

- [`features-5.8.md`](features-5.8.md): changed defaults and breaking changes first (WASAPI replaces XAudio2 on Windows, Zen Server is the cooked output store, character movement bases now `FMovementBaseInterfaceData`, `UE_LOGF` replacing `UE_LOG`, the deprecated Enhanced Input combo trigger, `FJsonObject` keys, `FCoreDelegates::GetOnPostEngineInit()`, preview-platform renames, navmesh version 28), then new features by area (MegaLights production ready, Lumen Lite, Iris production ready, Mover, unified input, StateTree starting states, Unreal MCP's first release).
- [`release-notes-5.8-by-area.md`](release-notes-5.8-by-area.md): the whole 5.8 release notes condensed area by area (animation, audio, editor, core, framework, level design, platforms, rendering, simulation, UI, virtual production), bug fixes that change behaviour included. Search it by class, function, console variable or feature name.
- [`deprecations-5.8.md`](deprecations-5.8.md): 989 of 5.8's 2,570 deprecation markers, for the gameplay-facing modules. Search it for the header or class you are about to use.

With no 5.7 install there is nothing to diff, so API that 5.8 deleted outright appears only where the notes mention it. A remembered symbol that the engine search does not find has been removed: look for its replacement by concept.

## What 5.9 adds

- **Feature overview by area** (rendering, animation, world building, gameplay, editor, core), with the console variables and property names found in the source: [`features-5.9.md`](features-5.9.md). Read it when choosing how to build something, so that a 5.9 feature is on the table: progressive navmesh builds, Lumen World Cache, order-independent translucency, Mass Characters, the Modular Test Framework, script editing of Blueprints, StateTrees, Chooser tables, PCG and Dataflow graphs.
- **All 66 plugins added since 5.8**, with status and description: [`plugins-added-in-5.9.md`](plugins-added-in-5.9.md). Read it before enabling a plugin or when a task might be covered by one of the 25 new AI toolset plugins under `Engine/Plugins/Experimental/Toolsets`.

## Provenance and upkeep

Two sources, marked in the reference files: **[disk]** is read from the installed 5.9 engine and can be trusted for this build; **[notes]** comes from Epic's release notes: the 5.9 Preview page (last updated 2026-11-09) is a short overview with no API list, known issues or upgrade notes; the 5.8 page is long-form, and it was read in full. A [notes] item names a feature without proving how it is spelled in code. Confirm a [notes] item on disk before relying on it.

Re-check this skill when the engine's `Build.version` changes (a 5.9 patch, or 5.9 leaving Preview), and when you move to a newer engine: re-run the diffs against the previous install and update the reference files. Last checked: 2026-11-12.
