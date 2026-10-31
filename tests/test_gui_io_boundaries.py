import ast
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _GuiCallCollector(ast.NodeVisitor):
    def __init__(self):
        self.functions = []
        self.calls = []

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        target = node.func
        if (isinstance(target, ast.Attribute)
                and target.attr == "_call"
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"):
            command = (node.args[0].value
                       if node.args and isinstance(node.args[0], ast.Constant)
                       else "<dynamic>")
            self.calls.append((self.functions[-1], command))
        self.generic_visit(node)


def gui_calls(relative_path):
    collector = _GuiCallCollector()
    collector.visit(ast.parse(
        (ROOT / relative_path).read_text(encoding="utf-8"),
        filename=relative_path))
    return Counter(collector.calls)


class GuiIoBoundaryTests(unittest.TestCase):
    def test_removed_synchronous_facades_stay_out_of_backend(self):
        source = (ROOT / "ampere/mpdclient.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        removed = {
            "setRating", "currentRating", "_refresh_liked",
            "_refresh_disliked",
        }
        self.assertTrue(removed.isdisjoint(functions))
        self.assertNotIn("self._playlist_service =", source)
        self.assertNotIn("self._library_updates =", source)
        self.assertNotIn("self._replay_gain_daemon =", source)
        self.assertNotIn("self._automix_daemon =", source)

    def test_gui_mpd_reads_stay_inside_reviewed_mutation_boundaries(self):
        """New Qt-thread reads require an explicit architecture decision.

        Presentation, planning, timers, and ordinary controls use retained
        snapshots or owned workers. These remaining calls reconcile a mutation
        whose correctness depends on immediate daemon truth; bridge splice is
        separately deferred until queue mutations share one coordinator.
        """
        self.assertEqual(Counter(), gui_calls("ampere/mpdclient.py"))
        self.assertEqual(Counter(), gui_calls("ampere/dj/planner.py"))

    def test_dj_whole_family_reads_require_an_explicit_worker_client(self):
        tree = ast.parse((ROOT / "ampere/dj/planner.py").read_text(
            encoding="utf-8"))
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if not (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"):
                continue
            required = {"_sticker_map": 2, "_energies": 1}.get(target.attr)
            if required is not None and len(node.args) < required:
                missing.append((target.attr, node.lineno))
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
