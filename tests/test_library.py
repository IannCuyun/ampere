import unittest
import contextlib
from pathlib import Path
from unittest.mock import patch

from ampere.library import (
    LibraryIndexer, LibraryPathResult, LibraryRepository, LibraryUpdateController,
    LibraryUpdateResult, normalize_song,
)
from ampere.mpdclient import Backend
from ampere.search import SearchCatalog


class LibraryRepositoryTests(unittest.TestCase):
    def test_normalize_song_has_a_stable_shape_and_safe_fallbacks(self):
        result = normalize_song({"file": "Folk/Artist/Track.flac",
                                 "albumartist": ["Artist"],
                                 "duration": "bad", "range": "12.5-40",
                                 "date": ["2024-10-04"],
                                 "genre": [" Dark Folk ",
                                           "dark folk; Americana "]})
        self.assertEqual("Track", result["title"])
        self.assertEqual("Artist", result["artist"])
        self.assertEqual("Artist", result["albumartist"])
        self.assertEqual(0.0, result["duration"])
        self.assertEqual((12.5, 40.0), (result["rangeStart"], result["rangeEnd"]))
        self.assertEqual("2024", result["year"])
        self.assertEqual(["Dark Folk", "Americana"], result["genres"])
        self.assertEqual("Dark Folk", result["genre"])

    def test_attribution_names_are_never_normalized_as_genres(self):
        result = normalize_song({
            "file": "Classical/Carmina Burana.flac",
            "artist": ["Carl Orff", "Boston Pops Orchestra"],
            "albumartist": ["Carl Orff"],
            "composer": ["Carl Orff"],
            "conductor": ["John Williams"],
            "genre": ["Carl Orff", " john   williams ", "Classical"],
        })

        self.assertEqual("Carl Orff, Boston Pops Orchestra", result["artist"])
        self.assertEqual(
            ["Carl Orff", "Boston Pops Orchestra", "John Williams"],
            result["creditNames"])
        self.assertEqual(["Classical"], result["genres"])
        self.assertEqual("Classical", result["genre"])

    def test_combined_display_credit_contributors_are_not_genres(self):
        result = normalize_song({
            "file": "Classical/Edward Elgar/Cello Concerto.flac",
            "artist": "Edward Elgar, Sheku Kanneh-Mason, London Symphony Orchestra",
            "albumartist": "Sheku Kanneh-Mason, London Symphony Orchestra",
            "genre": ["Classical", "Edward Elgar"],
        })

        self.assertEqual(
            "Edward Elgar, Sheku Kanneh-Mason, London Symphony Orchestra",
            result["artist"])
        self.assertIn("Edward Elgar", result["creditNames"])
        self.assertIn("Sheku Kanneh-Mason", result["creditNames"])
        self.assertEqual(["Classical"], result["genres"])

    def test_replace_publishes_coherent_lookup_and_search_snapshots(self):
        repository = LibraryRepository()
        generation = repository.replace([
            {"file": "Rap/Artist/Album/01.flac", "title": "Signal",
             "artist": "Artist", "album": "Album"},
            {"file": "Rap/Artist/Album/.sync-conflict-01.flac", "title": "Copy"},
        ])
        self.assertEqual(1, generation)
        self.assertEqual(1, repository.generation)
        self.assertEqual(["Rap/Artist/Album/01.flac"], list(repository.by_file))
        self.assertEqual("Signal", repository.search_index[0]["song"]["title"])
        self.assertEqual(["Rap/Artist/Album/01.flac"],
                         repository.files_under("Rap/Artist"))
        self.assertEqual([], repository.files_under("Rap/Other"))

    def test_browse_and_discography_are_display_ready(self):
        repository = LibraryRepository()
        repository.replace([
            {"file": "Rap/Travis/Rodeo/01.flac", "title": "One",
             "artist": "Travis", "album": "Rodeo"},
            {"file": "Rap/Travis/Utopia/01.flac", "title": "Two",
             "artist": "Travis", "album": "Utopia"},
        ])
        self.assertEqual(["Rap"], [entry["name"]
                                   for entry in repository.browse("")])
        self.assertEqual(["Travis"], [entry["name"]
                                      for entry in repository.browse("Rap")])
        self.assertEqual("Rap/Travis/Rodeo/01.flac",
                         repository.browse("")[0]["cover"])
        self.assertEqual("Rap/Travis/Rodeo/01.flac",
                         repository.browse("Rap")[0]["cover"])
        albums = repository.artist_discography(list(repository.by_file), {
            "Rap/Travis/Utopia/01.flac": 8,
        })
        self.assertEqual(["Utopia", "Rodeo"], [album["album"] for album in albums])
        self.assertEqual("Rap/Travis", repository.artist_path(
            "Rap/Travis/Utopia/01.flac", "Travis"))

    def test_artist_membership_merges_aliases_and_projects_collaborations(self):
        repository = LibraryRepository()
        repository.replace([
            {"file": "Rap/Kanye/solo.flac", "title": "Solo",
             "artist": "Kanye West", "albumartist": "Kanye West",
             "album": "Solo Album"},
            {"file": "Rap/Ye/alias.flac", "title": "Alias",
             "artist": "Ye", "albumartist": "Ye", "album": "BULLY"},
            {"file": "Rap/Watch/joint.flac", "title": "Joint",
             "artist": "Jay Z, Kanye West", "albumartist": "Jay Z",
             "album": "Watch the Throne"},
            {"file": "Rap/Other/no.flac", "title": "No",
             "artist": "Other", "albumartist": "Other", "album": "No"},
        ])

        kanye = repository.artist_files("Kanye West")
        ye = repository.artist_files("Ye")
        jay_z = repository.artist_files("Jay Z")

        self.assertEqual([
            "Rap/Kanye/solo.flac", "Rap/Ye/alias.flac",
            "Rap/Watch/joint.flac",
        ], kanye)
        self.assertEqual(kanye, ye)
        self.assertEqual(["Rap/Watch/joint.flac"], jay_z)
        self.assertEqual(jay_z, repository.artist_files("Jay Z, Kanye West"))
        self.assertEqual(len(kanye), len(set(kanye)))

    def test_combined_credit_navigation_resolves_first_contributor(self):
        backend = type("BackendHarness", (), {})()

        self.assertEqual(
            "Jay Z",
            Backend.canonicalArtistName(backend, "Jay Z, Kanye West"),
        )
        self.assertEqual(
            "Kanye West",
            Backend.canonicalArtistName(backend, "Ye; Jay Z"),
        )

    def test_path_snapshot_distinguishes_empty_and_preserves_on_failure(self):
        repository = LibraryRepository()
        verified = repository.publish_path("Rap", [
            {"directory": "Rap/Artist"},
            {"file": "Rap/Artist/one.flac"},
        ])
        unavailable = repository.publish_path("Rap", None)
        malformed = repository.publish_path("Rap", [{"file": "new.flac"}, 7])
        empty = repository.publish_path("Empty", [])

        self.assertTrue(verified.success)
        self.assertEqual(("Rap/Artist/one.flac",), verified.files)
        self.assertFalse(unavailable.success)
        self.assertEqual(verified.files, unavailable.files)
        self.assertFalse(malformed.success)
        self.assertEqual(verified.files, malformed.files)
        self.assertTrue(empty.success)
        self.assertEqual((), empty.files)

    def test_stats_snapshot_retains_verified_totals_through_failure(self):
        repository = LibraryRepository()
        verified = repository.publish_stats({
            "songs": "42", "albums": "7", "artists": "5",
            "db_playtime": "7200",
        })
        unavailable = repository.publish_stats(None)
        malformed = repository.publish_stats({
            "songs": "broken", "albums": "0", "artists": "0",
            "db_playtime": "0",
        })

        self.assertTrue(verified.success)
        self.assertEqual((42, 7, 5, 2.0), (
            verified.songs, verified.albums, verified.artists,
            verified.playtime_hours))
        self.assertFalse(unavailable.success)
        self.assertFalse(malformed.success)
        self.assertEqual((42, 7), (unavailable.songs, malformed.albums))

    def test_valid_zero_stats_replace_prior_snapshot(self):
        repository = LibraryRepository()
        repository.publish_stats({
            "songs": "42", "albums": "7", "artists": "5",
            "db_playtime": "7200",
        })

        empty = repository.publish_stats({
            "songs": "0", "albums": "0", "artists": "0",
            "db_playtime": "0",
        })

        self.assertTrue(empty.success)
        self.assertEqual((0, 0, 0, 0.0), (
            empty.songs, empty.albums, empty.artists,
            empty.playtime_hours))


class _Signal:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class LibraryStatsPublicationTests(unittest.TestCase):
    def test_backend_returns_last_verified_totals_without_mpd_io(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.publish_stats({
            "songs": "42", "albums": "7", "artists": "5",
            "db_playtime": "7200",
        })
        backend._call = lambda *_args, **_kwargs: self.fail(
            "cached totals must not read MPD")

        self.assertEqual({
            "songs": 42, "albums": 7, "artists": 5,
            "genres": 0,
            "playtimeHours": 2.0,
        }, Backend.stats(backend))

    def test_backend_stats_uses_canonical_artist_projection_when_ready(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.publish_stats({
            "songs": "42", "albums": "7", "artists": "5",
            "db_playtime": "7200",
        })
        backend._library_directory = {
            "artists": ({"name": "Jay Z"}, {"name": "Kanye West"}),
            "genres": (),
        }

        self.assertEqual(2, Backend.stats(backend)["artists"])


class LibraryPresentationTests(unittest.TestCase):
    def test_album_and_artist_views_use_the_verified_snapshot_only(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.replace([
            {"file": "Rap/Artist/Album/01.flac", "title": "Signal",
             "artist": "Artist", "album": "Album", "date": "2024-10-04"},
            {"file": "Rap/Artist/Favorite/01.flac", "title": "Loved",
             "artist": "Artist", "album": "Favorite"},
        ])
        backend._library_playcounts = {
            "Rap/Artist/Favorite/01.flac": 8,
        }
        backend._playcounts = lambda: self.fail("read play counts")
        backend._path_files = lambda *_args, **_kwargs: self.fail("queried MPD")

        album = Backend.albumInfo(backend, "Rap/Artist/Album")
        discography = Backend.artistDiscography(backend, "Artist")

        self.assertEqual("2024", album["year"])
        self.assertEqual(["Signal"], [track["title"] for track in album["tracks"]])
        self.assertEqual(["Favorite", "Album"],
                         [entry["album"] for entry in discography])

    def test_album_info_filters_shared_folder_by_selected_album_tag(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library.replace([
            {"file": "Metal/Signs/death-whistle.flac",
             "title": "Death Whistle", "album": "Absolvere",
             "artist": "Signs", "albumartist": "Signs"},
            {"file": "Metal/Signs/iwontletyoudie.flac",
             "title": "IWONTLETYOUDIE",
             "album": "Amongst the Low & Empty",
             "artist": "Signs", "albumartist": "Signs"},
        ])

        album = Backend.albumInfo(backend, "Metal/Signs", "Absolvere")

        self.assertEqual("Absolvere", album["album"])
        self.assertEqual(["Death Whistle"],
                         [track["title"] for track in album["tracks"]])


class LibraryPathPublicationTests(unittest.TestCase):
    def harness(self):
        backend = type("BackendHarness", (), {})()
        backend._library = LibraryRepository()
        backend._library_read_failed = False
        backend.errorOccurred = _Signal()
        backend.rows = {
            "listall": [{"file": "Rap/Artist/one.flac"}],
        }
        backend._call = lambda command, _path, default=None: \
            backend.rows.get(command, default)
        backend._report_library_read = lambda success: \
            Backend._report_library_read(backend, success)
        return backend

    def test_browse_reads_only_the_verified_index_hierarchy(self):
        backend = self.harness()
        backend._library.replace([
            {"file": "Rap/Artist/Album/01.flac", "title": "One"},
            {"file": "Rap/Artist/Album/02.flac", "title": "Two"},
            {"file": "Jazz/Loose.flac", "title": "Loose"},
        ])
        backend._call = lambda *_args, **_kwargs: self.fail("queried MPD")

        root = Backend.browse(backend, "")
        artist = Backend.browse(backend, "/Rap/Artist/")
        album = Backend.browse(backend, "Rap/Artist/Album")

        self.assertEqual(["Rap", "Jazz"], [row["name"] for row in root])
        self.assertEqual(["Album"], [row["name"] for row in artist])
        self.assertEqual(["One", "Two"], [row["title"] for row in album])

    def test_path_slots_route_to_async_planning_without_inline_mutation(self):
        backend = type("BackendHarness", (), {})()
        backend.actions = []
        backend._request_path_action = lambda action, path: \
            backend.actions.append((action, path))

        Backend.queuePath(backend, "Rap")
        Backend.playPath(backend, "Rap")
        Backend.shufflePath(backend, "Rap")
        Backend.shufflePathNow(backend, "Rap")

        self.assertEqual([
            ("queue", "Rap"), ("play", "Rap"),
            ("shuffle", "Rap"), ("shuffle-now", "Rap"),
        ], backend.actions)

    def test_queue_files_keeps_explicit_album_membership(self):
        backend = type("BackendHarness", (), {})()
        appended = []
        backend._queued_notice = lambda *_a, **_k: None
        backend._request_queue_intent = lambda kind, request, **_kw: (
            appended.append((kind, request)) or True)

        result = Backend.queueFiles(backend, ["album/one.flac",
                                              "album/two.flac"])

        self.assertTrue(result)
        self.assertEqual("append", appended[0][0])
        self.assertEqual(
            ("album/one.flac", "album/two.flac"),
            appended[0][1]["files"])

    def test_queue_album_marks_the_only_disliked_admission_exception(self):
        backend = type("BackendHarness", (), {})()
        appended = []
        backend._queued_notice = lambda *_a, **_k: None
        backend._request_queue_intent = lambda kind, request, **_kw: (
            appended.append((kind, request)) or True)

        result = Backend.queueAlbum(
            backend, ["album/one.flac", "album/disliked.flac"])

        self.assertTrue(result)
        self.assertEqual("append", appended[0][0])
        self.assertEqual(
            ("album/one.flac", "album/disliked.flac"),
            appended[0][1]["files"])
        self.assertEqual("album", appended[0][1]["source"])
        self.assertTrue(appended[0][1]["allowDisliked"])

    def test_album_room_routes_only_parent_album_queue_through_exception(self):
        source = (Path(__file__).resolve().parents[1]
                  / "qml" / "AlbumView.qml").read_text()

        self.assertIn('backend.queueAlbum(view.files)', source)
        self.assertIn('backend.playAlbum(view.files, 0)', source)
        self.assertIn('backend.playFilesShuffled(view.files)', source)

    def test_path_action_worker_uses_owned_client(self):
        backend = type("BackendHarness", (), {})()
        backend._path_action_busy = False
        backend._path_action_pending = None
        backend._path_action_generation = 0
        backend._workers = object()
        emitted = []
        backend._pathActionReady = type("Signal", (), {
            "emit": lambda self, payload: emitted.append(payload),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)
        calls = []
        client = type("Client", (), {
            "listall": lambda self, path: (
                calls.append(path) or [{"file": path + "/one.flac"}]),
        })()

        @contextlib.contextmanager
        def scoped_client(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scoped_client):
            self.assertTrue(Backend._request_path_action(
                backend, "play", "Rap"))

        self.assertEqual(["Rap"], calls)
        self.assertTrue(emitted[0]["result"].success)
        self.assertEqual(("Rap/one.flac",), emitted[0]["result"].files)

    def test_unavailable_path_result_never_reaches_queue_mutation(self):
        backend = self.harness()
        backend._path_action_generation = 3
        backend._path_action_busy = True
        backend._path_action_pending = None
        backend._launch_pending_path_action = lambda: False
        backend._apply_path_action = lambda *_args: self.fail(
            "unverified path must not mutate queue")

        Backend._on_path_action_ready(backend, {
            "generation": 3, "action": "play", "path": "Rap",
            "result": LibraryPathResult(False),
        })

        self.assertFalse(backend._path_action_busy)
        self.assertEqual(1, len(backend.errorOccurred.messages))

    def test_superseded_path_result_launches_only_latest_request(self):
        backend = type("BackendHarness", (), {})()
        backend._path_action_busy = True
        backend._path_action_pending = None
        backend._path_action_generation = 4

        self.assertTrue(Backend._request_path_action(
            backend, "play", "Rap"))
        launched = []
        backend._request_path_action = lambda *request: \
            launched.append(request) or True
        backend._launch_pending_path_action = lambda: \
            Backend._launch_pending_path_action(backend)
        backend._apply_path_action = lambda *_args: self.fail(
            "superseded result must not apply")

        Backend._on_path_action_ready(backend, {
            "generation": 4, "action": "queue", "path": "Jazz",
            "result": LibraryPathResult(True, ("Jazz/old.flac",)),
        })

        self.assertEqual([("play", "Rap")], launched)

    def test_verified_current_path_publishes_then_applies(self):
        backend = self.harness()
        backend._path_action_generation = 2
        backend._path_action_busy = True
        backend._path_action_pending = None
        backend._launch_pending_path_action = lambda: False
        applied = []
        backend._apply_path_action = lambda action, path, files: \
            applied.append((action, path, list(files))) or True

        Backend._on_path_action_ready(backend, {
            "generation": 2, "action": "queue", "path": "Rap",
            "result": LibraryPathResult(True, ("Rap/new.flac",)),
        })

        self.assertEqual(
            [("queue", "Rap", ["Rap/new.flac"])], applied)
        self.assertEqual(
            ("Rap/new.flac",),
            backend._library.publish_path("Rap", None).files)


class LibraryUpdateControllerTests(unittest.TestCase):
    def test_preflight_unavailable_or_running_never_dispatches(self):
        writes = []
        unavailable = LibraryUpdateController(
            read=lambda *_args, **_kwargs: None,
            write_once=lambda *args, **kwargs: writes.append((args, kwargs)))
        running = LibraryUpdateController(
            read=lambda *_args, **_kwargs: {"updating_db": "7"},
            write_once=lambda *args, **kwargs: writes.append((args, kwargs)))

        self.assertFalse(unavailable.request().success)
        self.assertFalse(unavailable.request().confirmed)
        self.assertTrue(running.request().already_running)
        self.assertEqual([], writes)

    def test_lost_reply_reconciles_started_job_without_replay(self):
        statuses = iter(({}, {"updating_db": "9"}))
        writes = []
        controller = LibraryUpdateController(
            read=lambda *_args, **_kwargs: next(statuses),
            write_once=lambda *args, **kwargs: (
                writes.append((args, kwargs)) or False))

        result = controller.request("Artist")

        self.assertTrue(result.success)
        self.assertTrue(result.started)
        self.assertEqual([(("update", "Artist"), {"quiet": True})], writes)

    def test_verified_rejection_is_distinct_from_unconfirmed_reply(self):
        statuses = iter(({}, {}))
        controller = LibraryUpdateController(
            read=lambda *_args, **_kwargs: next(statuses),
            write_once=lambda *_args, **_kwargs: False)

        result = controller.request()

        self.assertFalse(result.success)
        self.assertTrue(result.confirmed)

    def test_backend_update_action_reports_running_and_unconfirmed_states(self):
        backend = type("BackendHarness", (), {})()
        backend.errorOccurred = _Signal()
        backend._database_update_busy = True

        Backend._on_database_update_ready(
            backend, LibraryUpdateResult(True, already_running=True))
        Backend._on_database_update_ready(
            backend, LibraryUpdateResult(False, confirmed=False))

        self.assertIn("already running", backend.errorOccurred.messages[0])
        self.assertIn("could not be confirmed", backend.errorOccurred.messages[1])

    def test_backend_update_action_admits_only_one_worker(self):
        backend = type("BackendHarness", (), {})()
        backend._database_update_busy = False
        launched = []
        backend._start_worker = lambda work, **_kwargs: (
            launched.append(work) or True)

        self.assertTrue(Backend.updateDatabase(backend))
        self.assertFalse(Backend.updateDatabase(backend))
        self.assertEqual(1, len(launched))

    def test_backend_update_worker_uses_one_owned_client(self):
        backend = type("BackendHarness", (), {})()
        backend._database_update_busy = False
        backend._workers = object()
        emitted = []
        backend._databaseUpdateReady = type("Signal", (), {
            "emit": lambda self, result: emitted.append(result),
        })()
        backend._start_worker = lambda work, **_kwargs: (work() or True)

        class Client:
            def __init__(self):
                self.calls = []

            def status(self):
                self.calls.append("status")
                return {}

            def update(self):
                self.calls.append("update")

        client = Client()

        @contextlib.contextmanager
        def scope(*_args, **_kwargs):
            yield client

        with patch("ampere.mpdclient.temporary_mpd_client", scope):
            self.assertTrue(Backend.updateDatabase(backend))

        self.assertEqual(["status", "update"], client.calls)
        self.assertTrue(emitted[0].started)


class LibraryIndexerTests(unittest.TestCase):
    class Client:
        def __init__(self, songs=None, error=None):
            self.songs = songs
            self.error = error

        def listallinfo(self):
            if self.error:
                raise self.error
            return self.songs

    def indexer(self, repository, catalog, client):
        return LibraryIndexer(
            repository, catalog,
            client_scope=lambda: contextlib.nullcontext(client))

    def test_success_publishes_one_coherent_filtered_generation(self):
        repository, catalog = LibraryRepository(), SearchCatalog()
        result = self.indexer(repository, catalog, self.Client([
            {"file": "Rap/Artist/one.flac", "title": "One"},
            {"file": "Rap/Artist/.sync-conflict-copy.flac", "title": "Copy"},
        ])).rebuild()

        self.assertTrue(result.success)
        self.assertEqual((1, 1, 1), (
            result.generation, result.total, len(result.search_index)))
        self.assertEqual("One", catalog.query("one")["hits"][0]["title"])

    def test_failure_preserves_the_last_published_generation(self):
        repository, catalog = LibraryRepository(), SearchCatalog()
        repository.replace([
            {"file": "Rap/existing.flac", "title": "Existing"}])
        catalog.replace_index(repository.search_index)

        result = self.indexer(
            repository, catalog,
            self.Client(error=OSError("MPD unavailable"))).rebuild()

        self.assertFalse(result.success)
        self.assertEqual("OSError", result.error)
        self.assertEqual(1, repository.generation)
        self.assertEqual("Existing",
                         catalog.query("existing")["hits"][0]["title"])
        self.assertEqual(["Rap"], [row["name"]
                                   for row in repository.browse("")])

    def test_none_snapshot_is_a_failure_not_an_empty_publication(self):
        repository, catalog = LibraryRepository(), SearchCatalog()
        result = self.indexer(
            repository, catalog, self.Client(songs=None)).rebuild()
        self.assertFalse(result.success)
        self.assertEqual(0, repository.generation)


if __name__ == "__main__":
    unittest.main()
