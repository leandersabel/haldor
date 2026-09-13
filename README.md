# Haldor

A Valheim mod loader for macOS. Installs a Thunderstore modpack and launches the
game with BepInEx attached.

Thunderstore Mod Manager and r2modman have no macOS build. Haldor resolves a pack
from the Thunderstore API, lays it down next to `valheim.app`, and starts the game
through Doorstop.

## Usage

    ./haldor.py install MahMods/Trollheim
    ./haldor.py update
    ./haldor.py play

`install` pins every version the pack names. Where a mod asks for an older version
of something the pack already pins, the pack wins, so the install matches what the
other players run.

## Why it is built this way

The Steam macOS build of Valheim is signed with `allow-dyld-environment-variables`,
`disable-library-validation` and `allow-jit`. Doorstop injects through
`DYLD_INSERT_LIBRARIES` without disabling SIP or re-signing the app.

**The game runs natively on Apple Silicon**, with no translation layer. That needs a
BepInEx core rebuilt against MonoMod 25, because the MonoMod that BepInEx bundles
patches code in a way Apple Silicon refuses. See `ARM64.md`.

BepInEx comes from the official macOS build rather than the Windows `BepInExPack_Valheim`,
whose bundled `libdoorstop_x64.dylib` is Intel-only. Its core is then replaced with the
arm64 one in `bepinex-arm64/core`.

Mod plugins are managed .NET and carry no native code. Their embedded Unity asset
bundles declare build target 5, the canonical desktop-standalone value, which the
macOS player accepts.

## Known issues

Mod-supplied shaders have no Metal variants, logged as `Desired shader compiler
platform 14 is not available in shader blob`. Custom content added by mods can render
untextured. Vanilla assets are unaffected.

## Diagnosing a failed preload

BepInEx writes preload exceptions to `preloader_<timestamp>.log` beside the
executable, which on macOS is inside the bundle at `valheim.app/Contents/MacOS/`.
Nothing appears in `BepInEx/LogOutput.log` when preloading fails, because the logger
is not up yet.
