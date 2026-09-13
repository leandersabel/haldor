# Native arm64

Haldor runs Valheim on the Apple Silicon slice with no translation layer. Getting
there needed one change to BepInEx, recorded here.

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

The result is in `bepinex-arm64/core`, and `bepinex-arm64/*.patch` reproduces it
against upstream `v5.4.23.5`. Doorstop, the launcher script and every mod are
upstream and unmodified.

The patch is 11 files, +103/-347:

- `PlatformCompat.cs` reimplements `PlatformHelper` and `Platform` on MonoMod 25's
  `PlatformDetection`, so existing call sites are untouched.
- `UnixStreamHelper` uses `DllImport` instead of the removed `DynDllImport`.
- `PlatformUtils.SetPlatform` is deleted; MonoMod 25 detects the platform itself.
- `XTermFix` is deleted; it existed to work around MonoMod 22's platform detection.
- `HarmonyX2Interop` is dropped from the build. It produces `0Harmony20.dll` for mods
  built against Harmony 2.0, and nothing in the pack references it.
- Target framework moves from net35 to net472, which is what Unity's Mono is.

`System.ValueTuple.dll` ships alongside because MonoMod 25 references it and the game
provides no such assembly. It is the net461 build, a pure forwarder to mscorlib, where
the type actually lives. The net452 build does not work: it pulls in `System.Collections`,
which Mono does not have.

## What it buys

Time from launch, on this machine:

    vanilla, to main menu        arm64  5.7s, 6.7s     x86_64  11.3s, 10.2s
    modded, all plugins loaded   arm64  6.2s, 6.1s     x86_64  14.3s

## Diagnosing a failed preload

BepInEx writes preload exceptions to `preloader_<timestamp>.log` beside the executable,
which on macOS is inside the bundle at `valheim.app/Contents/MacOS/`. Nothing reaches
`BepInEx/LogOutput.log` when preloading fails, because the logger is not up yet. Files
written there also break the bundle's code signature seal.
