import unittest

from ampere.dj.splice import splice_bridge


class BridgeHarness:
    def __init__(self):
        self.queue = [
            {"id": "10", "pos": "0", "file": "a.flac"},
            {"id": "20", "pos": "1", "file": "b.flac"},
        ]
        self.next_id = 30
        self.ranges = {}
        self.deleted = []
        self.lose_reply = False
        self.reject_a = False

    def add_once(self, path, pos):
        row = {"id": str(self.next_id), "pos": str(pos), "file": path}
        self.queue.insert(pos, row)
        for index, item in enumerate(self.queue):
            item["pos"] = str(index)
        if self.lose_reply:
            return False
        return True

    def set_range(self, sid, spec):
        if self.reject_a and sid == 10:
            return False
        self.ranges[sid] = spec
        return True

    def delete_once(self, sid):
        self.deleted.append(sid)
        self.queue = [row for row in self.queue if int(row["id"]) != sid]
        return True


class DjBridgeSpliceTests(unittest.TestCase):
    def splice(self, harness):
        return splice_bridge(
            initial_queue=list(harness.queue), a_id=10, b_id=20,
            path="/cache/bridge.flac", a_end=123.4, b_start=17.2,
            prior_a=None, prior_b=None, add_once=harness.add_once,
            set_range=harness.set_range, delete_once=harness.delete_once,
            read_queue=lambda: list(harness.queue))

    def test_lost_add_reply_recovers_inserted_bridge_by_adjacency(self):
        harness = BridgeHarness()
        harness.lose_reply = True

        result = self.splice(harness)

        self.assertTrue(result.committed)
        self.assertEqual(30, result.bridge_id)
        self.assertEqual({20: "17.20:", 10: "0.00:123.40"},
                         harness.ranges)

    def test_incomplete_range_commit_removes_bridge_and_restores_ranges(self):
        harness = BridgeHarness()
        harness.reject_a = True

        result = self.splice(harness)

        self.assertFalse(result.committed)
        self.assertEqual([30], harness.deleted)
        self.assertEqual(":", harness.ranges[20])

    def test_preexisting_render_path_is_not_mistaken_for_new_bridge(self):
        harness = BridgeHarness()
        harness.queue.insert(0, {"id": "31", "pos": "0",
                                 "file": "/cache/bridge.flac"})
        for index, row in enumerate(harness.queue):
            row["pos"] = str(index)

        result = self.splice(harness)

        self.assertTrue(result.committed)
        self.assertEqual(30, result.bridge_id)


if __name__ == "__main__":
    unittest.main()
