"""Bounded cached presentation model for Discover's Needle Drop room."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class DiscoverProjection:
    """Choose one honest album entrance for each approved discovery lane."""

    LANES = (
        {
            "key": "loved",
            "ordinal": "01",
            "title": "Bring something back",
            "shortTitle": "Forgotten",
            "subtitle": "Loved, then quiet",
            "eyebrow": "DISCOVER / A FAVORITE OUT OF ROTATION",
            "reason": (
                "A record you marked as a favorite has slipped out of "
                "rotation."
            ),
        },
        {
            "key": "arrivals",
            "ordinal": "02",
            "title": "Open a recent arrival",
            "shortTitle": "New",
            "subtitle": "Waiting for a first spin",
            "eyebrow": "DISCOVER / RECENTLY ADDED",
            "reason": (
                "This record recently entered your archive and is still "
                "waiting for a proper listen."
            ),
        },
        {
            "key": "deep",
            "ordinal": "03",
            "title": "Go deeper",
            "shortTitle": "Unheard",
            "subtitle": "Unplayed from familiar rooms",
            "eyebrow": "DISCOVER / DEEP IN A FAMILIAR ROOM",
            "reason": (
                "This is an overlooked record from a part of the archive "
                "you already return to."
            ),
        },
    )

    @staticmethod
    def _identity(row: Mapping) -> tuple[str, str]:
        file = str(row.get("file") or "")
        folder = file.rsplit("/", 1)[0] if "/" in file else ""
        album = str(row.get("album") or "").strip()
        # Ampere's locked release identity is exactly (folder, album tag).
        # Track-level or album-level artist fields are attribution, not
        # membership, and must not merge or split releases.
        # A tagged release may live directly at the MPD root, where the
        # folder component is the empty string. Untagged files are not an
        # album and therefore remain explicit single-file identities.
        return (folder, album) if album else (file, "")

    @classmethod
    def _release_files(cls, entry: Mapping, library: Mapping) -> list[str]:
        identity = cls._identity(entry)
        files = [
            str(file)
            for file, song in library.items()
            if isinstance(song, Mapping) and cls._identity(song) == identity
        ]
        selected = str(entry.get("file") or "")
        # Smart shelves and the library snapshot are published from one
        # verified generation. The fallback preserves an honest explicit
        # single-file action if a defensive harness supplies them separately.
        return files or ([selected] if selected else [])

    @classmethod
    def _entry(cls, rows: Sequence[Mapping], seen: set[tuple[str, str]]) -> dict:
        candidates = [dict(row) for row in rows if isinstance(row, Mapping)
                      and row.get("file")]
        if not candidates:
            return {}
        for row in candidates:
            identity = cls._identity(row)
            if identity not in seen:
                seen.add(identity)
                return row
        # Do not present the same album as several independent discovery
        # choices. The lane remains explicitly empty until a distinct record
        # enters its verified shelf evidence.
        return {}

    def build(self, smart_shelves: Mapping[str, Sequence[Mapping]], *,
              library: Mapping[str, Mapping] | None = None) -> dict:
        """Project only cached shelf rows; never read MPD, Qt, or the filesystem."""
        library = library or {}
        ready = all(lane["key"] in smart_shelves for lane in self.LANES)
        seen: set[tuple[str, str]] = set()
        lanes = []
        for spec in self.LANES:
            source = smart_shelves.get(spec["key"], ())
            rows = (source if isinstance(source, Sequence)
                    and not isinstance(source, (str, bytes)) else ())
            lane = dict(spec)
            lane["count"] = len(rows)
            lane["entry"] = self._entry(rows, seen)
            if lane["entry"]:
                lane["entry"]["files"] = self._release_files(
                    lane["entry"], library)
            lanes.append(lane)
        return {"ready": ready, "lanes": lanes}
