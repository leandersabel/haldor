# Native arm64

Haldor runs Valheim on the Apple Silicon slice. That needs one change to BepInEx.

## Why stock BepInEx cannot do it

Apple Silicon enforces W^X: a page cannot be writable and executable at once. MonoMod
22, which BepInEx bundles, patches code by calling `mprotect` for RWX. On arm64 macOS
that returns `EACCES`, `DetourHelper.Runtime` fails to construct, and every Harmony
patch throws `IL Compile Error`. Measured in-process:

    PlatformHelper.Current  = Bits64, MacOS, ARM            correct
    DetourHelper.Native     = DetourNativeMonoPosixPlatform correct
    DetourHelper.Runtime   -> Exception: mprotect returned EACCES

Architecture detection and ARM instruction encoding were never the problem. Only the
memory permission call was.

## The fix

BepInEx 5.4.23.5 rebuilt against MonoMod 25 and HarmonyX 2.16. MonoMod 25 toggles
`pthread_jit_write_protect_np` instead of asking for RWX, which the game's existing
`allow-jit` entitlement permits. Nothing is re-signed and no entitlement is added.

The result is in `bepinex-arm64/core`. `bepinex-arm64/build.sh` reproduces it from
`bepinex-arm64/*.patch` against upstream `v5.4.23.5`, needing only a .NET SDK.
Doorstop, the launcher script and every mod are upstream and unmodified.

Most of the core comes verbatim from the pinned packages. The assemblies built from
source differ from the shipped copies only in PE timestamp, MVID and debug directory.

The patch:

- `PlatformCompat.cs` reimplements `PlatformHelper` and `Platform` on MonoMod 25's
  `PlatformDetection`, so existing call sites are untouched.
- `UnixStreamHelper` uses `DllImport` instead of the removed `DynDllImport`.
- `PlatformUtils.SetPlatform` is deleted; MonoMod 25 detects the platform itself.
- `XTermFix` is deleted; it existed to work around MonoMod 22's platform detection.
- `HarmonyX2Interop` is dropped from the build. It produces `0Harmony20.dll` for mods
  built against Harmony 2.0, and nothing in the pack references it.
- Target framework moves from net35 to net472, which is what Unity's Mono is.

`System.ValueTuple.dll` ships alongside because MonoMod 25 references it and the game
provides no such assembly. It is the `net461` build, which defines the types. A restore
at net472 resolves the `net47` build instead, which holds nothing but forwarders to
mscorlib, and Unity's mscorlib has no `ValueTuple` to forward to. The `netstandard1.0`
build defines the types too, but references `System.Collections`, which Mono does not
have. `build.sh` puts the `net461` build in place after the copy.

## Repatching while the game runs

MonoMod repatches a method only once no thread is inside it, and it finds those threads
by walking the stack for its own dynamic methods. Under Unity's Mono those frames are
`DynamicMethod`s the walk does not resolve, so the count comes back zero and a mod that
repatches from inside a patched method waits for itself. Every thread parks, the log
ends mid-sentence, and the game shows a black screen with no error.

Valheim Plus does exactly that: it calls `Harmony.UnpatchSelf` from the handler for the
server's config, which is itself running through a detour.

    DetourSyncInfo.WaitForNoActiveCalls        <- waiting for itself
    ILHook.Apply / PatchProcessor.Unpatch
    Harmony.UnpatchSelf
    ServerSync.ConfigSync.HandleConfigSyncRPC
    ZRpc.HandlePackage  ->  ZNet.Update

`run_bepinex.sh` exports `MONOMOD_DMDType="cecil"`, which emits dynamic methods as real
methods in generated assemblies. The stack walk sees those, the count is right, and the
repatch goes through. It costs nothing measurable at startup.

Apple Silicon is not what causes this. The same core deadlocks the same way under
Rosetta, and stock BepInEx on MonoMod 22 waits for nobody, which is why it never shows.

## What it buys

Time from launch, on this machine:

    vanilla, to main menu        arm64  5.7s, 6.7s     x86_64  11.3s, 10.2s
    modded, all plugins loaded   arm64  6.2s, 6.1s     x86_64  14.3s
