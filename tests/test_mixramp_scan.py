import unittest

from ampere.mixramp_scan import MixRampScanner


class MixRampScannerTests(unittest.TestCase):
    def test_accounts_for_every_outcome_and_reports_tagged_progress(self):
        outcomes = iter(["tagged", "skipped", "failed"])
        calls, reports = [], []

        def tag(path, *, force=False):
            calls.append((path, force))
            return next(outcomes)

        result = MixRampScanner("/music", tag_file=tag).scan(
            ["one.flac", "two.flac", "three.flac"], force=True,
            progress=lambda *values: reports.append(values))

        self.assertEqual([
            ("/music/one.flac", True),
            ("/music/two.flac", True),
            ("/music/three.flac", True),
        ], calls)
        self.assertEqual([(3, 3, 1)], reports)
        self.assertEqual((3, 1, 1, 1, False),
                         (result.done, result.tagged, result.skipped,
                          result.failed, result.cancelled))

    def test_cancellation_reports_actual_work_not_false_completion(self):
        stopped, reports = [False], []

        def tag(_path, *, force=False):
            _ = force
            stopped[0] = True
            return "tagged"

        result = MixRampScanner("/music", tag_file=tag).scan(
            ["one", "two"], should_stop=lambda: stopped[0],
            progress=lambda *values: reports.append(values))

        self.assertEqual([(1, 2, 1)], reports)
        self.assertEqual((2, 1, 1, True),
                         (result.total, result.done, result.tagged,
                          result.cancelled))

    def test_tagger_exception_is_counted_as_failure(self):
        result = MixRampScanner(
            "/music", tag_file=lambda *_args, **_kwargs: 1 / 0).scan(["bad"])
        self.assertEqual((1, 1), (result.done, result.failed))

    def test_empty_snapshot_emits_stable_empty_progress(self):
        reports = []
        result = MixRampScanner("/music").scan(
            [], progress=lambda *values: reports.append(values))
        self.assertEqual([(0, 0, 0)], reports)
        self.assertEqual(0, result.total)


if __name__ == "__main__":
    unittest.main()
