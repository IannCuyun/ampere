"""Recoverable transaction for inserting a rendered DJ bridge into MPD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


@dataclass(frozen=True)
class BridgeSpliceResult:
    committed: bool
    bridge_id: int = -1


def _song_id(row: Mapping) -> int:
    try:
        return int(row.get("id", -1))
    except (TypeError, ValueError):
        return -1


def _ordered(rows: Iterable[Mapping]) -> list[Mapping]:
    def position(row):
        try:
            return int(row.get("pos", -1))
        except (TypeError, ValueError):
            return -1

    return sorted(rows, key=position)


def splice_bridge(*, initial_queue: Iterable[Mapping], a_id: int, b_id: int,
                  path: str, a_end: float, b_start: float,
                  prior_a: tuple[float, float] | None,
                  prior_b: tuple[float, float] | None,
                  add_once: Callable[[str, int], bool],
                  set_range: Callable[[int, str], bool],
                  delete_once: Callable[[int], bool],
                  read_queue: Callable[[], Iterable[Mapping] | None],
                  ) -> BridgeSpliceResult:
    """Insert and configure one bridge, reconciling a lost ``addid`` reply.

    The queue snapshot—not the command return value—is authoritative. This
    lets an insertion whose reply was lost continue safely while refusing an
    absent or ambiguous candidate. Range writes are absolute/idempotent; the
    bridge deletion is stable-ID and at most once.
    """
    before = _ordered(initial_queue)
    before_ids = {_song_id(row) for row in before}
    b_pos = next((i for i, row in enumerate(before)
                  if _song_id(row) == b_id), -1)
    a_pos = next((i for i, row in enumerate(before)
                  if _song_id(row) == a_id), -1)
    if a_pos < 0 or b_pos != a_pos + 1:
        return BridgeSpliceResult(False)

    # The at-most-once adapter deliberately returns False for both definite
    # and ambiguous failures. Always reconcile: the queue snapshot tells us
    # whether MPD applied the insertion before losing its reply.
    add_once(path, b_pos)

    try:
        after_value = read_queue()
        if after_value is None:
            return BridgeSpliceResult(False)
        after = _ordered(after_value)
    except Exception:
        return BridgeSpliceResult(False)

    candidates = []
    for index, row in enumerate(after):
        sid = _song_id(row)
        if (sid not in before_ids and row.get("file") == path
                and index > 0 and index + 1 < len(after)
                and _song_id(after[index - 1]) == a_id
                and _song_id(after[index + 1]) == b_id):
            candidates.append(sid)
    if len(candidates) != 1:
        return BridgeSpliceResult(False)
    bridge_id = candidates[0]

    def restore(sid: int, prior: tuple[float, float] | None) -> None:
        if prior and (prior[0] or prior[1]):
            end = f"{prior[1]:.2f}" if prior[1] else ""
            set_range(sid, f"{prior[0]:.2f}:{end}")
        else:
            set_range(sid, ":")

    b_end = (prior_b or (0.0, 0.0))[1]
    b_spec = f"{b_start:.2f}:" + (f"{b_end:.2f}" if b_end else "")
    a_entry = (prior_a or (0.0, 0.0))[0]
    try:
        if not set_range(b_id, b_spec):
            raise RuntimeError("B range rejected")
        if not set_range(a_id, f"{a_entry:.2f}:{a_end:.2f}"):
            raise RuntimeError("A range rejected")
    except Exception:
        delete_once(bridge_id)
        restore(a_id, prior_a)
        restore(b_id, prior_b)
        return BridgeSpliceResult(False)

    return BridgeSpliceResult(True, bridge_id)
