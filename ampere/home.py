"""Small immutable presentation projection for Ampere's music-first Home."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class HomeProjection:
    """Project verified Library/Rewind caches into Home's bounded contract."""

    SHELVES = ("history", "arrivals", "loved", "deep", "unfinished")

    @staticmethod
    def unfinished(*, library: Mapping[str, Mapping],
                   resume_positions: Mapping[str, object],
                   last_played: Mapping[str, object],
                   limit: int = 150) -> list[dict]:
        """Build real resumable-record evidence from verified worker data."""
        candidates = []
        for file, raw_position in resume_positions.items():
            song = library.get(file)
            if not isinstance(song, Mapping):
                continue
            try:
                position = int(raw_position)
                duration = float(song.get("duration", 0) or 0)
                played = int(last_played.get(file, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if duration <= 120 or not 60 < position < duration - 60:
                continue
            row = dict(song)
            row["resumePosition"] = position
            row["resumeFraction"] = position / duration
            candidates.append((played, str(file), row))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [row for _, _, row in candidates[:limit]]

    @staticmethod
    def _albums(rows: Sequence[Mapping], limit: int = 3) -> list[dict]:
        result: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for source in rows:
            row = dict(source)
            identity = (
                str(row.get("albumartist") or row.get("artist") or ""),
                str(row.get("album") or row.get("file") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(row)
            if len(result) >= limit:
                break
        return result

    def build(self, *, smart_shelves: Mapping[str, Sequence[Mapping]],
              rewind: Mapping) -> dict:
        stats = rewind.get("stats") if isinstance(rewind, Mapping) else None
        stats = stats if isinstance(stats, Mapping) else {}
        top_artists = stats.get("monthTopArtists", ())
        if not isinstance(top_artists, Sequence) or isinstance(top_artists, str):
            top_artists = ()
        ready = bool(rewind.get("ready")) and all(
            name in smart_shelves for name in self.SHELVES)
        return {
            "ready": ready,
            "metrics": {
                "week": max(0, int(stats.get("week", 0) or 0)),
                "month": max(0, int(stats.get("month", 0) or 0)),
                "artists": max(0, int(stats.get("monthArtists", 0) or 0)),
            },
            "artists": [dict(row) for row in top_artists[:3]
                        if isinstance(row, Mapping)],
            "shelves": {
                name: self._albums(smart_shelves.get(name, ()))
                for name in self.SHELVES
            },
        }


def listening_recommendations(*, library, counts, last_played, liked,
                              disliked, entries, arrivals, now):
    """Bounded, deterministic recommendations from one worker snapshot.

    Calendar rankings use qualified local events. Discovery uses known taste,
    never claims lifetime listening knowledge, and excludes disliked releases.
    """
    from collections import Counter, defaultdict
    from datetime import datetime, timedelta
    from hashlib import sha256
    from pathlib import PurePosixPath

    def number(value):
        try:
            return max(0, int(value))
        except (ValueError, TypeError, OverflowError):
            return 0

    def key(song):
        parent = str(PurePosixPath(song['file']).parent)
        return ('' if parent == '.' else parent, str(song.get('album', '')))

    albums = defaultdict(list)
    hidden = set(disliked)
    likes = set(liked)
    for file, song in library.items():
        if file and not file.startswith('Incoming/'):
            albums[key({**song, 'file': file})].append({**song, 'file': file})
    # An album recommendation should not reintroduce a disliked track.
    albums = {k: rows for k, rows in albums.items()
              if not any(row['file'] in hidden for row in rows)}
    available = {row['file']: row for rows in albums.values() for row in rows}
    events = [(number(t), f) for t, f in entries
              if f in available and 0 < number(t) <= now]
    observed = Counter(f for _, f in events)
    plays = {f: max(number(counts.get(f)), observed[f]) for f in available}
    last = {f: number(last_played.get(f)) for f in available}
    for t, f in events:
        last[f] = max(last[f], t)
    artist_affinity = Counter()
    genre_affinity = Counter()
    for f, row in available.items():
        weight = min(plays[f], 20) + (10 if f in likes else 0)
        artist_affinity[str(row.get('albumartist') or row.get('artist') or '')] += weight
        genre_affinity[str(row.get('genre') or '')] += weight

    def affinity(rows):
        row = rows[0]
        return (artist_affinity[str(row.get('albumartist') or row.get('artist') or '')]
                + genre_affinity.get(str(row.get('genre') or ''), 0) * 0.2
                if row.get('genre') else
                artist_affinity[str(row.get('albumartist') or row.get('artist') or '')])

    def album_plays(rows):
        return sum(plays[r['file']] for r in rows) / len(rows)

    stamp = datetime.fromtimestamp(now)
    end = stamp.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(day=1)
    monthly = Counter(f for t, f in events if start.timestamp() <= t < end.timestamp())
    period = start.strftime('%B %Y')
    used = set()
    sections = [[], []]

    def add(rows, label, reason, section=0, song=False):
        if not rows:
            return
        row = rows[0]
        identity = key(row)
        if identity in used and not song:
            return
        used.add(identity)
        sections[section].append({
            'label': label, 'reason': reason, 'kind': 'song' if song else 'album',
            'file': row['file'], 'path': identity[0], 'album': identity[1],
            'title': str((row.get('title') or row['file']) if song else row.get('album') or 'Unknown album'),
            'artist': str(row.get('albumartist') or row.get('artist') or 'Unknown artist'),
        })

    if monthly:
        f = min(monthly, key=lambda f: (-monthly[f], f))
        add([available[f]], 'Last month’s favorite song',
            f'Most played song · {period}', song=True)
        ranked = sorted(albums.items(), key=lambda item: (
            -sum(monthly[r['file']] for r in item[1]) / len(item[1]), item[0]))
        k, rows = ranked[0]
        # Song and album awards may legitimately identify the same release.
        used.discard(k)
        add(rows, 'Last month’s favorite album',
            f'Highest plays per track · {period}')

    def ordered(candidates, daily=False):
        bucket = int(now // (86400 if daily else 14400))
        return sorted(candidates, key=lambda item: (
            -affinity(item[1]), sha256(f'{bucket}:{item[0]}'.encode()).hexdigest()))

    def fill(candidates, label, reason, section, cap):
        artists = Counter(c['artist'] for c in sections[section])
        for k, rows in candidates:
            if len(sections[section]) >= cap:
                break
            artist = str(rows[0].get('albumartist') or rows[0].get('artist') or 'Unknown artist')
            if k in used or artists[artist] >= 2:
                continue
            add(rows, label, reason, section)
            artists[artist] += 1

    quiet = [(k, rows) for k, rows in albums.items()
             if any(r['file'] in likes for r in rows)
             and max(last[r['file']] for r in rows) < now - 14 * 86400]
    fill(ordered(quiet), 'A favorite you’ve missed',
         'Liked · outside your recent rotation', 0, 3)
    returning = [(k, rows) for k, rows in albums.items() if album_plays(rows) > 0]
    fill(ordered(returning), 'Worth another listen', 'From your listening history', 0, 4)

    recent = {str(r.get('file', '')) for r in arrivals}
    underplayed = [(k, rows) for k, rows in albums.items()
                   if any(r['file'] in recent for r in rows)
                   and album_plays(rows) <= 2 and affinity(rows) > 0]
    fill(ordered(underplayed, True), 'Recent & underplayed',
         'Recently added or updated · little recorded listening', 1, 1)
    unheard = [(k, rows) for k, rows in albums.items()
               if all(plays[r['file']] == 0 for r in rows) and affinity(rows) > 0]
    fill(ordered(unheard, True), 'An unheard album for you',
         'No recorded plays · connected to music you enjoy', 1, 4)
    # Cold start: offer honest library exploration without fabricated affinity.
    if not any(sections):
        fill(ordered(list(albums.items()), True), 'Explore your library',
             'Your listening will shape future recommendations', 1, 4)
    return [{'title': title, 'cards': cards} for title, cards in zip(
        ('Your favorites, revisited', 'Something you haven’t heard enough'), sections) if cards]
