#!/bin/sh
# Rebuild the arm64 core from the patches. Writes into the directory given, or
# into core/ beside this script. Needs a .NET SDK.
set -e

tag=v5.4.23.5
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/core}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git clone -q --branch "$tag" --depth 1 --recurse-submodules \
	https://github.com/BepInEx/BepInEx.git "$work/src"
git -C "$work/src" apply "$here/bepinex-mm25.patch"
git -C "$work/src/submodules/BepInEx.Harmony" apply "$here/bepinex-harmony-mm25.patch"

# The preloader's output directory is the core: its own assembly, the three
# projects it references, and the twelve DLLs the pinned packages bring in.
dotnet build "$work/src/BepInEx.Preloader/BepInEx.Preloader.csproj" -c Release -v m
mkdir -p "$out"
cp "$work/src/BepInEx.Preloader/bin/Release/net472/"*.dll "$out"

# At net472 the restore resolves System.ValueTuple to its net47 build, which
# forwards the types to mscorlib. Unity's mscorlib has nowhere to forward them
# to, so the net461 build, which defines them, replaces it.
nuget=$(dotnet nuget locals global-packages --list | sed 's/^[^:]*: //')
cp "$nuget/system.valuetuple/4.5.0/lib/net461/System.ValueTuple.dll" "$out"
