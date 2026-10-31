"""Pure transition policy for play counts and long-track resume state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressUpdate:
    file: str
    max_elapsed: float
    duration: float
    count_previous: bool = False
    resume_action: str = ""
    resume_file: str = ""
    resume_position: int = 0
    backward_seek: bool = False


@dataclass(frozen=True)
class ProgressObservation:
    update: ProgressUpdate
    resume_lookup_file: str = ""


def update_progress(*, previous_file: str, previous_max: float,
                    previous_duration: float, current_file: str,
                    elapsed: float, duration: float, song_changed: bool,
                    dj_on: bool, resume_min_seconds: float) -> ProgressUpdate:
    if not song_changed:
        return ProgressUpdate(
            current_file, max(previous_max, elapsed), previous_duration,
            backward_seek=(dj_on and elapsed < previous_max - 1.5))
    count = bool(previous_file and previous_duration > 8
                 and previous_max >= .5 * previous_duration)
    action = ""
    position = 0
    if previous_file and previous_duration >= resume_min_seconds:
        if 60 < previous_max < previous_duration - 60:
            action, position = "set", int(previous_max)
        else:
            action = "delete"
    return ProgressUpdate(
        current_file, elapsed, duration, count_previous=count,
        resume_action=action, resume_file=previous_file,
        resume_position=position)


class ListeningProgressService:
    """Own immediate progress state and describe deferred durable work."""

    def __init__(self, *, resume_min_seconds: float):
        self._resume_min_seconds = float(resume_min_seconds)
        self.file = ""
        self.max_elapsed = 0.0
        self.duration = 0.0

    def observe(self, *, current_file: str, elapsed: float, duration: float,
                song_changed: bool, dj_on: bool) -> ProgressObservation:
        update = update_progress(
            previous_file=self.file, previous_max=self.max_elapsed,
            previous_duration=self.duration, current_file=current_file,
            elapsed=elapsed, duration=duration, song_changed=song_changed,
            dj_on=dj_on, resume_min_seconds=self._resume_min_seconds)
        self.file = update.file
        self.max_elapsed = update.max_elapsed
        self.duration = update.duration

        lookup = (current_file if song_changed and current_file
                  and duration >= self._resume_min_seconds and elapsed < 5
                  else "")
        return ProgressObservation(update=update, resume_lookup_file=lookup)

    def accept_resume(self, position: int) -> None:
        """Advance monotonic progress after Backend accepts a deferred seek."""
        self.max_elapsed = max(self.max_elapsed, float(position))
