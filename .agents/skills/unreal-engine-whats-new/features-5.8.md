# New features and changes in UE 5.8

From Epic's "Unreal Engine 5.8 Release Notes" (<https://dev.epicgames.com/documentation/unreal-engine/unreal-engine-5-8-release-notes?application_version=5.8>), read on 2026-11-12. The page is long-form (about 740,000 characters of text) and has no known-issues section. Read in full: the feature overview, the whole "Upgrade Notes" section, every "Deprecated" list, and the "New" lists for AI, Blueprint, Gameplay, Mass, Networking, UI and Niagara. Every other area, bug-fix lists included, is condensed in [`release-notes-5.8-by-area.md`](release-notes-5.8-by-area.md). Status labels are the page's own; an item without one had none. Names marked **[disk]** were also found in the installed 5.9 source; the rest are as the notes spell them, so confirm them in the engine before use. Deprecated functions are in [`deprecations-5.8.md`](deprecations-5.8.md).

## Changed defaults and breaking changes

- **Windows audio backend is WASAPI**, replacing XAudio2. [disk] `AudioMixerModuleName=AudioMixerWasapi` in `BaseWindowsEngine.ini`. To revert, in `Config/Windows/WindowsEngine.ini`: `[Audio] AudioMixerModuleName=AudioMixerXAudio2`.
- **Zen Server is the default cooked output store.** A project that had the Zen store disabled must enable it by hand. `AllowRemoteNetworkService` became `RemoteNetworkService` [disk], taking `None`, `Unsecured` or `GeneratedStaticKey` (default) instead of true/false.
- **`FJsonObject` keys changed type.** Define `UE_JSONOBJECT_LEGACY_STRING_KEYS=1` [disk] to restore the old string keys.
- **`FCoreDelegates::OnPostEngineInit` is deprecated** for `FCoreDelegates::GetOnPostEngineInit()` [disk].
- **`AActor::EditorKeyPressed` was removed** [disk: absent from `Actor.h`].
- **`FField` virtuals `Bind()`, `PostLoad()`, `BeginDestroy()`** were deprecated and removed.
- **Preview platform renames** on the editor Blueprint library [disk]: `ToggleFeatureLevelPreview` → `TogglePreviewPlatform`, `IsFeatureLevelPreviewEnabled` → `IsPreviewPlatformEnabled`, `IsFeatureLevelPreviewActive` → `IsPreviewPlatformActive`; `SetPreviewPlatform` gained `bCompileShaders`.
- **Sequencer audio:** `bLooping` on `UMovieSceneAudioSection` became `bRepeating` [disk], migrated on load; audio sections no longer auto-expand to keyframes. CVars `Sequencer.Audio.UseRepeating` (on), `Sequencer.Audio.UsePlayUntilFinished` (off).
- **Subtitles:** `QueueSubtitle` is deprecated for `QueueSingleSubtitle` [disk] or `QueueSubtitlesFromAsset`.
- **Navigation:** navmesh version is 28 (old data upgrades on load). A pawn without `PreferredNavData` now uses only NavData whose `CanFly` matches. `bWaitForAsyncLoadingBeforeBuildingNavigationAutomatically` is on by default. UE 5.5-era deprecated navigation code was removed.
- **Editor utilities:** `UAssetActionUtility` and `UActorActionUtility` actions must set `SupportedClasses`, or data validation reports an error.
- **Config:** `BasePluginName.ini` is deprecated; `PluginOverride.ini` is new. Game feature plugin section `[ConsoleVariables_HighPriority]` became `[PluginCVars_HighPriority]` and `[PluginCVars_LowPriority]`. `FastGeoStreaming.ini` became `DefaultFastGeoStreaming.ini`.
- **Mobile renderer:** multi-pass deferred is the default on mobile; forward is opt-in.
- **Animation clean-up:** removed `USkeleton::GetSkeletonRemapping`, `GetAssetRegistryTags`, `CollectAnimationNotifies`, `GetRawAnimationTrackIndex`, and animation, LiveLink, ML Deformer and Pose Search API deprecated up to 5.6. `UAnimInstance::GetCurrentStateName` and `GetCurveValueWithDefault()` are now const. Renamed `INodeObjectInterface` → `INotifyNodeObjectInterface` [disk] and `ETimingElementType` → `ENotifyTimingElementType`.
- **Motion Warping:** `EMotionWarpRotationType::OppositeFacing` and `OppositeDefault` are deprecated (converted automatically; use a 180-degree `AdditionalRotationOffset`). The experimental `UMotionMatchingInteraction` node was removed.
- **Control Rig:** direct Blueprint access to `FRigControlElement::Settings` is deprecated for `GetControlSettings(Key)` [disk]; `BonesToUse` became `BoneMask`; the Control Rig Physics plugin is enabled by default.
- **MetaSounds:** `FNodeClassMetadata::DefaultInterface` takes `FClassInterface` instead of `FVertexInterface`; deprecated node creation helpers were removed from `IDataTypeRegistry`; `FSoundWaveProxy` is deprecated (a broker for `FSoundWaveData`). `SubmixEffectReverb` default gain is 1.0 for new assets (was 0.0).
- **Build:** `UhtSpecifierValueType.Legacy` is obsolete (use `None`). `TextureFormatOodle` is a built-in engine module; NVTT and ISPC fallback codecs are deprecated.
- **XR:** stereo layer draw order is priority-based; `xr.OpenXRProjectionLayerPriority`, `xr.OpenXRSortFaceLockedLayersAboveOtherLayers`.
- **Character movement bases are no longer `UPrimitiveComponent`s.** `ACharacter`, `UCharacterMovementComponent`, `FBasedMovementInfo`, `FCharacterNetworkMoveData`, `FClientAdjustment` and `MovementBaseUtility` now use `FMovementBaseInterfaceData` [disk], which wraps a `UObject` owner and an `IPhysicsBodyOwnerInterface`. Code that extends the character movement component or reads `FBasedMovementInfo` needs fixing up; `UCharacterMovementComponent::RevertMove` and `ACharacter::OnRep_ReplicatedBasedMovement()` are the notes' worked examples, with `MovementBaseUtility::GetMovementBaseDataFromPhysicsOwner`.
- **Input devices:** `FInputDeviceScope` is deprecated and a no-op unless the target defines `UE_USE_LEGACY_INPUT_DEVICE_SCOPE=1`; use the thread-safe `FInputDeviceRegistry` [disk], filled when a device connects.
- **Enhanced Input:** the combo trigger is deprecated ("unreliable and can cause mapping contexts to be corrupted in the editor"). Behaviour fixes sit behind CVars that default on: `EnhancedInput.IgnoreHeldKeysOnFlush`, `EnhancedInput.CorrectTouchBoolActionKeys`, `input.bShouldUpdatedDeviceSubsystemOnConnection`.
- **Raw Input plugin is deprecated** for the "Game Input for Windows" plugin. To ship its redistributable, set `IncludeRedistFiles=True` for Game Input in `DefaultEngine.ini`.
- **Logging:** `UE_LOGF` [disk] and its siblings replace `UE_LOG`, which "will eventually be deprecated"; the release ships `ConvertUELog.py`.
- **Tick functions:** `GetLastTickGameTime` [disk] is deprecated.
- **Blueprint:** a function-local variable must not share a name with a member variable; one can inherit the other's parent-class default. Rename one by hand in existing Blueprints.
- **GAS:** the `FActiveGameplayEffectHandle(int32)` constructor is deprecated for `FActiveGameplayEffectHandle::GetInstantExecutedHandle` [disk]; the handle now references its owning ability system component instead of a global map.
- **StateTree:** `STATETREE_POD_INSTANCEDATA` was removed for `UE_STATETREE_CONSTRUCTED_TRIVIALLY_COPIED_NO_DESTRUCTOR_INSTANCEDATA` or `UE_STATETREE_ZEROED_TRIVIALLY_COPIED_NO_DESTRUCTOR_INSTANCEDATA`; `UE::StateTree::EComparisonOperator` [disk] replaces `EGenericAICheck`; `FindFrame`, `FStateTreePropertyRef::GetMutablePtr` and `StateTreePropertyRefExternalHandle` are deprecated; bindings on an overridden linked state may stop working.
- **Mass:** `FMassEntityManager::AddElementToEntities` and `RemoveElementFromEntities` were renamed `BatchAddElementToEntities` [disk] and `BatchRemoveElementFromEntities`; `GetOrSpawnActorFromTemplate` became `GetOrRequestSpawnActorFromTemplate`; `FMassCommandAddFragmentsInternal` and `FMassCommandAddTagsInternal` are deprecated for `FMassCommandAddElements`.
- **Mover:** PhysicsMover and NetworkPhysicsLiaison code was removed from the Mover plugin (use the ChaosMover plugin); `FloorQueryUtil` functions take `FFloorCheckSettings` [disk].
- **Slate:** `EWindowType::GameWindow` is deprecated (use `EWindowType::Normal`); "OnlyGameWindow" CVars became "OnlyProjectContent" and `bDebugGameWindowOnly` became `bDebugProjectContentOnly`. A module depending on `SlateRHIRenderer` may also need `SlateBaseRenderer` in its `Build.cs`.
- **Core:** `FSharedEventRef` now honours `EEventMode::ManualReset` (it was always auto-reset): check call sites. An implicit cast to bool in string conversion is now a compile error: add a `LexToString` for the type. `REN_ForceNoResetLoaders` is deprecated because `UObject::Rename` no longer resets loaders. `#if UE_PLATFORM_*` is the new form of `#if PLATFORM_*` (optional migration).
- **Animation removals** beyond those above: the Smart Name API (`FSmartName` and its container are deprecated, most helpers removed), `PropertyAccessCompilerHandler` (replaced by `UAnimBlueprintExtension_PropertyAccess`), `GetCharacterOwner` on `UMotionWarpingComponent` and `URootMotionModifier` (use `GetOwnerAdapter()`), and Blueprint access to `FindBone`, `FindControl`, `FindNull` on `URigHierarchy` (use `Contains(Key)`, `GetBoneType(Key)`, `IsSelected(Key)`, `GetIndex(Key)`).
- **Audio:** `au.EnableRelativeRenderCostVoiceLimit` is on by default, so voice counts weigh render cost and fewer sounds may play; attenuation submix sends that `bEnableSubmixSends` had silently disabled may now be audible; `UFadeFunction`, `FFadeFunctionData` and `EWaveEditorFadeMode` are deprecated for `UTransformationFadeFunction` and `UWaveformTransformationFade`.
- **Rendering:** SSGI is deprecated (superseded by Lumen GI); Lumen applies height fog to reflection hits by default (`r.Lumen.HeightFog 1`); `r.Water.SingleLayer.ForceVelocity` is deprecated; the path tracer culls backfaces unless the material is two-sided; a custom `FViewportClient` holding a `TSharedPtr` to its `FViewport` should hold a weak pointer.
- **Cloth:** `USkeletalMeshComponent::FindClothCollisions` and related extraction is deprecated; use `AddClothCollisionSource`.
- **Python:** a `ufunction` returning a tuple now packs values in declared order (it was reversed).
- **Networking:** thread-safety primitives were added for parallel Iris; `UE_SUPPORT_PARALLEL_IRIS=0` (or `ExcludeParallelIrisSupport` in the target rules) compiles them out. `ESubObjectInsertionOrder::ReplicateWith` is deprecated.
- **Mutable:** removed Parameter Profiles, the Node Copy Mesh Section, Low Priority Textures, the CO States tab and the LOD limiter CVars; `ComponentIndex` is deprecated for `ComponentName`.

## Gameplay framework and AI

- **Iris** replication: "production-ready for licensees".
- **Mover** (still Experimental; [disk] `Engine/Plugins/Experimental/Mover`): core movement, NavWalking for Detour Crowd, networking with optional Iris, ChaosMover trajectory prediction.
- **Unified input:** Enhanced Input and Common Input/UI unified, with an Input Debugger; `OnInputDeviceHardwareInfoAvailable` delegate.
- **StateTree:** tree-defined starting states, a gameplay-tag start-state override, a Compiler Manager with out-of-date tracking, reversible property bindings, queued compilation (off by default) under `StateTree.Compiler.*` [disk].
- **Mass:** Mass Signals in core, off-thread entity creation, sparse and virtual fragments, a new `MassCore` module; `FAgentHeightFragment` and `OffsetCornersFromBoundaries` on `FMassNavMeshPathFollowTask`.
- **Navigation:** per-mesh walkable-surface control through `UNavCollision::bUseSurfaceArea` [disk] and `AreaClass`; `ARecastNavMesh::bMinimizeLinkPoolSize` [disk], `AverageLayersPerTile`, `bDrawOnScreenInformation`.
- **EQS:** `bStripFromClientBuilds` on `UEnvQuery` [disk].
- **Level Streaming Persistence** (Experimental), in Project Settings; not found on disk under that name in 5.9. Dynamic Loading Range Scaling in World Settings.
- **Core types:** `TInstancedStruct` gained `*` and `->`; `TSubScriptStructOf` [disk]; `FInstancedPropertyBag` serialises defaults; compact sets through UBT's `bUseCompactSetAsDefault` [disk].
- **Pose Search and motion matching:** the `BP_Get...` channel functions are deprecated for `...FromContext` variants taking `FChooserEvaluationContext`; `UPoseSearchInteractionLibrary::MotionMatchMulti` (Experimental); `URootMotionModifier_Blueprintable`; `FindWarpTarget` is BlueprintCallable.
- **StateTree, further:** transition targets Parent, NextParent and NextSelectableParent; a transition can be marked for reselection; a condition comparing one Gameplay Tag with another; drag and drop of nodes between states; `FStateTreeExecutionContext::GetCurrentlyProcessedStateSelection`; an experimental State Centric View (`StateTree.Editor.Experimental.EnableStateCentricView`).
- **GAS:** `EGameplayEffectGrantedEffectRemovalPolicy` [disk] (`GrantedEffectControlsOwnLifetime`, `RemoveGrantedEffectOnEnd`) on effects granted by `AdditionalEffectsGameplayEffectComponent`; ability triggers can be added at run time.
- **Mover, further:** kinematic simulation separated from `UMoverComponent`; `USimpleFlyingMode` [disk] for Blueprint flying modes; a Blueprint floor query; perching radius threshold; RVO interface on `NavMoverComponent` for Detour Crowd; a `MovementInterface` shared by movement systems.
- **Mass, further:** Sparse Elements (tags and fragments added to an entity without changing its archetype); `FMassCommandAddElements` and `FMassCommandRemoveElement`; observers for shared fragments; traits valid per target configuration (Standalone, Client, Server); `UMassRepresentationActorManagement::IsActorReadyForRepresentation`; experimental spring movement and trajectory traits in MassGameplay (module `MassCharacterTrajectory`).
- **Gameplay Cameras:** first-person view support, an "aim-at" camera action with screen-space framing, a camera action service, an easing blend node, and components that run either their own camera system ("standalone", the default) or only an evaluation context. A procedural camera needs the dedicated activation functions such as "Activate Gameplay Camera" for blending.
- **Level Streaming Persistence plugin:** `SerializeTo` and `InitializeFrom` on its manager are Blueprint-callable, for save games; destroyed map-placed actors can be re-destroyed on reload and chosen actor classes respawned.
- **Input:** a "preferred input API" project setting (`bEnablePreferredInputAPIPreferences`); Game Input can filter devices by VID/PID.
- **Conversation** task nodes can pick branches in order instead of at random.
- **Debugging:** Rewind Debugger project settings (`URewindDebuggerProjectSettings`); Visual Logger split into `UE_DEBUG_RECORDING_ENABLED`, `UE_DEBUG_RENDERING_ENABLED`, `UE_DEBUG_VISUALIZER_TOOL_ENABLED` (`ENABLE_VISUAL_LOG` still enables all).

## Blueprint and UI

- **Blueprint editor scripting was greatly expanded:** `unreal.BlueprintGraphEditor` for graphs and new functions on `unreal.BlueprintEditorLibrary` [disk: module `BlueprintEditorLibrary`]; run `help()` on either.
- **Blueprint:** enable/disable node options left experimental; `FPerPlatformBool` is exposed; `bp.MaxAsyncActionCount` ensures on too many async actions; a `UserDefinedStruct` can be generated from a property bag.
- **Common UI is production ready** (out of Beta). UI actions can be registered from Blueprint through new functions on `UCommonUserWidget` [disk]; `FCommonInputTypeInfo::AdditionalKeys`; `OnSelectedButtonLostSelection` on `UCommonButtonGroupBase`; `UCommonUILibrary::RefreshFocusIfLeafmostDescendant`; `CommonUI.TextGlobalScaling`.
- **MVVM:** a Context resolver type that pulls view models from a parent widget's binding; implicit converters; a one-way binding to a source without FieldNotify is now a notice, not a compile error; `OnItemsChanged` on the panel view extension.
- **UMG and Slate:** proximate-entry navigation on list and tile views (`bEnableProximateEntryNavigation` [disk], `UListView::SetEnableProximateEntryNavigation`); `UTextBlock::SetFontSize` / `GetFontSize` in the project's font DPI; `AnyTextSelected` on editable text; default frame rate for widget animations in project settings; `Slate.EnableTooltipForceFieldDraw`.

## Networking

- **Iris:** `UNetObjectPrioritizer` is subclassable; delta serialisation for `FInstancedStructNetSerializer`; `PreferredReplicationSystem` on `FIrisNetDriverConfig` overrides `net.Iris.UseIrisReplication` per net driver; parallel `NetConnection::Tick` behind `net.iris.AllowParallelNetTick`; debug objects written outside the bandwidth limit.
- Network Prediction plugin supports Iris. Experimental `NetworkServiceDiscovery` plugin (mDNS/Bonjour). Default socket receive buffers raised to 262144 bytes. `net.NumericIPSyncResolve`, `HTTP.Curl.MaxHostConnections`.

## Rendering

- **Niagara:** a Spawn By Trigger module, Random Jitter and Ramp In/Out dynamic inputs, GPU bitonic sort for small particle counts, `r.HeterogeneousVolumes.Allow` driven by scalability.
- **MegaLights** is Production Ready: transmission, translucency lighting, IES for volumetrics, lighting channels, cloud shadows, first-person weapons, new debug views. [disk] `r.MegaLights.*`.
- **Lumen Lite** (Beta): medium-quality Irradiance Fields GI, about twice as fast as high-quality Lumen; default on current handhelds, supported on PC. [disk] `r.Lumen.IrradianceFieldGather.*`.
- **Fog Screen Space Scattering** (Experimental), on the Exponential Height Fog component; no Volumetric Clouds or Heterogeneous Volumes.
- **Substrate Toon Shading** (Experimental): Substrate Toon BSDF and a Toon Profile asset, on the Blendable GBuffer mode. **AxF materials** import through Substrate.

## Audio

- **Audio Insights** is Production Ready. **Audio Subtitles** and the **Waveform Editor** are Beta (`UWaveformTransformationFade`).
- **MetaSounds** (Experimental): node configuration, templates, and Channel Agnostic Types with nodes Wave Player 2.0, CAT Mixer and Grain Player.
- **Sequencer:** Control Bus and Control Bus Mix tracks.

## Animation and characters

- **Control Rig Physics** (Beta) and **Control Rig Dynamics** (Experimental; [disk] plugin `ControlRigDynamics`), a particle solver for cosmetic motion. **PhysicsControl** is ready for production.
- **Sequencer:** Animation Mixer (Experimental, supports UAF), Simple View, AutoBaking, linked filters across Viewport, Sequencer and Curve Editor.
- **Retargeting:** foot definition, retarget override sets, RigMapper as an op stack (Beta); biped templates changed so leg chains end at the foot and new LeftFoot/RightFoot chains cover ball and toe.
- **Skeletal Editor:** morph target tools, lattice deformer, Bone Count Reduction; `USkeletalMesh::Clear()`.
- **Mutable** and **Chaos Cloth** reach production readiness. **MetaHuman Crowd** (Experimental) builds MetaHumans for Mass crowds.

## World building and PCG

- **Mesh Terrain** (Experimental; [disk] plugin `MeshTerrainMode`): mesh-based terrain for large worlds.
- **Fast Geometry Streaming** (Experimental) adds decals and point, spot and rect lights. **World Partition Insights.** HLOD: Build HLOD for Selection and for Selected Region.
- **PCG:** manual editing with a Data Overrides window; arrays, structs, sets and maps as attributes; nodes including Align Points, Apply Spline to Component, Teleport Actors and Components, Set Materials On Dynamic Mesh. **Procedural Vegetation Editor** (Experimental).

## Editor, scripting and pipeline

- **MCP Server** (Experimental): Unreal MCP first shipped in 5.8. **Semantic Search** plugin (Experimental). **Sandboxes:** isolated workspaces with export and import.
- **Editor Gizmo System** on the Interactive Tools Framework, with Default, Classic and Maya-style presets. Details Panel favourites, a reworked Shortcut Manager and Editor Preferences.
- **Scripting:** `bOverwriteExisting` on CreateAsset; optional properties in Python; `DataTable` export to string and file; `BatchProcessCommandlet` and `BatchProcessLibrary::RunBatch`; `UAssetReferencingPolicySubsystem::ValidateAssetReferences`.
- **Cooking:** Incremental Cooking (Beta); `-CompileOnly` for UAT; `-SkipEncryption` for IoStore; packaging settings `bDeduplicateChunks` and `bUsePatchInPlaceLayout`.
- **Interchange:** reworked import dialog; uFBX importer (Experimental); USD through Interchange is production ready for assets and experimental for levels.
- **Movie Render Graph** is Production Ready; new render features are graph-only.
- **Chaos:** destruction dataflow template, Visual Debugger additions, per-component caching in Sequencer, modular vehicles on skeletal meshes.

## Toolchain (5.8 notes)

Recommended Visual Studio 2026, minimum VS 2022 17.14; MSVC 14.50 recommended, 14.38 minimum; Windows SDK 10.0.26100.0; clang 20.1.8 preferred; .NET 10.0. The 5.9 values read from disk are in [`features-5.9.md`](features-5.9.md).

Mobile, XR, virtual production, media, Horde and the other areas not covered above are in [`release-notes-5.8-by-area.md`](release-notes-5.8-by-area.md).
