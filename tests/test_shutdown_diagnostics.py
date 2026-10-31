import threading
import unittest

from ampere.shutdown_diagnostics import describe_object, format_snapshot


class Part:
    def __init__(self, *, buffer=None, raw=None, sock=None, closed=False):
        self.buffer = buffer
        self.raw = raw
        self._sock = sock
        self.closed = closed
        self.name = -1


class Client:
    _rbfile = object()
    _wfile = None
    _sock = object()


class ShutdownDiagnosticTests(unittest.TestCase):
    def test_describes_text_wrapper_chain_without_mutation(self):
        socket = Part(closed=False)
        raw = Part(sock=socket)
        buffer = Part(raw=raw)
        wrapper = Part(buffer=buffer)

        description = describe_object(wrapper)

        self.assertIn("object=", description)
        self.assertIn("buffer=", description)
        self.assertIn("raw=", description)
        self.assertIn("socket=", description)
        self.assertIn("closed=False", description)

    def test_snapshot_reports_open_client_parts_and_named_threads(self):
        text = format_snapshot(
            "before-close", [Client()], [threading.current_thread()])
        self.assertIn("before-close", text)
        self.assertIn("Client:_rbfile,_sock", text)
        self.assertIn(threading.current_thread().name, text)


if __name__ == "__main__":
    unittest.main()
