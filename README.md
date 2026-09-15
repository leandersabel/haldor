# Haldor

A Valheim mod loader for macOS, because Thunderstore Mod Manager and r2modman have no
macOS build. Haldor resolves a Thunderstore modpack, lays it down next to `valheim.app`,
and starts the game through Doorstop.

## Usage

    ./haldor.py install MahMods/Trollheim
    ./haldor.py add DrummerCraig/ShaderHelperForMac
    ./haldor.py update
    ./haldor.py play
    ./gui.py

`install` pins every version the pack names. Where a mod asks for an older version of
something the pack already pins, the pack wins, so the install matches what the other
players run.

`add` records a package under `extras` in `BepInEx/haldor.json` and installs it beside
the pack, which `update` preserves. Deleting the entry and running `update` drops the
mod. `install` starts from the pack alone.

`gui.py` opens a window on the same state: the modpack, the extras, install and play.
Install applies whatever the window shows, so editing the extras there covers both `add`
and dropping a mod. Beside the modpack stands the pack version the install carries, and
`refresh` asks Thunderstore for the published one, shown as `1.1.0 → 1.2.0` where the
install is behind. The window is a dark terminal pane, set in MesloLGS NF where that is
installed and Menlo otherwise. It needs the Python the `Brewfile` names: `brew bundle`.

`python3 -m unittest` runs the tests, which need no network and no game: the resolver,
the layouts a Thunderstore package arrives in, and the cache. CI runs them before it
builds the app.

## The app

[**Download Haldor.app**](https://github.com/leandersabel/haldor/releases/latest/download/Haldor.zip),
the window carrying its own Python and Tk, so it needs nothing installed. That link
always points at the newest [release](https://github.com/leandersabel/haldor/releases).

Every push builds the app and a tag starting with `v` publishes it, so an untagged build
lives only as an artifact on its [workflow run](https://github.com/leandersabel/haldor/actions),
which GitHub hands out to signed-in visitors. `./make-app.sh` builds the same app here,
from `gui.py`, `icon.svg` and a throwaway virtualenv holding PyInstaller.

macOS quarantines what it downloads, and the signature is ad hoc, so clear the flag
before the first launch:

    xattr -dr com.apple.quarantine Haldor.app

The app is arm64, like the rest of this.

## Why it is built this way

The Steam macOS build of Valheim is signed with `allow-dyld-environment-variables`,
`disable-library-validation` and `allow-jit`. Doorstop injects through
`DYLD_INSERT_LIBRARIES` without disabling SIP or re-signing the app.

**The game runs natively on Apple Silicon.** That needs a BepInEx core rebuilt against
MonoMod 25, because the MonoMod that BepInEx bundles patches code in a way Apple Silicon
refuses. See `ARM64.md`.

BepInEx comes from the official macOS build rather than the Windows
`BepInExPack_Valheim`, whose bundled `libdoorstop_x64.dylib` is Intel-only. Its core is
then replaced with the arm64 one in `bepinex-arm64/core`. The download is checked against
`BEPINEX_SHA256`, since a release asset can be swapped under a tag that does not move.

Mod plugins are managed .NET and carry no native code. Their embedded Unity asset
bundles declare build target 5, the canonical desktop-standalone value, which the macOS
player accepts.

## Known issues

A shader with no Metal variant is logged as `Desired shader compiler platform 14 is not
available in shader blob`. Mod-supplied ones leave custom content untextured. Valheim's
own tree-cut leaf particles ask `Standard` for transparency and get none, so felling a
tree throws its leaves out as opaque black quads.

`DrummerCraig/ShaderHelperForMac` remaps affected materials at runtime and is installed
as an extra. It reaches neither of those on its own: its scan skips the largest mod DLLs,
and it refuses a Valheim material on a Valheim shader unless a rule names the prefab the
material sits under. `shaderfix` holds those rules, laid into
`BepInEx/config/ShaderHelperForMac` on every install.

## Diagnosing a failed preload

BepInEx writes preload exceptions to `preloader_<timestamp>.log` beside the executable,
which on macOS is inside the bundle at `valheim.app/Contents/MacOS/`. Nothing appears in
`BepInEx/LogOutput.log` when preloading fails, because the logger is not up yet. Files
written there also break the bundle's code signature seal.

## How this was made

Written with Claude Code.

## License

MIT, in `LICENSE`. BepInEx, Doorstop and the mods keep their own.
