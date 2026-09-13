# Native arm64

Haldor runs the game on the x86_64 slice under Rosetta. Native arm64 is blocked by
one specific thing, recorded here so the question does not get reopened from scratch.

## The blocker

Apple Silicon enforces W^X: a page cannot be made writable and executable at once.
MonoMod 22, which BepInEx bundles, patches code by calling `mprotect` for RWX. On
arm64 macOS that call returns `EACCES`, so `DetourHelper.Runtime` fails to construct
and every Harmony patch throws `IL Compile Error`.

Measured in-process on arm64:

    PlatformHelper.Current  = Bits64, MacOS, ARM       correct
    DetourHelper.Native     = DetourNativeMonoPosixPlatform   correct
    DetourHelper.Runtime   -> Exception: mprotect returned EACCES

Architecture detection and ARM instruction encoding are both fine. Only the memory
permission call fails.

## What Rosetta costs

Time from exec to main menu, vanilla, no BepInEx:

    arm64    5.7s, 6.7s
    x86_64  11.3s, 10.2s

## Routes to native, and why none is taken

**MonoMod 25.** `MonoMod.Core` 1.3.6 carries `Arm64Arch`, `MacOSSystem` and
`pthread_jit_write_protect_np`, which is the correct W^X handling and works under the
`allow-jit` entitlement the game already has. BepInEx cannot consume it as a drop-in:
MonoMod 25 removed `MonoMod.Utils.Platform` and the `DynDllImport` attributes, both of
which BepInEx calls, so it fails with `TypeLoadException`. BepInEx must be recompiled.
Upstream has not done this: BepInEx master still pins HarmonyX 2.10.2 and
MonoMod.Utils 22.7.31, and BepInEx 5 pins HarmonyX 2.9 and MonoMod 22.1.29. The port
surface is 11 files and about 17 call sites.

**A replacement native platform.** `DetourHelper.Native` is settable, so an
`IDetourNativePlatform` that toggles `pthread_jit_write_protect_np` instead of calling
`mprotect` can be injected without touching BepInEx. Attempted: the game hangs during
detour setup, because the toggle applies to the whole thread and Mono then stalls
executing JIT code from it. Correct scoping is the same problem MonoMod 25 solves.

**Adding `com.apple.security.cs.allow-unsigned-executable-memory`.** Re-signing the app
with this entitlement would let the RWX `mprotect` succeed. It weakens the app's
hardening and is the wrong fix, since `allow-jit` plus the proper API already suffices.
