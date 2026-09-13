# Haldor

A Valheim mod loader for macOS. Installs a Thunderstore modpack and launches the
game with BepInEx attached.

Thunderstore Mod Manager and r2modman have no macOS build. Haldor resolves a pack
from the Thunderstore API, lays it down next to `valheim.app`, and starts the game
through Doorstop.

## Usage

    ./haldor.py install MahMods/Trollheim
    ./haldor.py add DrummerCraig/ShaderHelperForMac
    ./haldor.py update
    ./haldor.py play
    ./haldor.py gui
    ./make-app.sh

`install` pins every version the pack names. Where a mod asks for an older version
of something the pack already pins, the pack wins, so the install matches what the
other players run.

`add` records a package in `extras` in `BepInEx/haldor.json` and installs it beside
the pack, where `update` keeps it. The pack is still queued first, so an extra never
moves a version the pack pins. Deleting the entry and running `update` drops the mod.
`install` starts from the pack alone.

`gui` opens a window on the same state: the source, the modpack, the extras beside
it, Install and Play. The source list names `thunderstore.io` and holds nothing else,
because that is the only index Haldor reads. Install applies whatever the window
shows, so editing the extras there and installing covers both `add` and dropping a
mod. Tkinter comes with Python, so the window needs nothing installed.

`make-app.sh` builds `Haldor.app` beside it, which opens the same window from Finder
or the Dock. The bundle is a launcher and an icon, naming this checkout and the
`python3` on your path, so build it again if either moves. The icon is `icon.svg`,
rasterized at build time. macOS asks once for access to the folder the checkout
sits in.

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

`DrummerCraig/ShaderHelperForMac` remaps the affected materials at runtime and is
installed as an extra. It does not reach every mod.

## Diagnosing a failed preload

BepInEx writes preload exceptions to `preloader_<timestamp>.log` beside the
executable, which on macOS is inside the bundle at `valheim.app/Contents/MacOS/`.
Nothing appears in `BepInEx/LogOutput.log` when preloading fails, because the logger
is not up yet.
