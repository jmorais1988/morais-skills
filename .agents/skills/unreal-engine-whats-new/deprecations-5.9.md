# Deprecated in UE 5.9

`UE_DEPRECATED(5.9, ...)` markers in the modules a game project is likely to call, read from the 5.9 headers (CL 60351404) on 2026-11-12. The engine has 376 such markers in all; ControlRig (135), the modeling toolset (42) and Interchange (19) hold most of the rest and are left to a search. Messages are the engine's own, shortened.

## Core and CoreUObject

| Deprecated | Use instead |
|---|---|
| `TIsArray`, `TIsBoundedArray`, `TIsUnboundedArray` | Concepts `UE::CArray`, `UE::CBoundedArray`, `UE::CUnboundedArray` |
| `TLazyObjectPtr` ("to be removed in 6.0") | `TSoftObjectPtr` |
| `GIsCookerLoadingPackage` | `UE::GetIsCookerLoadingPackage()` |
| Two format accessors in `StructuredLog.h` (names not captured: read the header) | `GetFormat()` / `SetFormat()` |
| `ExtractAutomationTestFlags` | `ParseFlags` |
| `OnPackageLoadCompleted` in `UObjectGlobals.h`, marked unsafe: it can broadcast a `UPackage` whose outer objects are still being mutated or already freed | `FCoreUObjectDelegates::OnEndLoadPackage` |

## Engine

| Deprecated | Use instead |
|---|---|
| `UGameplayStatics::SpawnEmitterAtLocation`, `SpawnEmitterAttached`, `SetEmitterCallbacksInternal` | `UCascadeFunctionLibrary` in module `CascadeRuntime` |
| `UAssetManager::ScanPathsForPrimaryAssets(FPrimaryAssetType, Paths, UClass* BaseClass, ...)` | The overload taking `const FPrimaryAssetTypeInfo*` |
| `UAssetManager::ScanPathForPrimaryAssets` (singular) | `ScanPathsForPrimaryAssets` with `{ Path }` and `InputInfo` |
| `UDeviceProfileManager::GatherDeviceProfileCVars(const FString&, EDeviceProfileMode)` | `GatherDeviceProfileCVars(const FGatherCVarsContext&)` |
| `FAudioDevice::GetAzimuth` | `GetListenerRelativeAngles`. The old outputs were misnamed: the first is the angle from the listener's forward axis (0 to 180), the second the azimuth (0 to 360) |
| `bIsNonRealtime` in `AudioDeviceManager.h` | `RenderMode` |
| `FVisualLogger::CheckVisualLogInputInternal` | `GetEntryToWrite`, which includes the filter check |
| `FSceneView::IsInstancedStereoPass()` | `IsInstancedStereo()` |
| `FeatureLevel` overloads in `BatchedElements.h`, `DistanceFieldAtlas.h`, `MeshPaintRendering.h` | The `EShaderPlatform` overloads |
| Directional light cascade setup on `FLightSceneProxy` (seven functions) | Moved into the Renderer module (`Renderer/Private/ShadowRendering.h`), which is private: game code has no replacement |
| `FLocalLightSceneProxy::UpdateRadius_GameThread` | `ULightComponent::UpdateProxy(...)` |
| `GameThread_UpdateContents` without a scene, and `GetUniformBuffer()` (now returns null), in `ParameterCollection.h` | The `GameThread_UpdateContents` overload that takes an `FSceneInterface`; the scene owns the uniform buffers |
| `FMaterialAttributeDefintion`, `FMaterialCustomOutputAttributeDefintion` (misspelt) | `FMaterialAttributeDefinition`, `FMaterialCustomOutputAttributeDefinition` |
| `GetAllDefaultTextureFormats` | No replacement named |
| `PhysicsAssetForDebug` and the collision debug hook on the skeletal mesh scene proxy | Automatic: `UE::MeshComponentDebugRender::DrawSkinnedMeshCollision` |

Removed from the Engine module outright (headers gone, no forwarding header): everything under `Classes/Particles/` except `FXBudget.h`, `ParticlePerfStats.h` and `ParticlePerfStatsManager.h`; the three particle anim notifies; `ParticleHelper.h`, `ParticleEmitterInstances.h`, `ParticleSystemSceneProxy.h` (all now in module `CascadeRuntime`); the particle vertex factories (now in module `CascadeVertexFactories`); and `Materials/MaterialIR*.h` (now `Materials/MIR/MIR*.h`).

## Gameplay plugins and runtime modules

| Module | Deprecated | Use instead |
|---|---|---|
| EnhancedInput | `bShouldBeIgnored` on `FEnhancedActionKeyMapping` | `UEnhancedPlayerInput::IsKeyIgnored` / `AddIgnoredKey` / `RemoveIgnoredKey` |
| GameplayAbilities | `HasReceivedEffectWithPredictedKey` | `HasReceivedEffectOfClassWithPredictedKey`, which names the exact effect class |
| StateTree | `UStateTreeEditingSubsystem::K2_CompileStateTree` | `CompileStateTreeWithResult` |
| StateTree | `MarkDelegateAsBroadcasted` on the execution context | `FStateTreeMinimalExecutionContext` |
| ModelViewViewModel | `FParentSourceInfo`, the "parent" source accessors, enum field `ParentContextReference` | `GetContextSourceInfo`, `IsContextReference`, `ContextReference` |
| MassEntity | Template-argument forms of `CheckElementAddBreakpoints` / `CheckElementRemoveBreakpoints` / `CheckCreateEntityBreakpoints` ("removed in 6.0") | Pass `UScriptStruct*` (or `TArray<const UScriptStruct*>`) directly |
| NavigationSystem | `ARecastNavMesh::FindPolysAroundCircle` | `FindPolysAroundCircleReal` |
| PCG | `GetSegmentStartIndexAndKeyAtInputKey` in `PCGSplineStruct.h` | `GetSegmentInfoAtInputKey` |
| PCG | `UPCGGraph::NotifyGraphStructureChanged` | `NotifyGraphChanged`; the `bForce` argument is obsolete |
| MovieScene | `FMovieSceneMarkedFrame::FrameNumber` | `GetStartFrame()` / `GetEndFrame()`, `SetRange()` / `SetRangeStartAndEnd()` |
| MovieScene | `SetMarkedFrame` with one frame | `SetMarkedFrame` with a `StartFrame` and an `EndFrame` |
| MovieScene | `GetDecorations()` | `GetDecorationObjects` (returns a copy) |
| MovieScene | `PreFlush` event on `UMovieSceneEntitySystemLinker` | An update's flushed callback: `FMovieSceneEntitySystemRunner::QueueUpdate` |
| ReplicationGraph | `bEnableDebugging` | Unused; remove |
| UMGEditor | `FWidgetBlueprintOperationUtils` | `UWidgetBlueprintEditorSubsystem` |
| UMGEditor | `UIComponentUtils` functions (older overloads) | The `FWidgetBlueprintEditor*` overloads |
| Slate | `SDockingTabStack::ReserveSpaceForWindowChrome` | The static `ReserveSpaceForWindowChromes` |
