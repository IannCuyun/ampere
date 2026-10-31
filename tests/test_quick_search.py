import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QuickSearchBoundaryTests(unittest.TestCase):
    def test_quick_search_uses_an_owned_worker(self):
        tree = ast.parse(
            (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8"))
        method = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "requestQuickSearch")
        calls = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_start_worker"
        ]
        self.assertEqual(1, len(calls))

    def test_full_results_page_slot_is_retired(self):
        source = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        self.assertNotIn("def requestSearchResults", source)
        self.assertNotIn("searchResultsReady", source)
        self.assertFalse((ROOT / "qml/SearchResultsView.qml").exists())

    def test_quick_search_worker_reports_failure_instead_of_vanishing(self):
        from ampere.search import SearchCatalog, run_quick_search

        class Broken(SearchCatalog):
            def query(self, text):
                raise RuntimeError("index exploded")

        ready, failed = [], []
        ok = run_quick_search(
            Broken(), "bully", serial=7, lyrics_pending=True,
            on_ready=lambda q, r: ready.append((q, r)),
            on_failed=lambda q, s, why: failed.append((q, s, why)))
        self.assertFalse(ok)
        self.assertEqual([], ready)
        self.assertEqual([("bully", 7, "index exploded")], failed)

    def test_quick_search_result_carries_serial_and_generation(self):
        from ampere.search import SearchCatalog, run_quick_search

        catalog = SearchCatalog()
        generation = catalog.replace_songs([
            {"file": "a/b.flac", "title": "Bully", "artist": "K", "album": "A"}])
        ready = []
        self.assertTrue(run_quick_search(
            catalog, "bully", serial=3, lyrics_pending=False,
            on_ready=lambda q, r: ready.append(r),
            on_failed=lambda *_: self.fail("unexpected failure")))
        self.assertEqual(3, ready[0]["serial"])
        self.assertEqual(generation, ready[0]["generation"])
        self.assertFalse(ready[0]["lyricsPending"])
        self.assertEqual([], ready[0]["lyrics"])


if __name__ == "__main__":
    unittest.main()
