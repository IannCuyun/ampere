"""Contract for the honest first-index state (ux(ready)).

Pins the backend readiness property, the shared loading component, and that
every room which renders library content gates on `libraryReady` instead of
showing an unexplained void while the worker reads the archive.
"""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "qml"
BACKEND = ROOT / "ampere" / "mpdclient.py"

GATED_VIEWS = (
    "LibraryView.qml",
    "LandingView.qml",
    "ArtistView.qml",
    "AlbumView.qml",
    "BrowseView.qml",
    "SearchDropdown.qml",
)


class LibraryReadinessContractTests(unittest.TestCase):
    def backend_class(self):
        tree = ast.parse(BACKEND.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Backend":
                return node
        self.fail("Backend class not found")

    def test_backend_exposes_library_ready_property_with_notify(self):
        cls = self.backend_class()
        props = {}
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                for deco in node.decorator_list:
                    if (isinstance(deco, ast.Call)
                            and getattr(deco.func, "id", "") == "Property"):
                        notify = [kw.value.id for kw in deco.keywords
                                  if kw.arg == "notify"]
                        kind = deco.args[0]
                        kind = getattr(kind, "id", None) or getattr(kind, "value", None)
                        props[node.name] = (kind, notify)
        self.assertEqual(("bool", ["libraryReadyChanged"]), props["libraryReady"])
        self.assertEqual("int", props["libraryTotalSongs"][0])
        signals = {t.id for node in cls.body if isinstance(node, ast.Assign)
                   for t in node.targets if isinstance(t, ast.Name)}
        self.assertIn("libraryReadyChanged", signals)

    def test_ready_flips_only_on_a_successful_index(self):
        source = BACKEND.read_text(encoding="utf-8")
        self.assertIn("self._library_ready = False", source)
        ready = source.index("self._library_ready = True")
        emit = source.index("self.databaseUpdated.emit()")
        self.assertLess(ready, emit, "ready must flip before databaseUpdated")
        self.assertIn("self.libraryReadyChanged.emit()", source)

    def test_shared_loading_component_follows_the_wash_recipe(self):
        source = (QML / "ArchiveLoading.qml").read_text(encoding="utf-8")
        for needle in ("Reading the archive…", "Theme.displayFont",
                       "Theme.washMicro", "font.letterSpacing: 3",
                       "Font.AllUppercase", "Theme.washFaint",
                       "Theme.washMuted", "Theme.fsSmall",
                       "songs indexed so far"):
            self.assertIn(needle, source)
        self.assertNotIn("BusyIndicator", source)
        self.assertNotIn("Rectangle", source)

    def test_every_library_room_gates_on_readiness(self):
        for name in GATED_VIEWS:
            with self.subTest(view=name):
                source = (QML / name).read_text(encoding="utf-8")
                self.assertIn("libraryReady", source)
                self.assertIn("ArchiveLoading {", source)

    def test_search_dropdown_keeps_the_provider_indirection(self):
        source = (QML / "SearchDropdown.qml").read_text(encoding="utf-8")
        self.assertIn("property var readinessProvider: backend", source)
        self.assertIn("readinessProvider.libraryReady", source)
        self.assertNotIn("backend.libraryReady", source)


if __name__ == "__main__":
    unittest.main()
