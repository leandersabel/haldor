#!/usr/bin/env python3
"""What the resolver and the unpacker do, without a network or a game on disk."""

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import haldor


def zipped(*names: str) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in names:
            zf.writestr(n, b"x")
    return zipfile.ZipFile(buf)


class Split(unittest.TestCase):
    """Thunderstore writes a pin as namespace-name-version, and a namespace and a
    name hold no dash, so every dash but the last one joins the two halves."""

    def test_a_pin_becomes_a_reference_and_a_version(self):
        self.assertEqual(haldor.split("denikson-BepInExPack_Valheim-5.4.2202"),
                         ("denikson/BepInExPack_Valheim", "5.4.2202"))


class Resolve(unittest.TestCase):
    """The pack pins the versions. An extra or a transitive edge fills a gap only."""

    def setUp(self):
        self.deps = {}   # full_name -> its dependencies
        self.newest = {}  # namespace/name -> its newest full_name

        def latest(pkg):
            full = self.newest[pkg]
            return {"full_name": full, "dependencies": self.deps.get(full, [])}

        def fetch(url):
            namespace, name, version = url.rstrip("/").split("/")[-3:]
            full = f"{namespace}-{name}-{version}"
            return json.dumps({"dependencies": self.deps.get(full, [])}).encode()

        for name, fake in (("latest", latest), ("fetch", fetch)):
            patch = mock.patch.object(haldor, name, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_pack_pins_over_a_transitive_older_edge(self):
        self.newest["p/Pack"] = "p-Pack-1.0.0"
        self.deps["p-Pack-1.0.0"] = ["a-Core-2.0.0", "a-Mod-1.0.0"]
        self.deps["a-Mod-1.0.0"] = ["a-Core-1.0.0"]
        self.assertEqual(haldor.resolve(haldor.latest("p/Pack"), []),
                         ["a-Core-2.0.0", "a-Mod-1.0.0"])

    def test_an_extra_comes_after_the_pack(self):
        self.newest["p/Pack"] = "p-Pack-1.0.0"
        self.newest["x/Extra"] = "x-Extra-3.0.0"
        self.deps["p-Pack-1.0.0"] = ["a-Core-2.0.0"]
        self.assertEqual(haldor.resolve(haldor.latest("p/Pack"), ["x/Extra"]),
                         ["a-Core-2.0.0", "x-Extra-3.0.0"])

    def test_an_extra_the_pack_already_pins_does_not_move_the_version(self):
        self.newest["p/Pack"] = "p-Pack-1.0.0"
        self.newest["a/Core"] = "a-Core-9.0.0"
        self.deps["p-Pack-1.0.0"] = ["a-Core-2.0.0"]
        self.assertEqual(haldor.resolve(haldor.latest("p/Pack"), ["a/Core"]),
                         ["a-Core-2.0.0"])

    def test_a_cycle_terminates(self):
        self.newest["p/Pack"] = "p-Pack-1.0.0"
        self.deps["p-Pack-1.0.0"] = ["a-One-1.0.0"]
        self.deps["a-One-1.0.0"] = ["a-Two-1.0.0"]
        self.deps["a-Two-1.0.0"] = ["a-One-1.0.0"]
        self.assertEqual(haldor.resolve(haldor.latest("p/Pack"), []),
                         ["a-One-1.0.0", "a-Two-1.0.0"])


class Unpack(unittest.TestCase):
    """The three layouts a Thunderstore package arrives in."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name)
        self.bep = self.game / "BepInEx"

    def test_a_package_carrying_bepinex_overlays_the_game_root(self):
        haldor.unpack(zipped("Pack/BepInEx/plugins/Foo.dll", "Pack/README.md"),
                      self.bep, "a/Foo")
        self.assertTrue((self.bep / "plugins/Foo.dll").exists())
        self.assertTrue((self.game / "README.md").exists())

    def test_a_package_of_bare_folders_lands_inside_bepinex(self):
        haldor.unpack(zipped("plugins/Foo.dll", "config/Foo.cfg"), self.bep, "a/Foo")
        self.assertTrue((self.bep / "plugins/Foo.dll").exists())
        self.assertTrue((self.bep / "config/Foo.cfg").exists())

    def test_a_bare_dll_gets_a_folder_named_for_the_package(self):
        haldor.unpack(zipped("Foo.dll", "icon.png"), self.bep, "a/Foo")
        self.assertTrue((self.bep / "plugins/a-Foo/Foo.dll").exists())

    def test_an_entry_climbing_out_of_the_install_is_refused(self):
        with self.assertRaisesRegex(haldor.HaldorError, "writes outside the install"):
            haldor.unpack(zipped("plugins/../../../../evil.sh"), self.bep, "a/Evil")
        self.assertFalse((self.game.parent / "evil.sh").exists())


class Loader(unittest.TestCase):
    """What the loader overlay lays down beyond the packages the pack names."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name)
        # The launcher is the only file install_loader edits rather than writes.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("run_bepinex.sh", "executable_name=\"x\"\nexport ARCHPREFERENCE=\"\"\n")
        patch = mock.patch.object(haldor, "fetch", return_value=buf.getvalue())
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_shader_rules_land_in_a_config_directory_nothing_has_made_yet(self):
        haldor.install_loader(self.game)
        dest = self.game / "BepInEx/config/ShaderHelperForMac"
        shipped = sorted(p.name for p in (haldor.HERE / "shaderfix").glob("*.txt"))
        self.assertTrue(shipped, "a rule file is what this ships")
        self.assertEqual(sorted(p.name for p in dest.glob("*.txt")), shipped)

    def test_the_launcher_runs_the_app_on_arm64_through_the_cecil_backend(self):
        haldor.install_loader(self.game)
        text = (self.game / "run_bepinex.sh").read_text()
        self.assertIn('executable_name="valheim.app"', text)
        self.assertIn('export ARCHPREFERENCE="arm64"', text)
        self.assertIn('export MONOMOD_DMDType="cecil"', text)


class Fetch(unittest.TestCase):
    """The cache holds bodies that cannot change, so what lands in it must be whole."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(haldor, "CACHE", Path(tmp.name) / "cache")
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_body_matching_its_checksum_comes_back(self):
        digest = hashlib.sha256(b"loader").hexdigest()
        with mock.patch.object(haldor, "get", return_value=b"loader"):
            self.assertEqual(haldor.fetch("https://x/a.zip", digest), b"loader")

    def test_a_body_failing_its_checksum_is_refused_and_not_kept(self):
        with mock.patch.object(haldor, "get", return_value=b"tampered"):
            with self.assertRaises(haldor.HaldorError):
                haldor.fetch("https://x/b.zip", hashlib.sha256(b"loader").hexdigest())
        self.assertEqual(list(haldor.CACHE.glob("*")), [],
                         "a body that failed its checksum must not stay cached")

    def test_a_download_that_dies_leaves_nothing_to_trust(self):
        with mock.patch.object(haldor, "get", side_effect=haldor.HaldorError("cut")):
            with self.assertRaises(haldor.HaldorError):
                haldor.fetch("https://x/c.zip")
        with mock.patch.object(haldor, "get", return_value=b"whole"):
            self.assertEqual(haldor.fetch("https://x/c.zip"), b"whole")


class Errors(unittest.TestCase):
    def test_an_unreachable_host_is_reported_not_raised_raw(self):
        import urllib.error
        with mock.patch.object(haldor.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(haldor.HaldorError):
                haldor.get("https://thunderstore.io/api/")

    def test_nothing_installed_is_its_own_error(self):
        with mock.patch.object(haldor, "game_dir", return_value=Path("/nope")):
            with self.assertRaises(haldor.NotInstalled):
                haldor.state()


if __name__ == "__main__":
    unittest.main()
