import unittest
from collections import deque
from types import SimpleNamespace

from ampere.listening_progress import (ListeningProgressService,
                                      ProgressObservation, ProgressUpdate,
                                      update_progress)
from ampere.mpdclient import Backend


class ListeningProgressTests(unittest.TestCase):
    def update(self, **changes):
        values = dict(previous_file="old.flac", previous_max=90,
                      previous_duration=180, current_file="new.flac",
                      elapsed=2, duration=240, song_changed=True, dj_on=False,
                      resume_min_seconds=1200)
        values.update(changes)
        return update_progress(**values)

    def test_half_heard_track_counts_once_on_departure(self):
        self.assertTrue(self.update(previous_max=90).count_previous)
        self.assertFalse(self.update(previous_max=89.9).count_previous)
        self.assertFalse(self.update(previous_duration=8,
                                     previous_max=8).count_previous)

    def test_midway_long_track_persists_integer_resume_position(self):
        result = self.update(previous_duration=1800, previous_max=742.9)
        self.assertEqual(result.resume_action, "set")
        self.assertEqual(result.resume_file, "old.flac")
        self.assertEqual(result.resume_position, 742)

    def test_edges_of_long_track_clear_stale_resume(self):
        self.assertEqual(self.update(
            previous_duration=1800, previous_max=60).resume_action, "delete")
        self.assertEqual(self.update(
            previous_duration=1800, previous_max=1740).resume_action, "delete")
        self.assertEqual(self.update(
            previous_duration=1199, previous_max=500).resume_action, "")

    def test_song_change_resets_progress_to_incoming_snapshot(self):
        result = self.update(elapsed=3.5, duration=500)
        self.assertEqual((result.file, result.max_elapsed, result.duration),
                         ("new.flac", 3.5, 500))

    def test_same_song_is_monotonic_and_detects_dj_backward_seek(self):
        result = self.update(song_changed=False, current_file="old.flac",
                             previous_max=100, elapsed=97, dj_on=True)
        self.assertEqual(result.max_elapsed, 100)
        self.assertTrue(result.backward_seek)
        ordinary = self.update(song_changed=False, current_file="old.flac",
                               previous_max=100, elapsed=99, dj_on=True)
        self.assertFalse(ordinary.backward_seek)


class ListeningProgressServiceTests(unittest.TestCase):
    def service(self):
        return ListeningProgressService(resume_min_seconds=1200)

    def test_departure_describes_playcount_and_resume_once(self):
        service = self.service()
        service.observe(current_file="long.flac", elapsed=1000.9,
                        duration=1800, song_changed=True, dj_on=False)
        result = service.observe(
            current_file="next.flac", elapsed=2, duration=200,
            song_changed=True, dj_on=False)

        self.assertTrue(result.update.count_previous)
        self.assertEqual("set", result.update.resume_action)
        self.assertEqual("long.flac", result.update.resume_file)
        self.assertEqual(1000, result.update.resume_position)

    def test_reentry_requests_deferred_resume_lookup(self):
        service = self.service()
        result = service.observe(
            current_file="long.flac", elapsed=2, duration=1800,
            song_changed=True, dj_on=False)

        self.assertEqual("long.flac", result.resume_lookup_file)
        self.assertEqual(2.0, service.max_elapsed)
        service.accept_resume(742)
        self.assertEqual(742.0, service.max_elapsed)

    def test_short_or_already_advanced_tracks_skip_resume_lookup(self):
        for elapsed, duration in ((2, 1199), (5, 1800)):
            with self.subTest(elapsed=elapsed, duration=duration):
                result = self.service().observe(
                    current_file="long.flac", elapsed=elapsed,
                    duration=duration, song_changed=True, dj_on=False)
                self.assertEqual("", result.resume_lookup_file)

    def test_backward_seek_remains_a_side_effect_free_signal(self):
        service = self.service()
        service.observe(current_file="song", elapsed=100, duration=200,
                        song_changed=True, dj_on=True)
        result = service.observe(
            current_file="song", elapsed=90, duration=200,
            song_changed=False, dj_on=True)
        self.assertTrue(result.update.backward_seek)


class BackendListeningProgressLifecycleTests(unittest.TestCase):
    def harness(self):
        backend = SimpleNamespace(
            _listening_progress_generation=0,
            _listening_progress_jobs=deque(),
            _listening_progress_busy=False,
            launched=[],
        )
        backend._start_worker = lambda work, **_kwargs: (
            backend.launched.append(work) or True)
        backend._start_next_listening_progress_job = lambda: (
            Backend._start_next_listening_progress_job(backend))
        return backend

    def observation(self, file):
        return ProgressObservation(ProgressUpdate(
            file=file, max_elapsed=2, duration=1800,
            resume_action="delete", resume_file="old.flac"), file)

    def test_transition_jobs_are_fifo_and_only_one_worker_runs(self):
        backend = self.harness()

        Backend._enqueue_listening_progress(
            backend, self.observation("first.flac"))
        Backend._enqueue_listening_progress(
            backend, self.observation("second.flac"))

        self.assertEqual(2, backend._listening_progress_generation)
        self.assertEqual(1, len(backend.launched))
        self.assertEqual(1, len(backend._listening_progress_jobs))
        self.assertEqual(
            "second.flac",
            backend._listening_progress_jobs[0]["current_file"])

    def test_stale_or_late_result_cannot_seek(self):
        backend = SimpleNamespace(
            _listening_progress_busy=True,
            _listening_progress_generation=2,
            _song={"file": "new.flac"}, _elapsed=2, _duration=1800,
            _play_record_failed=False, seeks=[],
            _publish_play_record=lambda *_args: None,
            _report_listening_progress_failure=lambda: None,
            _start_next_listening_progress_job=lambda: None,
            _seek_current_once=lambda seconds: (
                backend.seeks.append(seconds) or True),
            _listening_progress=SimpleNamespace(accept_resume=lambda _p: None),
        )
        payload = {
            "generation": 1,
            "current_file": "old.flac",
            "update": ProgressUpdate("old.flac", 2, 1800),
            "resume_position": 742,
            "resume_available": True,
        }

        Backend._on_listening_progress_ready(backend, payload)

        self.assertEqual([], backend.seeks)


if __name__ == "__main__":
    unittest.main()
