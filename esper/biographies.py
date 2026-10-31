"""Cached, trust-bounded artist biography enrichment."""

from __future__ import annotations

import hashlib
import json
import threading
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from .persistence import atomic_write_bytes, atomic_write_json


EMPTY_BIO = {
    "found": False, "bio": "", "url": "", "source": "",
    "portrait": "", "imageRemote": "", "imageVersion": 6,
    "imageOrigin": "", "portraitRetryable": False,
}
# Bumped so every cached entry is re-fetched once through the portrait chain
# below: entries written at 5 hold Wikipedia lead images, which for many
# artists are a signature, a logo, or a record sleeve rather than a portrait.
PORTRAIT_SCHEMA_VERSION = 6
# TheAudioDB is a MUSIC database: its artist images are portraits by
# definition, which is why Lollypop reaches for it before anything else.
# The public client id is the one Lollypop ships.
AUDIODB_CLIENT_ID = "195003"
AUDIODB_HOSTS = ("r2.theaudiodb.com", "www.theaudiodb.com", "theaudiodb.com")
PORTRAIT_TARGET_WIDTH = 1600
PORTRAIT_CACHE_MAX_BYTES = 256 * 1024 * 1024
MUSICAL_TERMS = (
    "band", "singer", "musician", "rapper", "album", "song", "music",
    "dj", "composer", "producer", "vocalist", "guitarist", "duo",
)


class BiographyService:
    def __init__(self, cache_dir: str | Path, *, getter=None, image_getter=None,
                 portrait_cache_bytes=PORTRAIT_CACHE_MAX_BYTES):
        self._cache_dir = Path(cache_dir)
        self._getter = getter or self._get_json
        self._image_getter = image_getter or self._get_image
        self._portrait_cache_bytes = max(0, int(portrait_cache_bytes))
        self._cache_lock = threading.Lock()
        self._portrait_orphans_pruned = False

    def maintain_portrait_cache(self) -> None:
        """Reclaim ownerless rasters once per service lifetime.

        The Library prime worker calls this before hydration, keeping the
        filesystem walk off Qt's render thread. A later first download also
        performs the sweep if the Library has not been opened yet.
        """
        with self._cache_lock:
            self._prune_portrait_orphans_locked()

    def peek_cached(self, artist: str) -> dict | None:
        """Return one complete current cache entry without touching the network.

        Library hydration uses this path in one background batch.  A JSON
        record whose portrait file was pruned is a miss: ``get`` may repair
        it later through the normal trust-bounded provider chain, but a cache
        peek must never cause that download itself.
        """
        artist = str(artist or "").strip()
        if not artist:
            return None
        try:
            cached = json.loads(
                self._cache_file(artist).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if (not self._valid_result(cached)
                or cached.get("imageVersion") != PORTRAIT_SCHEMA_VERSION
                or "imageRemote" not in cached):
            return None
        portrait_key = str(cached.get("portrait") or "")
        if not portrait_key:
            return None
        portrait = self._cache_dir / f"{portrait_key}.img"
        try:
            if not portrait.is_file() or portrait.stat().st_size <= 0:
                return None
        except OSError:
            return None
        return dict(cached)

    def get(self, artist: str) -> dict:
        artist = str(artist or "").strip()
        if not artist:
            return dict(EMPTY_BIO)
        cache_file = self._cache_file(artist)
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            # Cache entries written before portrait enrichment deliberately
            # fall through once, so existing users gain the new image field.
            if (self._valid_result(cached)
                    and cached.get("imageVersion") == PORTRAIT_SCHEMA_VERSION
                    and "imageRemote" in cached):
                return self._attach_portrait(cached)
        except (OSError, ValueError, TypeError):
            pass
        result = self.fetch(artist)
        # A biography and an artist portrait are independent pieces of truth.
        # Lollypop-style artwork fallback can produce a verified portrait for
        # an artist with no Wikipedia article, so cache either positive result.
        # A provider outage with no remote URL is deliberately not durable.
        if (result.get("found") is True or result.get("imageRemote")):
            result = self._attach_portrait(result)
            try:
                atomic_write_json(cache_file, result)
            except OSError:
                pass
        return result

    def fetch(self, artist: str) -> dict:
        artist = str(artist or "").strip()
        if not artist:
            return dict(EMPTY_BIO)

        result, wikipedia_retryable = self._fetch_wikipedia(artist)
        if not result:
            result = dict(EMPTY_BIO)

        # PORTRAIT ORDER (Iann, 2026-08-22, after reading Lollypop's chain).
        # Wikipedia is authoritative for the BIOGRAPHY but not for the face:
        # its lead image for Travis Scott is a signature, and for many acts it
        # is a logo or a record sleeve. A music database's artist image is a
        # portrait by definition, so it goes first and the encyclopaedia's
        # lead image becomes the fallback.
        row, audiodb_retryable = self._audiodb_row(artist)
        if row is not None:
            for key in ("strArtistThumb", "strArtistFanart"):
                remote = str(row.get(key) or "")
                parsed = urllib.parse.urlsplit(remote)
                if (parsed.scheme == "https"
                        and parsed.hostname in AUDIODB_HOSTS and parsed.path):
                    result["imageRemote"] = remote
                    result["imageOrigin"] = "TheAudioDB"
                    break

        # Deezer alone is NOT identity evidence: it will return a face for any
        # name typed at it, which is how "Adam Warren" — a comics writer, a
        # pitcher and a cricketer, with no musical article anywhere — acquired
        # a portrait. It is accepted only once something else has established
        # that an act by this exact name exists (SPEC UNDESIGNED #17).
        corroborated = bool(result.get("found")) or row is not None
        deezer_retryable = False
        if not result.get("imageRemote") and corroborated:
            remote, deezer_retryable = self._deezer_artist_image(artist)
            if remote:
                result["imageRemote"] = remote
                result["imageOrigin"] = "Deezer"
        if not result.get("imageRemote") and (
                wikipedia_retryable or deezer_retryable or audiodb_retryable):
            result["portraitRetryable"] = True
        return result

    def _audiodb_row(self, artist: str) -> tuple[dict | None, bool]:
        """The provider's own record for this EXACT artist name, if any.

        A match is identity corroboration in its own right: it says a music
        database knows an act by this name, which a bare image-search result
        does not (SPEC row 38)."""
        query = urllib.parse.urlencode({"s": artist})
        try:
            payload = self._getter(
                f"https://theaudiodb.com/api/v1/json/{AUDIODB_CLIENT_ID}"
                f"/search.php?{query}")
        except Exception:
            return None, True
        rows = payload.get("artists") if isinstance(payload, dict) else None
        target = self._normalized_artist(artist)
        for row in rows or ():
            if isinstance(row, dict) and \
                    self._normalized_artist(row.get("strArtist")) == target:
                return row, False
        return None, False

    def _audiodb_artist_image(self, artist: str) -> tuple[str, str, bool]:
        """Return an exact-name TheAudioDB portrait, and whether to retry.

        Identity is gated exactly as the Deezer path is: the provider's own
        artist name must match after normalization, so a namesake can never
        supply a face (SPEC row 38). ``strArtistThumb`` is the portrait;
        ``strArtistFanart`` is a wide promotional shot and is only used when
        no thumb exists.
        """
        row, retryable = self._audiodb_row(artist)
        if row is None:
            return "", "", retryable
        for key in ("strArtistThumb", "strArtistFanart"):
            remote = str(row.get(key) or "")
            parsed = urllib.parse.urlsplit(remote)
            if (parsed.scheme == "https"
                    and parsed.hostname in AUDIODB_HOSTS
                    and parsed.path):
                return remote, "TheAudioDB", False
        return "", "", False

    def _fetch_wikipedia(self, artist: str) -> tuple[dict | None, bool]:
        """Return biography data and whether transport failed along the way.

        The direct page and one search request cover the normal Wikipedia
        naming cases without firing five speculative REST requests per artist.
        That matters when the Library admits several portraits concurrently.
        """
        retryable = False
        info, failed = self._summary_outcome(artist)
        retryable = retryable or failed
        if info:
            return info, retryable

        try:
            query = urllib.parse.quote(
                f"{artist} musician OR band OR singer OR rapper")
            search = self._getter(
                "https://en.wikipedia.org/w/api.php?action=query&list=search"
                f"&format=json&srlimit=5&srsearch={query}")
            results = [row for row in search.get("query", {}).get("search", [])
                       if isinstance(row, dict) and row.get("title")
                       and not row["title"].lower().startswith("list of")
                       and "discography" not in row["title"].lower()]
            key = artist.casefold()
            ordered = [row["title"] for row in results
                       if row["title"].split(" (")[0].casefold() == key]
            ordered += [row["title"] for row in results
                        if key in row["title"].casefold()
                        and row["title"] not in ordered]
            for title in ordered[:3]:
                info, failed = self._summary_outcome(title)
                retryable = retryable or failed
                if info:
                    return info, retryable
        except Exception:
            retryable = True
        return None, retryable

    @staticmethod
    def _normalized_artist(value: str) -> str:
        value = unicodedata.normalize("NFKC", str(value or ""))
        return " ".join(value.casefold().split())

    def _deezer_artist_image(self, artist: str) -> tuple[str, bool]:
        """Return only an exact-name Deezer XL portrait.

        Deezer is Lollypop's credential-free artist-art provider. Search
        results are not trusted by rank: an exact normalized artist name is
        required, preventing a visually plausible namesake from being cached.
        """
        query = urllib.parse.urlencode({
            "q": artist, "output": "json", "index": 0, "limit": 10,
        })
        try:
            payload = self._getter(
                "https://api.deezer.com/search/artist?" + query)
        except Exception:
            return "", True
        target = self._normalized_artist(artist)
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if self._normalized_artist(row.get("name")) != target:
                continue
            remote = str(row.get("picture_xl") or "")
            parsed = urllib.parse.urlsplit(remote)
            if (parsed.scheme == "https"
                    and parsed.hostname == "cdn-images.dzcdn.net"
                    and parsed.path and "/artist//" not in parsed.path):
                return remote, False
        return "", False

    def _summary(self, title: str | None) -> dict | None:
        return self._summary_outcome(title)[0]

    def _summary_outcome(self, title: str | None) -> tuple[dict | None, bool]:
        if not title:
            return None, False
        try:
            summary = self._getter(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" +
                urllib.parse.quote(title.replace(" ", "_")))
        except Exception:
            return None, True
        extract = str(summary.get("extract") or "")
        if summary.get("type") == "disambiguation" or not extract:
            return None, False
        if not any(term in extract.casefold() for term in MUSICAL_TERMS):
            return None, False
        page_image = self._page_image(title)
        thumbnail = summary.get("thumbnail") or {}
        original = summary.get("originalimage") or {}
        image_remote = str(page_image or original.get("source")
                           or thumbnail.get("source") or "")
        return {"found": True, "bio": extract,
                "url": summary.get("content_urls", {}).get(
                    "desktop", {}).get("page", ""), "source": "Wikipedia",
                "portrait": "", "imageRemote": image_remote,
                "imageVersion": PORTRAIT_SCHEMA_VERSION,
                "imageOrigin": "Wikimedia" if image_remote else "",
                "portraitRetryable": False}, False

    def _page_image(self, title: str) -> str:
        """Request Wikipedia's canonical lead image at display resolution.

        ``generator=images`` returns every file embedded in an article, which
        allowed square album covers and individual-member photos to outrank the
        artist. ``pageimages`` follows Wikipedia's own lead-image decision.
        """
        query = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "piprop": "thumbnail|original",
            "pithumbsize": PORTRAIT_TARGET_WIDTH,
            "titles": title,
        })
        try:
            payload = self._getter(
                "https://en.wikipedia.org/w/api.php?" + query)
        except Exception:
            return ""
        pages = payload.get("query", {}).get("pages", {})
        if not isinstance(pages, dict):
            return ""
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            thumbnail = page.get("thumbnail") or {}
            original = page.get("original") or {}
            source = str(thumbnail.get("source") or original.get("source") or "")
            if source:
                return source
        return ""

    def _prune_portraits(self, keep: Path) -> None:
        if self._portrait_cache_bytes <= 0:
            return
        self._prune_portrait_orphans_locked(keep)
        try:
            entries = [path for path in self._cache_dir.glob("*.img")
                       if path.is_file()]
            sizes = {path: path.stat().st_size for path in entries}
        except OSError:
            return
        total = sum(sizes.values())
        if total <= self._portrait_cache_bytes:
            return
        try:
            entries.sort(key=lambda path: path.stat().st_mtime)
        except OSError:
            return
        for path in entries:
            if total <= self._portrait_cache_bytes:
                break
            if path == keep:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            total -= sizes.get(path, 0)

    def _prune_portrait_orphans_locked(self, keep: Path | None = None) -> None:
        if self._portrait_orphans_pruned:
            return
        # Schema/provider upgrades change the opaque key stored in an
        # artist's JSON record.  The old raster then has no owner, but before
        # this sweep it still consumed the bounded cache and eventually
        # evicted useful current portraits.  The image being attached is not
        # referenced until the caller writes its JSON immediately afterward,
        # so it is an explicit temporary root.
        referenced = {keep.stem} if keep is not None else set()
        try:
            records = list(self._cache_dir.glob("*.json"))
        except OSError:
            records = []
        for record in records:
            try:
                value = json.loads(record.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            key = str(value.get("portrait") or "") \
                if isinstance(value, dict) else ""
            if key:
                referenced.add(key)
        try:
            entries = [path for path in self._cache_dir.glob("*.img")
                       if path.is_file()]
        except OSError:
            return
        for path in entries:
            if path.stem in referenced:
                continue
            try:
                path.unlink()
            except OSError:
                continue
        self._portrait_orphans_pruned = True

    def _attach_portrait(self, result: dict) -> dict:
        """Cache only trust-bounded Wikimedia portraits and expose an opaque key."""
        value = dict(result)
        remote = str(value.get("imageRemote") or "")
        key = hashlib.sha1(remote.encode(), usedforsecurity=False).hexdigest()
        portrait = self._cache_dir / f"{key}.img"
        if remote:
            try:
                with self._cache_lock:
                    cached = portrait.exists() and portrait.stat().st_size > 0
                    if cached:
                        portrait.touch()
                if not cached:
                    data = self._image_getter(remote)
                    if data:
                        with self._cache_lock:
                            if (not portrait.exists()
                                    or portrait.stat().st_size <= 0):
                                atomic_write_bytes(portrait, data)
                            self._prune_portraits(portrait)
                        cached = True
                value["portrait"] = key if cached else ""
                value["portraitRetryable"] = not cached
            except Exception:
                value["portrait"] = ""
                value["portraitRetryable"] = True
        else:
            value["portrait"] = ""
        return value

    def _cache_file(self, artist: str) -> Path:
        key = hashlib.sha1(artist.casefold().encode(),
                           usedforsecurity=False).hexdigest()
        return self._cache_dir / f"{key}.json"

    @staticmethod
    def _valid_result(value) -> bool:
        return (isinstance(value, dict)
                and (value.get("found") is True or value.get("imageRemote"))
                and all(isinstance(value.get(key), str)
                        for key in ("bio", "url", "source")))

    @staticmethod
    def _get_json(url: str) -> dict:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
                "en.wikipedia.org", "www.wikipedia.org", "api.deezer.com",
                "theaudiodb.com", "www.theaudiodb.com"}:
            raise ValueError("refusing untrusted artist-profile URL")
        request = urllib.request.Request(
            url, headers={"User-Agent": "Ampere/0.17.0 (local music player)"})
        with urllib.request.urlopen(request, timeout=8) as response:  # nosec B310
            return json.loads(response.read().decode())

    @staticmethod
    def _get_image(url: str) -> bytes:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
                "upload.wikimedia.org", "cdn-images.dzcdn.net",
                "r2.theaudiodb.com", "www.theaudiodb.com", "theaudiodb.com"}:
            raise ValueError("refusing untrusted artist image URL")
        request = urllib.request.Request(
            url, headers={"User-Agent": "Ampere/0.17.0 (local music player)"})
        with urllib.request.urlopen(request, timeout=8) as response:  # nosec B310
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                raise ValueError("artist portrait is not an image")
            data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("artist portrait exceeds cache limit")
            return data
