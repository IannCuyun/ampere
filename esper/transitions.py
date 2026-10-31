"""Click-free playback moves at the audio-output boundary.

MPD's software volume is applied before its output buffer.  Riding that volume
around a skip is therefore too early: the skip flushes the faded samples and
can leave the beginning of the next track muted.  PipeWire stream volume is
applied at mix time, which makes it the correct boundary for manual and DJ
moves alike.

The controller is deliberately independent of Qt and MPD.  The application
injects a scheduler, stream resolver and volume setter; tests can exercise the
entire state machine without audio hardware.
"""
from __future__ import annotations

from collections.abc import Callable

FULL_VOLUME = 65536

# MPD reopens its output around a move, so its stream can briefly vanish
# while the ride is still down.  Retry the resolve rather than abandoning
# the ride at zero.
_RESOLVE_RETRIES = 5
_RESOLVE_RETRY_MS = 60


class StreamTransitionController:
    """Serialize short output-volume rides around discontinuous moves."""

    def __init__(
        self,
        *,
        resolve_stream: Callable[[], tuple[int | None, int]],
        set_stream_volume: Callable[[int, int], None],
        schedule: Callable[[int, Callable[[], None]], None],
        run_io: Callable[[Callable[[], object],
                          Callable[[object], None]], bool] | None = None,
        full_volume: int = FULL_VOLUME,
    ) -> None:
        self._resolve_stream = resolve_stream
        self._set_stream_volume = set_stream_volume
        self._schedule = schedule
        self._run_io = run_io or self._run_inline
        self._full_volume = full_volume
        self._busy = False
        self._pending: list[Callable[[], None]] = []

    @staticmethod
    def _run_inline(operation, done) -> bool:
        try:
            result = operation()
        except Exception:
            result = None
        done(result)
        return True

    def _resolve(self, done) -> bool:
        return self._run_io(self._resolve_stream, done)

    def _set_volume(self, stream_id, volume, done) -> bool:
        def operation():
            self._set_stream_volume(stream_id, volume)
            return True

        return self._run_io(operation, done)

    @property
    def busy(self) -> bool:
        return self._busy

    def move(self, action: Callable[[], None], *, smooth: bool = True) -> bool:
        """Run ``action`` with a short mix-time fade.

        Rapid moves are serialized instead of bypassing the fade. Returns
        ``True`` when asynchronous resolution was accepted or a ride queued;
        ``False`` only when smoothing was disabled and the action ran directly.
        """
        if not smooth:
            action()
            return False
        if self._busy:
            self._pending.append(action)
            return True
        self._busy = True

        def finish() -> None:
            self._busy = False
            if self._pending:
                next_action = self._pending.pop(0)
                self.move(next_action)

        def begin(resolved) -> None:
            try:
                stream_id, start_volume = resolved
            except (TypeError, ValueError):
                stream_id, start_volume = None, 0
            if stream_id is None or start_volume <= 0:
                action()
                finish()
                return
            down = [int(start_volume * factor)
                    for factor in (0.55, 0.20, 0.0)]
            up = [int(start_volume * factor)
                  for factor in (0.45, 0.75, 1.0)]

            def restore() -> None:
                def resolved_restore(current):
                    try:
                        current_id, _ = current
                    except (TypeError, ValueError):
                        current_id = None
                    if current_id is None:
                        finish()
                        return
                    self._set_volume(
                        current_id, start_volume, lambda _ok: finish())

                self._resolve(resolved_restore)

            def step(index: int, retries: int = 0) -> None:
                if index < len(down):
                    self._set_volume(
                        stream_id, down[index],
                        lambda ok: (self._schedule(
                            25, lambda: step(index + 1))
                            if ok else restore()))
                    return
                if index == len(down):
                    action()
                    self._schedule(40, lambda: step(index + 1))
                    return
                up_index = index - len(down) - 1

                def resolved_up(current):
                    try:
                        current_id, _ = current
                    except (TypeError, ValueError):
                        current_id = None
                    if current_id is None:
                        if retries < _RESOLVE_RETRIES:
                            self._schedule(
                                _RESOLVE_RETRY_MS,
                                lambda: step(index, retries + 1))
                        else:
                            restore()
                        return

                    def raised(ok):
                        if not ok:
                            restore()
                        elif up_index + 1 < len(up):
                            self._schedule(50, lambda: step(index + 1))
                        else:
                            finish()

                    self._set_volume(current_id, up[up_index], raised)

                self._resolve(resolved_up)

            step(0)

        self._resolve(begin)
        return True

    def heal(self, on_result: Callable[[bool], None] | None = None) -> bool:
        """Raise a stranded stream volume back to full.

        Every ride restores the volume it took, but the process can die
        between the two halves (a kill mid-skip) or the stream can stay
        unresolvable until the ride gives up.  MPD then keeps playing into a
        muted stream: the player looks alive and nothing is audible.  Poll
        this while idle; it only ever writes when the volume is stranded at
        zero, so it can't fight a real user setting.
        """
        if self._busy:
            return False
        self._busy = True
        publish = on_result or (lambda _healed: None)

        def finish(healed):
            self._busy = False
            publish(bool(healed))
            if self._pending:
                next_action = self._pending.pop(0)
                self.move(next_action)

        def resolved(current):
            try:
                stream_id, volume = current
            except (TypeError, ValueError):
                stream_id, volume = None, 1
            if stream_id is None or volume > 0:
                finish(False)
                return

            def restored(ok):
                finish(ok)

            self._set_volume(stream_id, self._full_volume, restored)

        self._resolve(resolved)
        return True
