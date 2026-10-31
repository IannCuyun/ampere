import unittest

from ampere.transitions import StreamTransitionController


class StreamTransitionControllerTests(unittest.TestCase):
    def setUp(self):
        self.volume = 1000
        self.writes = []
        self.scheduled = []
        self.actions = []
        self.controller = StreamTransitionController(
            resolve_stream=lambda: (7, self.volume),
            set_stream_volume=lambda stream, volume: self.writes.append(
                (stream, volume)),
            schedule=lambda delay, callback: self.scheduled.append(
                (delay, callback)),
        )

    def drain(self):
        while self.scheduled:
            _delay, callback = self.scheduled.pop(0)
            callback()

    def test_fades_the_output_stream_and_restores_exact_volume(self):
        self.assertTrue(self.controller.move(lambda: self.actions.append("next")))
        self.drain()
        self.assertEqual(self.actions, ["next"])
        self.assertEqual([volume for _stream, volume in self.writes],
                         [550, 200, 0, 450, 750, 1000])
        self.assertFalse(self.controller.busy)

    def test_rapid_moves_are_serialized_instead_of_hard_cutting(self):
        self.controller.move(lambda: self.actions.append("first"))
        self.controller.move(lambda: self.actions.append("second"))
        self.assertEqual(self.actions, [])
        self.drain()
        self.assertEqual(self.actions, ["first", "second"])

    def test_a_stream_that_reappears_late_still_gets_its_volume_back(self):
        # MPD reopens its output around the move, so the stream can be
        # missing for a moment while the ride is at zero.
        misses = [2]

        def resolve():
            if self.writes and misses[0] > 0:
                misses[0] -= 1
                return None, 0
            return 7, self.volume

        self.controller = StreamTransitionController(
            resolve_stream=resolve,
            set_stream_volume=lambda stream, volume: self.writes.append(
                (stream, volume)),
            schedule=lambda delay, callback: self.scheduled.append(
                (delay, callback)),
        )
        self.controller.move(lambda: self.actions.append("next"))
        self.drain()
        self.assertEqual([volume for _stream, volume in self.writes][-1], 1000)
        self.assertFalse(self.controller.busy)

    def test_a_stream_that_never_returns_is_restored_not_left_muted(self):
        resolved = [(7, self.volume)]
        self.controller = StreamTransitionController(
            resolve_stream=lambda: resolved[0],
            set_stream_volume=lambda stream, volume: self.writes.append(
                (stream, volume)),
            schedule=lambda delay, callback: self.scheduled.append(
                (delay, callback)),
        )
        self.controller.move(lambda: resolved.__setitem__(0, (None, 0)))
        self.scheduled and self.drain()
        # gives up on the ride, but not with the stream still at zero
        resolved[0] = (7, 0)
        self.assertTrue(self.controller.heal())
        self.assertEqual(self.writes[-1], (7, 65536))

    def test_heal_leaves_a_healthy_stream_alone(self):
        healed = []
        self.assertTrue(self.controller.heal(healed.append))
        self.assertEqual([False], healed)
        self.assertEqual(self.writes, [])

    def test_heal_never_fights_a_ride_in_progress(self):
        self.controller.move(lambda: self.actions.append("next"))
        self.assertTrue(self.controller.busy)
        self.assertFalse(self.controller.heal())

    def test_injected_io_runner_owns_every_discovery_and_write(self):
        operations = []

        def run_io(operation, done):
            operations.append((operation, done))
            return True

        controller = StreamTransitionController(
            resolve_stream=lambda: (7, 1000),
            set_stream_volume=lambda *_args: None,
            schedule=lambda _delay, callback: callback(),
            run_io=run_io,
        )
        moved = []

        self.assertTrue(controller.move(lambda: moved.append(True)))
        self.assertEqual([], moved)
        while operations:
            operation, done = operations.pop(0)
            done(operation())

        self.assertEqual([True], moved)
        self.assertFalse(controller.busy)

    def test_move_queued_during_async_heal_runs_after_guard_finishes(self):
        operations = []
        actions = []

        def run_io(operation, done):
            operations.append((operation, done))
            return True

        controller = StreamTransitionController(
            resolve_stream=lambda: (7, 1000),
            set_stream_volume=lambda *_args: None,
            schedule=lambda _delay, callback: callback(),
            run_io=run_io,
        )
        controller.heal()
        controller.move(lambda: actions.append("next"))
        while operations:
            operation, done = operations.pop(0)
            done(operation())

        self.assertEqual(["next"], actions)
        self.assertFalse(controller.busy)

    def test_missing_stream_falls_back_to_the_requested_action(self):
        controller = StreamTransitionController(
            resolve_stream=lambda: (None, 0),
            set_stream_volume=lambda *_: None,
            schedule=lambda *_: None,
        )
        called = []
        self.assertTrue(controller.move(lambda: called.append(True)))
        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()
