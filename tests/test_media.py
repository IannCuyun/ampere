import unittest
import hashlib
import json
import math
import tempfile
from pathlib import Path

from ampere.media import MediaEnrichmentService, MediaPrefetcher


class FakeMedia:
    info = type("Info", (), {"sample_rate": 48000, "bits_per_sample": 24})()

    def get(self, key):
        return {"replaygain_track_gain": ["-7.25 dB"],
                "mixramp_end": ["-30 172; -10 160"],
                "date": ["2024-10-04"]}.get(key)


class MediaEnrichmentTests(unittest.TestCase):
    def service(self, wave_dir="/tmp/ampere-media-test-unused"):
        return MediaEnrichmentService(
            "/music", read_lyrics=lambda _path: ([{"t": 1, "line": "Hello"}], True),
            average_kbps=lambda _file, _duration: 921,
            tail_cut=lambda _file, _duration: 178.4,
            compute_wave=lambda _path: [.1, .7],
            wave_dir=wave_dir,
            art_colors=lambda _file: ["#112233", "#445566"],
            mutagen_file=lambda _path: FakeMedia())

    def test_reads_display_metadata_in_one_enrichment_result(self):
        result = self.service().read_song("Artist/Song.flac", 180)
        self.assertEqual("FLAC · 921 kbps · 48k/24", result.info)
        self.assertEqual(-7.25, result.replay_gain_db)
        self.assertEqual("-7.25 dB", result.replay_gain_text)
        self.assertEqual("-30 172; -10 160", result.mixramp_end)
        self.assertTrue(result.lyrics_synced)
        self.assertEqual(178.4, result.tail_cut)

    def test_component_failures_degrade_to_safe_partial_metadata(self):
        service = MediaEnrichmentService(
            "/music", read_lyrics=lambda _path: 1 / 0,
            average_kbps=lambda *_args: 1 / 0,
            tail_cut=lambda *_args: 1 / 0,
            mutagen_file=lambda _path: 1 / 0)

        result = service.read_song("Artist/Song.flac", 180)

        self.assertEqual("FLAC", result.info)
        self.assertIsNone(result.replay_gain_db)
        self.assertEqual((), result.lyrics)
        self.assertFalse(result.lyrics_synced)
        self.assertEqual(0.0, result.tail_cut)

    def test_invalid_tail_cut_values_are_never_published(self):
        for tail, duration in ((math.nan, 180), (math.inf, 180),
                               (-1, 180), (181, 180), (10, 0)):
            with self.subTest(tail=tail, duration=duration):
                service = MediaEnrichmentService(
                    "/music", read_lyrics=lambda _path: ([], False),
                    average_kbps=lambda *_args: 0,
                    tail_cut=lambda *_args, value=tail: value,
                    mutagen_file=lambda _path: None)
                self.assertEqual(
                    0.0, service.read_song("song.flac", duration).tail_cut)

    def test_generation_rejects_an_old_result_for_the_same_file(self):
        service = self.service()
        first = service.begin("one.flac", "metadata")
        service.begin("two.flac", "metadata")
        latest = service.begin("one.flac", "metadata")
        self.assertFalse(service.accepts(first, "one.flac", "one.flac"))
        self.assertTrue(service.accepts(latest, "one.flac", "one.flac"))

    def test_worker_kinds_have_independent_generations(self):
        service = self.service()
        wave = service.begin("one.flac", "wave")
        service.begin("one.flac", "colors")
        self.assertTrue(service.accepts(wave, "one.flac", "one.flac", "wave"))
        self.assertEqual(["#112233", "#445566"],
                         service.read_art_colors("one.flac"))

    def test_cached_waveform_read_never_invokes_audio_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            file = "Artist/Album/song.flac"
            key = hashlib.sha1(("v2:" + file).encode(),
                               usedforsecurity=False).hexdigest()
            Path(directory, key + ".json").write_text(json.dumps([.1, .4]))
            service = self.service(directory)
            service._compute_wave = lambda _path: self.fail("decoded audio")
            self.assertEqual(service.read_cached_waveform(file), [.1, .4])
            self.assertEqual(service.read_cached_waveform("missing.flac"), [])

    def test_waveform_cache_uses_injected_atomic_writer(self):
        writes = []
        service = MediaEnrichmentService(
            "/music", read_lyrics=lambda _path: ([], False),
            average_kbps=lambda *_args: 0, tail_cut=lambda *_args: 0,
            compute_wave=lambda _path: [.2, .8], wave_dir="/unused",
            write_json=lambda path, value: writes.append((path, value)))

        self.assertTrue(service.warm_waveform("song.flac"))
        self.assertEqual([.2, .8], writes[0][1])


class MediaPrefetcherTests(unittest.TestCase):
    def test_item_failure_isolated_and_same_snapshot_retries(self):
        thumbs, waves = [], []
        fail = [True]

        def thumbnail(file):
            thumbs.append(file)
            if file == "one" and fail[0]:
                fail[0] = False
                raise OSError("temporary cache failure")

        prefetcher = MediaPrefetcher(
            warm_thumbnail=thumbnail,
            warm_waveform=lambda file: waves.append(file) or True)
        launch = lambda work: (work() or True)

        self.assertTrue(prefetcher.request(["one", "two"], launch=launch))
        self.assertEqual(["one", "two"], thumbs)
        self.assertFalse(prefetcher.last_result.completed)
        self.assertTrue(prefetcher.request(["one", "two"], launch=launch))
        self.assertTrue(prefetcher.last_result.completed)
        self.assertFalse(prefetcher.request(["one", "two"], launch=launch))
        self.assertEqual(["one", "two", "one", "two"], thumbs)
        self.assertEqual(["one", "two", "one", "two"], waves)

    def test_inflight_snapshot_is_not_launched_twice(self):
        pending = []
        prefetcher = MediaPrefetcher(
            warm_thumbnail=lambda _file: None,
            warm_waveform=lambda _file: True)

        self.assertTrue(prefetcher.request(
            ["one"], launch=lambda work: pending.append(work) or True))
        self.assertFalse(prefetcher.request(
            ["one"], launch=lambda work: self.fail("duplicate launch")))
        pending.pop()()
        self.assertTrue(prefetcher.last_result.completed)


if __name__ == "__main__":
    unittest.main()
