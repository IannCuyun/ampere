import pathlib
import tomllib
import unittest
import xml.etree.ElementTree as ET

import ampere


ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
METAINFO = ROOT / "packaging/io.github.ianncuyun.ampere.metainfo.xml"


class ReleaseMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        cls.component = ET.parse(METAINFO).getroot()

    def test_every_public_version_agrees(self):
        version = self.project["project"]["version"]
        self.assertEqual("1.0.1", version)
        self.assertEqual(version, ampere.__version__)
        self.assertEqual(
            version,
            self.component.find("./releases/release").attrib["version"],
        )
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{version}]", changelog)

    def test_package_installs_one_runtime_matching_desktop_entry(self):
        data_files = self.project["tool"]["setuptools"]["data-files"]
        self.assertEqual(
            ["packaging/ampere.desktop"], data_files["share/applications"]
        )
        self.assertEqual(
            "ampere.desktop",
            self.component.find("launchable").text,
        )
        mpris = (ROOT / "ampere/mpris.py").read_text(encoding="utf-8")
        self.assertIn('"DesktopEntry": "ampere"', mpris)

    def test_package_globs_cannot_admit_backup_shaders(self):
        shaders = self.project["tool"]["setuptools"]["data-files"][
            "share/ampere/qml/shaders"
        ]
        self.assertEqual(
            ["qml/shaders/*.frag", "qml/shaders/*.qsb"], shaders
        )
        self.assertNotIn("qml/shaders/*", shaders)


if __name__ == "__main__":
    unittest.main()
