# Haldor

A Valheim mod loader for macOS. Installs a Thunderstore modpack and launches the
native Apple Silicon game with BepInEx attached.

Thunderstore Mod Manager and r2modman have no macOS build. Haldor resolves a pack
from the Thunderstore API, lays the plugins down next to `valheim.app`, and starts
the game through Doorstop.

## Why this works

The Steam macOS build of Valheim is a universal binary signed with
`allow-dyld-environment-variables`, `disable-library-validation` and `allow-jit`.
Doorstop injects through `DYLD_INSERT_LIBRARIES` without disabling SIP or
re-signing the app.

BepInEx 5.4.23.5 ships a universal `libdoorstop.dylib`, so the arm64 slice runs
directly. The `libdoorstop_x64.dylib` inside `denikson-BepInExPack_Valheim` is
x86_64 only and is replaced during install.

Mod plugins are managed .NET and carry no native code. Their embedded Unity asset
bundles declare build target 5, the canonical desktop-standalone value, which the
macOS player accepts.

## Usage

    haldor install MahMods/Trollheim
    haldor update
    haldor play
