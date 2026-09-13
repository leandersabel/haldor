#!/usr/bin/env python3
"""Install a Thunderstore modpack into the macOS build of Valheim and launch it."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

API = "https://thunderstore.io/api/experimental/package"
BEPINEX = ("https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5"
           "/BepInEx_macos_universal_5.4.23.5.zip")
STEAM = Path.home() / "Library/Application Support/Steam"
CACHE = Path.home() / "Library/Caches/haldor"


def game_dir() -> Path:
    """Locate the Valheim install through Steam's library index."""
    vdf = (STEAM / "steamapps/libraryfolders.vdf").read_text()
    for lib in re.findall(r'"path"\s+"([^"]+)"', vdf):
        d = Path(lib) / "steamapps/common/Valheim"
        if (d / "valheim.app").is_dir():
            return d
    sys.exit("Valheim not found in any Steam library")


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "haldor"})
    with urllib.request.urlopen(req) as r:
        return r.read()


def fetch(url: str) -> bytes:
    """Cache a URL whose body cannot change: a pinned version or a download."""
    cached = CACHE / re.sub(r"[^\w.-]", "_", url)
    if not cached.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(get(url))
    return cached.read_bytes()


def latest(pkg: str) -> dict:
    """The newest published version of a namespace/name reference."""
    return json.loads(get(f"{API}/{pkg}/"))["latest"]


def resolve(pack: str, extras: list[str]) -> list[str]:
    """Expand a pack and the extras beside it into a flat list of pinned dependencies."""
    queue = latest(pack)["dependencies"] + [latest(e)["full_name"] for e in extras]
    seen, order = set(), []
    while queue:
        dep = queue.pop(0)
        *parts, version = dep.split("-")
        pkg = "-".join(parts)
        # The pack pins its own versions and is queued first, so an extra or a
        # transitive edge only fills a gap.
        if pkg in seen:
            continue
        seen.add(pkg)
        order.append(dep)
        meta = json.loads(fetch(f"{API}/{'/'.join(parts)}/{version}/"))
        queue += meta.get("dependencies", [])
    return order


def install_mod(dep: str, bep: Path) -> None:
    """Unpack one Thunderstore package, honouring its layout."""
    *parts, version = dep.split("-")
    data = fetch(f"https://thunderstore.io/package/download/{'/'.join(parts)}/{version}/")
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()

    # A package that carries its own BepInEx tree overlays the game root.
    root = next((n[: n.index("BepInEx/")] for n in names if "BepInEx/" in n), None)
    if root is not None:
        dest, strip = bep.parent, root
    elif any(n.startswith(("plugins/", "patchers/", "config/")) for n in names):
        dest, strip = bep, ""
    else:
        dest, strip = bep / "plugins" / "-".join(parts), ""

    for n in names:
        if n.endswith("/") or not n.startswith(strip):
            continue
        target = dest / n[len(strip):]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(n))


def install_loader(game: Path) -> None:
    """Overlay the macOS build of BepInEx, then replace its core with the arm64 one.

    Stock BepInEx bundles MonoMod 22, which patches code by asking for RWX memory.
    Apple Silicon refuses that, so the core here is rebuilt against MonoMod 25,
    which uses the JIT write-protect toggle the game's allow-jit entitlement permits.
    Doorstop and the launcher come from upstream unchanged.
    """
    zf = zipfile.ZipFile(io.BytesIO(fetch(BEPINEX)))
    zf.extractall(game)

    core = game / "BepInEx" / "core"
    shutil.rmtree(core, ignore_errors=True)
    shutil.copytree(Path(__file__).parent / "bepinex-arm64" / "core", core)

    script = game / "run_bepinex.sh"
    text = script.read_text()
    text = re.sub(r'^executable_name=.*', 'executable_name="valheim.app"', text, flags=re.M)
    text = re.sub(r'^(\s*export ARCHPREFERENCE=).*', r'\1"arm64"', text, flags=re.M)
    script.write_text(text)
    script.chmod(0o755)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(game)], capture_output=True)


def install(pack: str, extras: list[str]) -> None:
    game = game_dir()
    bep = game / "BepInEx"
    for d in ("plugins", "patchers", "core"):
        shutil.rmtree(bep / d, ignore_errors=True)
    deps = resolve(pack, extras)
    for dep in deps:
        print(f"  {dep}")
        install_mod(dep, bep)
    install_loader(game)
    (bep / "haldor.json").write_text(
        json.dumps({"pack": pack, "extras": extras, "mods": deps}, indent=2))
    print(f"{len(deps)} packages installed into {game}")


def state() -> dict:
    return json.loads((game_dir() / "BepInEx/haldor.json").read_text())


def play() -> None:
    game = game_dir()
    os.chdir(game)
    os.execv("/bin/sh", ["sh", str(game / "run_bepinex.sh")])


def main() -> None:
    match sys.argv[1:]:
        case ["install", pack]:
            install(pack, [])
        case ["add", pkg]:
            s = state()
            extras = s.get("extras", [])
            install(s["pack"], extras if pkg in extras else extras + [pkg])
        case ["update"]:
            s = state()
            install(s["pack"], s.get("extras", []))
        case ["play"]:
            play()
        case ["gui"]:
            import gui
            gui.main()
        case _:
            sys.exit("usage: haldor "
                     "(install <namespace/pack> | add <namespace/name> | update | play | gui)")


if __name__ == "__main__":
    main()
