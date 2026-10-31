"""Framework-independent listening-history analytics for Rewind."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence


class RewindService:
    """Build Rewind's stable presentation models from explicit snapshots."""

    def __init__(self, *, clock: Callable[[], float] = time.time):
        self._clock = clock

    def stats(self, *, counts: Mapping[str, int],
              library: Mapping[str, Mapping], entries: Sequence[tuple[int, str]],
              artist_path: Callable[[str, str], str]) -> dict:
        now = self._clock()

        def song_rows(pairs, cap=10):
            result = []
            for file, plays in pairs[:cap]:
                if song := library.get(file):
                    row = dict(song)
                    row["plays"] = plays
                    result.append(row)
            return result

        total_plays = sum(counts.values())
        hours = sum(float(library[file].get("duration", 0) or 0) * plays
                    for file, plays in counts.items() if file in library) / 3600
        artists: dict[str, int] = {}
        genres: dict[str, int] = {}
        for file, plays in counts.items():
            song = library.get(file)
            if not song:
                continue
            if artist := song.get("artist") or "":
                artists[artist] = artists.get(artist, 0) + plays
            genre = file.split("/", 1)[0] if "/" in file else ""
            if genre and genre != "Incoming":
                genres[genre] = genres.get(genre, 0) + plays
        top_artists = []
        for name, plays in sorted(artists.items(), key=lambda item: -item[1])[:8]:
            file = next((file for file in counts
                         if library.get(file, {}).get("artist") == name), "")
            path = artist_path(file, name) if file else ""
            top_artists.append({"name": name, "plays": plays,
                                "path": path, "cover": path or file})
        week = sum(1 for played, _ in entries if now - played <= 7 * 86400)
        month_entries = [(played, file) for played, file in entries
                         if now - played <= 30 * 86400]
        month = len(month_entries)
        month_artists = {
            str(library.get(file, {}).get("artist") or "")
            for _, file in month_entries
            if library.get(file, {}).get("artist")
        }
        month_artist_counts: dict[str, int] = {}
        month_artist_files: dict[str, str] = {}
        for _, file in month_entries:
            name = str(library.get(file, {}).get("artist") or "")
            if not name:
                continue
            month_artist_counts[name] = month_artist_counts.get(name, 0) + 1
            month_artist_files.setdefault(name, file)
        month_top_artists = []
        for name, plays in sorted(
                month_artist_counts.items(), key=lambda item: -item[1])[:8]:
            file = month_artist_files[name]
            path = artist_path(file, name)
            month_top_artists.append({
                "name": name, "plays": plays,
                "path": path, "cover": path or file,
            })
        return {
            "totalPlays": total_plays,
            "hours": round(hours, 1),
            "tracksPlayed": len(counts),
            "week": week,
            "month": month,
            "monthArtists": len(month_artists),
            "monthTopArtists": month_top_artists,
            "topTracks": song_rows(sorted(counts.items(), key=lambda item: -item[1])),
            "topArtists": top_artists,
            "topGenres": [{"genre": genre, "plays": plays}
                          for genre, plays in sorted(
                              genres.items(), key=lambda item: -item[1])[:6]],
        }

    def history(self, *, entries: Sequence[tuple[int, str]],
                library: Mapping[str, Mapping]) -> dict:
        now = self._clock()
        local = time.localtime(now)
        midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday,
                                0, 0, 0, 0, 0, -1))
        # The history dial seeks ANY point of listening history (Iann's
        # Rewind synthesis verdict): the span reaches back to the oldest
        # play, bounded at 60 days, and never shrinks below the classic 14.
        span_days = 13
        oldest = min((played for played, file in entries if file),
                     default=now)
        if oldest < midnight - 13 * 86400:
            span_days = min(59, int((midnight - oldest) // 86400) + 1)
        floor = midnight - span_days * 86400
        recent = sorted(((played, file) for played, file in entries
                         if file and played >= floor), reverse=True)[:4000]
        rows = []
        for played, file in recent[:1500]:
            if song := library.get(file):
                row = dict(song)
                # QML's public contract is `ts`; retain `t` for older callers.
                row.update({"t": played, "ts": played})
                rows.append(row)
        days = []
        for offset in range(span_days, -1, -1):
            start = midnight - offset * 86400
            end = start + 86400
            day_entries = [(played, file) for played, file in recent
                           if start <= played < end and file in library]
            file_counts: dict[str, int] = {}
            for _played, file in day_entries:
                file_counts[file] = file_counts.get(file, 0) + 1
            representative_file = max(
                file_counts,
                key=lambda file: (
                    file_counts[file],
                    max(played for played, candidate in day_entries
                        if candidate == file),
                ),
                default="",
            )
            representative = library.get(representative_file, {})
            records = {
                (str(library[file].get("albumartist")
                     or library[file].get("artist") or ""),
                 str(library[file].get("album") or ""))
                for _played, file in day_entries
            }
            days.append({
                "label": time.strftime("%a %d", time.localtime(start)),
                "count": len(day_entries),
                "t0": start, "t1": end, "today": offset == 0,
                "file": representative_file,
                "title": str(representative.get("title") or ""),
                "artist": str(representative.get("albumartist")
                              or representative.get("artist") or ""),
                "album": str(representative.get("album") or ""),
                "records": len(records),
            })
        return {"days": days, "rows": rows}

    def chapters(self, *, entries: Sequence[tuple[int, str]],
                 first_played: Mapping[str, int],
                 library: Mapping[str, Mapping]) -> list[dict]:
        months: dict[tuple[int, int], list[tuple[int, str]]] = {}
        years: dict[int, list[tuple[int, str]]] = {}
        for played, file in entries:
            local = time.localtime(played)
            months.setdefault((local.tm_year, local.tm_mon), []).append((played, file))
            years.setdefault(local.tm_year, []).append((played, file))
        result = []
        for year in sorted(years, reverse=True):
            result.append(self._chapter(years[year], f"{year} — THE YEAR",
                                        str(year), first_played, library))
            for current_year, month in sorted(months, reverse=True):
                if current_year != year:
                    continue
                label = time.strftime(
                    "%B %Y", time.strptime(f"{current_year}-{month}", "%Y-%m"))
                result.append(self._chapter(
                    months[(current_year, month)], label.upper(),
                    f"{current_year}-{month:02d}", first_played, library))
        return result

    @staticmethod
    def recap_files(entries: Sequence[tuple[int, str]], key: str) -> tuple[str, list[str]]:
        if "-" in key:
            year, month = (int(value) for value in key.split("-", 1))
            selected = [(played, file) for played, file in entries
                        if time.localtime(played).tm_year == year
                        and time.localtime(played).tm_mon == month]
            label = time.strftime("%b %Y", time.strptime(key, "%Y-%m"))
        else:
            year = int(key)
            selected = [(played, file) for played, file in entries
                        if time.localtime(played).tm_year == year]
            label = key
        counts: dict[str, int] = {}
        for _, file in selected:
            counts[file] = counts.get(file, 0) + 1
        files = [file for file, _ in sorted(
            counts.items(), key=lambda item: -item[1])[:25]]
        return label, files

    def sound_profile(self, *, counts: Mapping[str, int],
                      energies: Mapping[str, float], bpms: Mapping[str, float],
                      keys: Mapping[str, int], entries: Sequence[tuple[int, str]],
                      key_label: Callable[[int], tuple[str, str]]) -> dict:
        energy_hist = [0.0] * 10
        for file, energy in energies.items():
            if counts.get(file, 0) > 0:
                energy_hist[min(9, max(0, int(energy * 10)))] += counts[file]
        bpm_hist = [0.0] * 14
        for file, bpm in bpms.items():
            if counts.get(file, 0) <= 0 or bpm <= 0:
                continue
            while bpm < 60:
                bpm *= 2
            while bpm > 200:
                bpm /= 2
            bpm_hist[min(13, max(0, int((bpm - 60) // 10)))] += counts[file]
        key_totals: dict[str, int] = {}
        minor = major = 0
        for file, key in keys.items():
            plays = counts.get(file, 0)
            if plays <= 0 or key < 0:
                continue
            name, camelot = key_label(key)
            label = f"{name} · {camelot}"
            key_totals[label] = key_totals.get(label, 0) + plays
            minor += plays if key >= 12 else 0
            major += plays if key < 12 else 0
        hour_clock = [0] * 24
        for played, _ in entries:
            hour_clock[time.localtime(played).tm_hour] += 1
        played_files = [file for file, plays in counts.items() if plays > 0]
        played_bpms = sorted(bpms[file] for file in played_files
                             if bpms.get(file, 0) > 0)
        played_energy = [energies[file] for file in played_files if file in energies]
        return {
            "energyHist": energy_hist, "bpmHist": bpm_hist,
            "topKeys": [{"key": key, "plays": plays}
                        for key, plays in sorted(
                            key_totals.items(), key=lambda item: -item[1])[:5]],
            "minorShare": minor / (minor + major) if minor + major else 0.0,
            "hourClock": hour_clock,
            "medianBpm": round(played_bpms[len(played_bpms) // 2])
                         if played_bpms else 0,
            "meanEnergy": sum(played_energy) / len(played_energy)
                          if played_energy else 0.0,
        }

    def song_story(self, file: str, *, entries: Sequence[tuple[int, str]],
                   first_played: Mapping[str, int], play_count: int) -> dict:
        """Describe one song's personal history without querying storage."""
        now = self._clock()
        month_counts: dict[str, int] = {}
        hours = [0] * 24
        for played, entry_file in entries:
            age = now - played
            if 0 <= age <= 30 * 86400:
                month_counts[entry_file] = month_counts.get(entry_file, 0) + 1
            if entry_file == file:
                hours[time.localtime(played).tm_hour] += 1
        monthly_plays = month_counts.get(file, 0)
        rank = (1 + sum(1 for count in month_counts.values()
                        if count > monthly_plays)) if monthly_plays else 0
        hour_word = ""
        if sum(hours) >= 3:
            spans = {
                "a morning": sum(hours[5:12]),
                "an afternoon": sum(hours[12:17]),
                "an evening": sum(hours[17:22]),
                "a late-night": sum(hours[22:]) + sum(hours[:5]),
            }
            hour_word = max(spans, key=spans.get)
        return {"firstHeard": first_played.get(file, 0),
                "plays": max(0, int(play_count)),
                "rankMonth": rank, "hourWord": hour_word}

    @staticmethod
    def top_artists(*, counts: Mapping[str, int],
                    library: Mapping[str, Mapping], limit: int,
                    artist_path: Callable[[str, str], str]) -> list[dict]:
        """Rank artists by durable play-count stickers."""
        totals: dict[str, dict] = {}
        for file, count in counts.items():
            artist = library.get(file, {}).get("artist") or ""
            if not artist:
                continue
            row = totals.setdefault(artist, {"plays": 0, "file": file})
            row["plays"] += count
        ranked = sorted(totals.items(), key=lambda item: -item[1]["plays"])
        result = []
        for name, row in ranked[:max(1, limit)]:
            path = artist_path(row["file"], name)
            result.append({"name": name, "path": path,
                           "cover": path or row["file"],
                           "plays": row["plays"]})
        return result

    @staticmethod
    def _chapter(entries, label, key, first_played, library):
        counts: dict[str, int] = {}
        for _, file in entries:
            counts[file] = counts.get(file, 0) + 1
        hours = sum(float(library[file].get("duration", 0) or 0) * plays
                    for file, plays in counts.items() if file in library) / 3600
        top_tracks = []
        for file, plays in sorted(counts.items(), key=lambda item: -item[1])[:5]:
            if song := library.get(file):
                row = dict(song)
                row["plays"] = plays
                top_tracks.append(row)
        artists: dict[str, int] = {}
        for file, plays in counts.items():
            if artist := library.get(file, {}).get("artist") or "":
                artists[artist] = artists.get(artist, 0) + plays
        low = min((played for played, _ in entries), default=0)
        high = max((played for played, _ in entries), default=0)
        finds = sorted(((first_played.get(file, 0), file) for file in counts
                        if low <= first_played.get(file, 0) <= high
                        and file in library), reverse=True)
        return {
            "label": label, "key": key, "plays": len(entries),
            "hours": round(hours, 1), "topTracks": top_tracks,
            "topArtists": [{"name": artist, "plays": plays}
                           for artist, plays in sorted(
                               artists.items(), key=lambda item: -item[1])[:3]],
            "newFinds": [dict(library[file]) for _, file in finds[:5]],
        }
