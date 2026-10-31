import unittest

from ampere.mpris import MprisService, PLAYER_IFACE, ROOT_IFACE


class BackendStub:
    def __init__(self):
        self.calls = []

    def requestLoopStatus(self, mode):
        self.calls.append(mode)

    def requestTransport(self, mode):
        self.calls.append(mode)


class MprisPropertyTests(unittest.TestCase):
    def test_explicit_transport_does_not_toggle_from_cached_state(self):
        service = type("Service", (), {"backend": BackendStub()})()

        MprisService.play(service)
        MprisService.pause(service)

        self.assertEqual(["play", "pause"], service.backend.calls)

    def test_loop_status_sets_repeat_and_single_together(self):
        service = type("Service", (), {"backend": BackendStub()})()

        MprisService.set_property(service, PLAYER_IFACE, "LoopStatus", "Track")
        self.assertEqual(service.backend.calls, ["Track"])

        service.backend.calls.clear()
        MprisService.set_property(service, PLAYER_IFACE, "LoopStatus", "Playlist")
        self.assertEqual(service.backend.calls, ["Playlist"])

        service.backend.calls.clear()
        MprisService.set_property(service, PLAYER_IFACE, "LoopStatus", "None")
        self.assertEqual(service.backend.calls, ["None"])

    def test_root_does_not_advertise_unsupported_open_uri(self):
        service = type("Service", (), {"backend": BackendStub()})()
        self.assertEqual(
            MprisService.get_property(service, ROOT_IFACE, "SupportedUriSchemes"), [])
        self.assertEqual(
            MprisService.get_property(service, ROOT_IFACE, "SupportedMimeTypes"), [])


if __name__ == "__main__":
    unittest.main()
