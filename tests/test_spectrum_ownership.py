import unittest
import threading

from ampere.mpdclient import Backend


class TapStub:
    def __init__(self):
        self.stops = 0

    def stop(self):
        self.stops += 1


class SignalStub:
    def __init__(self):
        self.frames = []

    def emit(self, frame):
        self.frames.append(frame)


class SpectrumOwnershipTests(unittest.TestCase):
    def test_capture_frames_are_latest_value_coalesced_before_qt_publication(self):
        backend = type("BackendStub", (), {})()
        backend._spectrum_frame_lock = threading.Lock()
        backend._spectrum_latest = None
        backend.spectrumFrame = SignalStub()

        Backend._capture_spectrum_frame(backend, [0.1, 0.2])
        Backend._capture_spectrum_frame(backend, [0.8, 0.9])
        self.assertEqual([], backend.spectrumFrame.frames)

        Backend._publish_spectrum_frame(backend)
        Backend._publish_spectrum_frame(backend)

        self.assertEqual([[0.8, 0.9]], backend.spectrumFrame.frames)

    def test_one_view_cannot_stop_another_views_tap(self):
        backend = type("BackendStub", (), {})()
        backend._spec = TapStub()
        backend._spec_owners = {"now", "ambient"}

        Backend.stopSpectrum(backend, "now")
        self.assertIsNotNone(backend._spec)
        self.assertEqual(backend._spec.stops, 0)

        Backend.stopSpectrum(backend, "ambient")
        self.assertIsNone(backend._spec)


if __name__ == "__main__":
    unittest.main()
