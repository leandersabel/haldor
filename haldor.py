#!/usr/bin/env python3
"""Install a Thunderstore modpack into the macOS build of Valheim and launch it."""

import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

API = "https://thunderstore.io/api/experimental/package"
BEPINEX_VERSION = "5.4.23.5"
BEPINEX = (f"https://github.com/BepInEx/BepInEx/releases/download/v{BEPINEX_VERSION}"
           f"/BepInEx_macos_universal_{BEPINEX_VERSION}.zip")
# The loader runs inside the game, and a release asset can be replaced under a tag
# that does not move. shasum -a 256 on what the URL above serves.
BEPINEX_SHA256 = "01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323"
STEAM = Path.home() / "Library/Application Support/Steam"
# Beside this file, or inside the app bundle once PyInstaller has unpacked it.
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
CACHE = Path.home() / "Library/Caches/haldor"

# The app bundle brings its own Python, which has no trust store to verify
# thunderstore.io against, so it brings certificates too. A checkout has neither and
# uses whatever its own Python trusts.
CERTS = HERE / "certs" / "cacert.pem"
if CERTS.exists():
    os.environ.setdefault("SSL_CERT_FILE", str(CERTS))


class HaldorError(Exception):
    """A condition the user can act on. Both front ends show its message and stop."""


class NotInstalled(HaldorError):
    """No modpack has been laid down in this game yet."""


def game_dir() -> Path:
    """Locate the Valheim install through Steam's library index."""
    vdf = STEAM / "steamapps/libraryfolders.vdf"
    if not vdf.exists():
        raise HaldorError("Steam not found")
    for lib in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text()):
        d = Path(lib) / "steamapps/common/Valheim"
        if (d / "valheim.app").is_dir():
            return d
    raise HaldorError("Valheim not found in any Steam library")


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "haldor"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.read()
    except urllib.error.URLError as e:
        # HTTPError is a URLError, so a wrong name and a dead network both land here.
        raise HaldorError(f"{url}: {e.reason}") from None


def fetch(url: str, sha256: str = "") -> bytes:
    """Cache a URL whose body cannot change: a pinned version or a download."""
    cached = CACHE / re.sub(r"[^\w.-]", "_", url)
    if not cached.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        # Moved into place whole, so a download cut short leaves nothing to trust.
        partial = cached.parent / (cached.name + ".partial")
        partial.write_bytes(get(url))
        partial.replace(cached)
    data = cached.read_bytes()
    if sha256 and hashlib.sha256(data).hexdigest() != sha256:
        cached.unlink()
        raise HaldorError(f"{url} is not the file it should be")
    return data


def latest(pkg: str) -> dict:
    """The newest published version of a namespace/name reference."""
    return json.loads(get(f"{API}/{pkg}/"))["latest"]


def split(dep: str) -> tuple[str, str]:
    """A pinned full_name into its namespace/name and its version."""
    *parts, version = dep.split("-")
    return "/".join(parts), version


def newest(pack: str) -> str:
    """The version Thunderstore publishes for a pack right now."""
    return latest(pack)["version_number"]


def resolve(pack: dict, extras: list[str]) -> list[str]:
    """Expand a pack's newest release and its extras into pinned dependencies."""
    queue = pack["dependencies"] + [latest(e)["full_name"] for e in extras]
    seen, order = set(), []
    while queue:
        dep = queue.pop(0)
        pkg, version = split(dep)
        # The pack pins its own versions and is queued first, so an extra or a
        # transitive edge only fills a gap.
        if pkg in seen:
            continue
        seen.add(pkg)
        order.append(dep)
        meta = json.loads(fetch(f"{API}/{pkg}/{version}/"))
        queue += meta.get("dependencies", [])
    return order


def unpack(zf: zipfile.ZipFile, bep: Path, pkg: str) -> None:
    """Write out one Thunderstore package, honouring its layout."""
    names = zf.namelist()

    # A package that carries its own BepInEx tree overlays the game root.
    root = next((n[: n.index("BepInEx/")] for n in names if "BepInEx/" in n), None)
    if root is not None:
        dest, strip = bep.parent, root
    elif any(n.startswith(("plugins/", "patchers/", "config/")) for n in names):
        dest, strip = bep, ""
    else:
        dest, strip = bep / "plugins" / pkg.replace("/", "-"), ""

    for n in names:
        if n.endswith("/") or not n.startswith(strip):
            continue
        target = dest / n[len(strip):]
        # An entry that climbs out of dest would write anywhere on the disk.
        if not target.resolve().is_relative_to(dest.resolve()):
            raise HaldorError(f"{pkg} writes outside the install: {n}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(n))


def install_mod(dep: str, bep: Path) -> None:
    pkg, version = split(dep)
    data = fetch(f"https://thunderstore.io/package/download/{pkg}/{version}/")
    unpack(zipfile.ZipFile(io.BytesIO(data)), bep, pkg)


def install_loader(game: Path) -> None:
    """Everything the pack needs on top of itself to run on an Apple Silicon Mac.

    The macOS build of BepInEx, overlaid and then given the arm64 core: stock BepInEx
    bundles MonoMod 22, which patches code by asking for RWX memory, and Apple Silicon
    refuses that, so the core here is rebuilt against MonoMod 25. See ARM64.md.
    Doorstop and the launcher come from upstream unchanged.
    """
    zf = zipfile.ZipFile(io.BytesIO(fetch(BEPINEX, BEPINEX_SHA256)))
    zf.extractall(game)

    core = game / "BepInEx" / "core"
    shutil.rmtree(core, ignore_errors=True)
    shutil.copytree(HERE / "bepinex-arm64" / "core", core)

    script = game / "run_bepinex.sh"
    text = script.read_text()
    text = re.sub(r'^executable_name=.*', 'executable_name="valheim.app"', text, flags=re.M)
    # MonoMod waits out a method's callers before repatching it, and finds them by
    # walking the stack. Its own dynamic methods do not appear there under Unity's
    # Mono, so a mod that repatches from inside a patched method waits on itself and
    # the game stops. The Cecil backend emits real methods, which the walk can see.
    text = re.sub(r'^(\s*)export ARCHPREFERENCE=.*',
                  r'\1export ARCHPREFERENCE="arm64"\n\1export MONOMOD_DMDType="cecil"',
                  text, flags=re.M)
    script.write_text(text)
    script.chmod(0o755)

    # ShaderHelperForMac repairs materials whose shader has no Metal variant. Its scan
    # skips the largest mod DLLs, and it refuses a Valheim material on a Valheim shader
    # unless a rule names the prefab it sits under. These files are those rules.
    rules = game / "BepInEx" / "config" / "ShaderHelperForMac"
    rules.mkdir(parents=True, exist_ok=True)
    for rule in (HERE / "shaderfix").glob("*.txt"):
        shutil.copy(rule, rules / rule.name)


def install(pack: str, extras: list[str], log=print) -> None:
    game = game_dir()
    bep = game / "BepInEx"
    log(f"⏺ Resolving {pack}")
    # Before anything is removed, so a wrong name or a dead network leaves the
    # install that is already there.
    release = latest(pack)
    deps = resolve(release, extras)
    for d in ("plugins", "patchers", "core"):
        shutil.rmtree(bep / d, ignore_errors=True)
    log("⏺ Installing")
    for dep in deps:
        log(f"  ⎿  {dep}")
        install_mod(dep, bep)
    install_loader(game)
    (bep / "haldor.json").write_text(json.dumps(
        {"pack": pack, "version": release["version_number"],
         "extras": extras, "mods": deps}, indent=2))
    log(f"⏺ Installed {pack} {release['version_number']} into {game}")


def state() -> dict:
    """What the last install recorded: the pack, its version, its extras and the
    pinned mods."""
    path = game_dir() / "BepInEx/haldor.json"
    if not path.exists():
        raise NotInstalled("nothing installed yet")
    return json.loads(path.read_text())


def play() -> None:
    game = game_dir()
    script = game / "run_bepinex.sh"
    if not script.exists():
        raise NotInstalled("nothing installed yet")
    os.chdir(game)
    os.execv("/bin/sh", ["sh", str(script)])


def main() -> None:
    # Plain ifs, not match, so any python3 can run the command line.
    args = sys.argv[1:]
    try:
        if args[:1] == ["install"] and len(args) == 2:
            install(args[1], [])
        elif args[:1] == ["add"] and len(args) == 2:
            s = state()
            extras = s.get("extras", [])
            install(s["pack"], extras if args[1] in extras else extras + [args[1]])
        elif args == ["update"]:
            s = state()
            install(s["pack"], s.get("extras", []))
        elif args == ["play"]:
            play()
        else:
            sys.exit("usage: haldor "
                     "(install <namespace/pack> | add <namespace/name> | update | play)")
    except HaldorError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
