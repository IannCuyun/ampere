"""Album art for QML via image://art/<url-encoded library-relative path>.

Resolves art for a directory (cover file, else first audio file's embedded
picture) or a single file (embedded picture). Thumbnails cached on disk so
the 62 GB library browses instantly after first pass.
"""

from ampere.compat import cache_path, environment
import hashlib
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse
from urllib.request import Request, urlopen

from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
)
from PySide6.QtQuick import QQuickImageProvider

MUSIC_ROOT = Path(os.path.expanduser(environment("MUSIC_ROOT", "~/MusicLibrary")))
CACHE_DIR = Path(cache_path('art'))
BIO_CACHE_DIR = Path(cache_path('bios'))
THUMB_SIZE = 512
FULL_ART_MAX = 1536
ART_CACHE_VERSION = "best-source-v5"
COVER_NAMES = ("cover", "folder", "front", "album")
COVER_EXT = (".jpg", ".jpeg", ".png", ".webp")
AUDIO_EXT = (".flac", ".mp3", ".ogg", ".opus", ".m4a", ".wav")
_ART_STRIPES = tuple(threading.RLock() for _ in range(32))
_NOART_LOCK = threading.Lock()
_REMOTE_FAILURE_LOCK = threading.Lock()
_REMOTE_ART_FAILURES: set[str] = set()
_SPOTIFY_IMAGE_SIDE = 640
_SPOTIFY_ID_RE = re.compile(r"[A-Za-z0-9]{22}")
_SPOTIFY_IMAGE_HOSTS = frozenset({
    "i.scdn.co",
    "image-cdn-ak.spotifycdn.com",
    "image-cdn-fa.spotifycdn.com",
})
_MAX_REMOTE_METADATA_BYTES = 256 * 1024
_MAX_REMOTE_ART_BYTES = 8 * 1024 * 1024
_DEEZER_IMAGE_SIDE = 1000
_DEEZER_ID_RE = re.compile(r"[1-9][0-9]{0,18}")
_DEEZER_API_HOSTS = frozenset({"api.deezer.com"})
_DEEZER_IMAGE_HOSTS = frozenset({
    "cdn-images.dzcdn.net",
    "e-cdns-images.dzcdn.net",
})


def _art_lock_for(image_id: str):
    """Bounded per-source locking: same art cannot race its cache write, while
    unrelated covers remain genuinely concurrent on Qt's image workers."""
    rel = unquote(str(image_id or ""))
    for prefix in (
            "full:", "ambient:", "round:", "portrait-full:",
            "portrait:", "folder:"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    digest = hashlib.sha1(rel.encode(), usedforsecurity=False).digest()
    return _ART_STRIPES[int.from_bytes(digest[:2], "big") % len(_ART_STRIPES)]


def _stat_fingerprint(path: Path) -> str:
    try:
        stat = path.stat()
        return f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return f"{path.name}:missing"


def _cache_key(rel: str, prefix: str = "") -> str:
    """Versioned disk-cache key for every file that can supply this artwork.

    Track tags, late-added folder covers, and in-place cover replacements must
    all invalidate a thumbnail. The source-selection version also retires
    thumbnails made by an older algorithm without destructively clearing the
    user's cache during an upgrade.
    """
    abs_path = MUSIC_ROOT / rel
    dependencies = [_stat_fingerprint(abs_path)]
    parent = abs_path if abs_path.is_dir() else abs_path.parent
    dependencies.append(_stat_fingerprint(parent))
    try:
        dependencies.extend(
            _stat_fingerprint(entry)
            for entry in sorted(parent.iterdir())
            if entry.is_file()
            and (
                entry.suffix.lower() in AUDIO_EXT
                or (
                    entry.suffix.lower() in COVER_EXT
                    and entry.stem.lower() in COVER_NAMES
                )
            )
        )
    except OSError:
        pass
    identity = "\x00".join(
        (ART_CACHE_VERSION, prefix, rel, *dependencies)
    )
    return hashlib.sha1(identity.encode(), usedforsecurity=False).hexdigest()


def _image_dimensions(data: bytes | None) -> tuple[int, int]:
    if not data:
        return 0, 0
    encoded = QByteArray(data)
    device = QBuffer(encoded)
    if not device.open(QIODevice.OpenModeFlag.ReadOnly):
        return 0, 0
    size = QImageReader(device).size()
    return max(0, size.width()), max(0, size.height())


def _image_area(data: bytes | None) -> int:
    width, height = _image_dimensions(data)
    return width * height


def _image_short_side(data: bytes | None) -> int:
    width, height = _image_dimensions(data)
    return min(width, height)


def _art_decodes(data: bytes | None) -> bool:
    """Fully read one candidate through a bounded verification raster."""
    if not data:
        return False
    encoded = QByteArray(data)
    device = QBuffer(encoded)
    if not device.open(QIODevice.OpenModeFlag.ReadOnly):
        return False
    reader = QImageReader(device)
    size = reader.size()
    if not size.isValid():
        return False
    if max(size.width(), size.height()) > 64:
        reader.setScaledSize(size.scaled(
            QSize(64, 64), Qt.AspectRatioMode.KeepAspectRatio))
    return not reader.read().isNull()


def _best_art_data(candidates) -> bytes | None:
    """Return the highest-resolution candidate that fully decodes.

    Header dimensions are cheap enough for ranking, but are not proof that the
    complete raster is intact. Decode in descending order so a truncated large
    file cannot hide a valid lower-resolution exact-album source. The normal
    path decodes only the leading candidate.
    """
    ranked = sorted(
        (data for data in candidates if data),
        key=lambda data: (
            _image_short_side(data), _image_area(data), len(data)
        ),
        reverse=True,
    )
    for data in ranked:
        if _art_decodes(data):
            return data
    return None


def _embedded_art(path: Path) -> bytes | None:
    try:
        suffix = path.suffix.lower()
        if suffix == ".flac":
            f = FLAC(path)
            pictures = [(picture.type, picture.data)
                        for picture in f.pictures]
        elif suffix == ".mp3":
            tags = ID3(path)
            pictures = [(picture.type, picture.data)
                        for picture in tags.getall("APIC")]
        elif suffix == ".m4a":
            f = MP4(path)
            covr = f.tags.get("covr") if f.tags else None
            pictures = [(3, bytes(picture)) for picture in (covr or [])]
        else:
            f = MutagenFile(path)
            pics = getattr(f, "pictures", None)
            pictures = [(getattr(picture, "type", 0), picture.data)
                        for picture in (pics or [])]
        if pictures:
            # Type 3 is the standard front-cover role. Never pick a larger
            # back/leaflet scan over a real front cover; within that role,
            # highest resolution wins instead of whichever tag came first.
            front_covers = [data for picture_type, data in pictures
                            if picture_type == 3]
            return _best_art_data(front_covers or
                                  [data for _, data in pictures])
    except Exception:  # noqa: BLE001, S110 - corrupt third-party tags are absent art
        pass
    return None


def _cover_file_art(dirpath: Path) -> bytes | None:
    try:
        entries = sorted(dirpath.iterdir())
    except OSError:
        return None
    candidates = []
    for entry in entries:
        if (entry.is_file() and entry.suffix.lower() in COVER_EXT
                and entry.stem.lower() in COVER_NAMES):
            try:
                candidates.append(entry.read_bytes())
            except OSError:
                continue
    return _best_art_data(candidates)


def _album_tag(path: Path) -> str:
    try:
        media = MutagenFile(path, easy=True)
        return str((media.get("album") or [""])[0]).strip() if media else ""
    except Exception:  # noqa: BLE001 - malformed tags are treated as unknown
        return ""


def _safe_folder_art(path: Path) -> bytes | None:
    """Folder art only when every neighboring audio file is the same album.

    Many library artist directories are flat and contain several releases
    beside one generic ``cover.jpg``. Resolution must never win at the expense
    of album identity, so an external cover can outrank embedded art only in a
    directory whose tags prove it belongs to one release.
    """
    try:
        has_folder_art = any(
            entry.is_file()
            and entry.suffix.lower() in COVER_EXT
            and entry.stem.lower() in COVER_NAMES
            for entry in path.parent.iterdir()
        )
    except OSError:
        return None
    if not has_folder_art:
        return None
    album = _album_tag(path)
    if not album:
        return None
    found_audio = False
    try:
        entries = sorted(path.parent.iterdir())
    except OSError:
        return None
    for entry in entries:
        if (not entry.is_file() or entry.suffix.lower() not in AUDIO_EXT
                or ".sync-conflict-" in entry.name):
            continue
        found_audio = True
        if _album_tag(entry) != album:
            return None
    return _cover_file_art(path.parent) if found_audio else None


def _same_album_sibling_art(
        path: Path, required_side: int = THUMB_SIZE) -> bytes | None:
    """Art from another track of the SAME album in the folder — flat artist
    dirs mix albums, so a plain first-neighbor grab serves the wrong cover."""
    album = _album_tag(path)
    if not album:
        return None
    try:
        entries = sorted(path.parent.iterdir())
    except OSError:
        return None
    candidates = []
    for entry in entries:
        if (entry == path or not entry.is_file()
                or entry.suffix.lower() not in AUDIO_EXT
                or ".sync-conflict-" in entry.name):
            continue
        try:
            g = MutagenFile(entry, easy=True)
            if g and (g.get("album") or [""])[0] == album:
                data = _embedded_art(entry)
                if data:
                    candidates.append(data)
        except Exception:  # noqa: BLE001, S112 - skip one corrupt sibling tag
            continue
    return _best_art_data(candidates)


def _tag_text(value) -> str:
    """Normalize one Mutagen scalar/list/frame value to plain text."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if hasattr(value, "text"):
        value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return str(value or "").strip()


def _metadata_id(path: Path, key: str, pattern: re.Pattern) -> str:
    """Read an exact provider ID across Vorbis, EasyID3, ID3 TXXX, and MP4.

    Ampere's library is primarily FLAC, but provider identity must not silently
    disappear merely because a track uses another supported container.
    """
    aliases = (key, key.casefold(), key.upper())
    try:
        media = MutagenFile(path, easy=True)
        if media:
            for alias in aliases:
                value = _tag_text(media.get(alias))
                if pattern.fullmatch(value):
                    return value
    except Exception:  # noqa: BLE001 - malformed optional metadata is absent
        pass

    try:
        if path.suffix.lower() == ".mp3":
            for frame in ID3(path).getall("TXXX"):
                if str(getattr(frame, "desc", "")).casefold() == key.casefold():
                    value = _tag_text(frame)
                    return value if pattern.fullmatch(value) else ""
        elif path.suffix.lower() == ".m4a":
            media = MP4(path)
            tags = media.tags or {}
            for alias in (*aliases, f"----:com.apple.iTunes:{key.upper()}"):
                value = _tag_text(tags.get(alias))
                if pattern.fullmatch(value):
                    return value
    except Exception:  # noqa: BLE001 - malformed optional metadata is absent
        pass
    return ""


def _spotify_track_id(path: Path) -> str:
    """Return a verified exact Spotify track ID from local metadata."""
    return _metadata_id(path, "spotify_track_id", _SPOTIFY_ID_RE)


def _deezer_track_id(path: Path) -> str:
    """Return a verified exact Deezer track ID from local metadata."""
    return _metadata_id(path, "deezer_track_id", _DEEZER_ID_RE)


def _deezer_album_id(path: Path) -> str:
    """Return a verified exact Deezer album ID from local metadata."""
    return _metadata_id(path, "deezer_album_id", _DEEZER_ID_RE)


def _read_trusted_https(
        url: str, allowed_hosts: frozenset[str], max_bytes: int) -> bytes:
    """Read one bounded HTTPS response and validate the final redirect host."""
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
        raise ValueError("untrusted remote artwork URL")
    request = Request(
        url,
        headers={"User-Agent": "Ampere/1.0 (+local music artwork)"},
    )
    with urlopen(request, timeout=6) as response:  # noqa: S310 - hosts are allowlisted
        final = urlparse(response.geturl())
        if (final.scheme != "https"
                or (final.hostname or "").casefold() not in allowed_hosts):
            raise ValueError("untrusted remote artwork redirect")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError("remote artwork response is too large")
    return payload


def _largest_spotify_thumbnail(url: str) -> str:
    """Promote Spotify's oEmbed 300px image token to its 640px cover token."""
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in _SPOTIFY_IMAGE_HOSTS:
        return ""
    path = re.sub(
        r"(?<=ab67616d)[0-9a-fA-F]{8}",
        "0000b273",
        parsed.path,
        count=1,
    )
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _deezer_exact_art(path: Path) -> bytes | None:
    """Fetch/cache Deezer's exact-ID 1000px album cover without text search."""
    track_id = _deezer_track_id(path)
    tagged_album_id = _deezer_album_id(path)
    if not track_id and not tagged_album_id:
        return None

    # Album identity is both the strongest cover key and the shared cache key:
    # every track on one release must not redownload the same raster. Use the
    # exact track endpoint only when album identity is absent from the file.
    request_kind = "album" if tagged_album_id else "track"
    request_id = tagged_album_id or track_id
    if tagged_album_id:
        cache_identity = f"album-{tagged_album_id}"
    else:
        cache_identity = f"track-{track_id}"
    cache_file = CACHE_DIR / "remote" / f"deezer-{cache_identity}.img"
    try:
        cached = cache_file.read_bytes()
    except OSError:
        cached = None
    if cached and _best_art_data((cached,)):
        return cached

    failure_key = f"deezer-{request_kind}:{request_id}"
    with _REMOTE_FAILURE_LOCK:
        if failure_key in _REMOTE_ART_FAILURES:
            return None
    try:
        metadata = json.loads(_read_trusted_https(
            f"https://api.deezer.com/{request_kind}/{request_id}",
            _DEEZER_API_HOSTS,
            _MAX_REMOTE_METADATA_BYTES,
        ).decode("utf-8"))
        if not isinstance(metadata, dict) or metadata.get("error"):
            raise ValueError("unexpected Deezer artwork metadata payload")
        if str(metadata.get("id", "")) != request_id:
            raise ValueError("Deezer artwork identity mismatch")

        if request_kind == "track":
            album = metadata.get("album")
            if not isinstance(album, dict):
                raise ValueError("missing Deezer album metadata")
            image_url = str(album.get("cover_xl") or "")
        else:
            image_url = str(metadata.get("cover_xl") or "")

        data = _read_trusted_https(
            image_url, _DEEZER_IMAGE_HOSTS, _MAX_REMOTE_ART_BYTES)
        if not _best_art_data((data,)):
            raise ValueError("remote artwork did not decode")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_name(
            f"{cache_file.name}.{threading.get_ident()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, cache_file)
        return data
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        with _REMOTE_FAILURE_LOCK:
            _REMOTE_ART_FAILURES.add(failure_key)
        return None


def _spotify_exact_art(path: Path) -> bytes | None:
    """Fetch/cache exact-ID Spotify art without title or artist guessing."""
    track_id = _spotify_track_id(path)
    if not track_id:
        return None
    cache_file = CACHE_DIR / "remote" / f"spotify-{track_id}.img"
    try:
        cached = cache_file.read_bytes()
    except OSError:
        cached = None
    if cached and _image_short_side(cached) > 0:
        return cached
    with _REMOTE_FAILURE_LOCK:
        if track_id in _REMOTE_ART_FAILURES:
            return None
    try:
        embed_url = (
            "https://open.spotify.com/oembed?url="
            + quote(f"https://open.spotify.com/track/{track_id}", safe="")
        )
        metadata = json.loads(_read_trusted_https(
            embed_url, frozenset({"open.spotify.com"}),
            _MAX_REMOTE_METADATA_BYTES,
        ).decode("utf-8"))
        if not isinstance(metadata, dict):
            raise ValueError("unexpected artwork metadata payload")
        if str(metadata.get("provider_name", "")).casefold() != "spotify":
            raise ValueError("unexpected artwork metadata provider")
        image_url = _largest_spotify_thumbnail(metadata.get("thumbnail_url", ""))
        if not image_url:
            raise ValueError("missing trusted Spotify artwork URL")
        data = _read_trusted_https(
            image_url, _SPOTIFY_IMAGE_HOSTS, _MAX_REMOTE_ART_BYTES)
        if not _best_art_data((data,)):
            raise ValueError("remote artwork did not decode")
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_name(
            f"{cache_file.name}.{threading.get_ident()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, cache_file)
        return data
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        with _REMOTE_FAILURE_LOCK:
            _REMOTE_ART_FAILURES.add(track_id)
        return None


def _art_bytes_for(
        abs_path: Path, required_side: int = THUMB_SIZE) -> bytes | None:
    if abs_path.is_dir():
        data = _cover_file_art(abs_path)
        if data:
            return data
        try:
            entries = sorted(abs_path.iterdir())
        except OSError:
            return None
        for e in entries:
            if (e.is_file() and e.suffix.lower() in AUDIO_EXT
                    and ".sync-conflict-" not in e.name):
                data = _embedded_art(e)
                if data:
                    return data
        # container dir (genre/artist): fall through to first subdir's art, one level
        for e in entries:
            if e.is_dir() and not e.name.startswith("."):
                data = _art_bytes_for(e, required_side)
                if data:
                    return data
        return None
    if abs_path.is_file() and abs_path.suffix.lower() in AUDIO_EXT:
        embedded = _embedded_art(abs_path)
        folder = _safe_folder_art(abs_path)
        sibling = _same_album_sibling_art(abs_path, required_side)
        # A track can carry a decodable but incorrect embed even when sibling
        # tracks prove a higher-resolution cover for the exact same
        # (directory, album tag) release. Compare every safe album-local source
        # before accepting an otherwise adequate thumbnail; the full-art and
        # thumbnail paths must resolve the same album identity.
        data = _best_art_data((embedded, folder, sibling))
        if _image_short_side(data) < _DEEZER_IMAGE_SIDE:
            data = _best_art_data((data, _deezer_exact_art(abs_path)))
        if _image_short_side(data) < _SPOTIFY_IMAGE_SIDE:
            data = _best_art_data((data, _spotify_exact_art(abs_path)))
        # Never fall through to an arbitrary parent cover here. The safe
        # single-album folder candidate was already considered above; using a
        # generic cover from a flat multi-album directory would trade exact
        # identity for a superficially sharper but incorrect image.
        return data
    return None


_NOART: QImage | None = None


def _noart_image() -> QImage:
    """THE 'no image found' replacement — one static image shared by every
    view (no initials, nothing name-keyed): a dim note on a neutral slate
    gradient. Rendered once per process."""
    global _NOART
    with _NOART_LOCK:
        if _NOART is None:
            s = THUMB_SIZE
            img = QImage(s, s, QImage.Format.Format_ARGB32)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            grad = QLinearGradient(0, 0, 0, s)
            grad.setColorAt(0.0, QColor.fromHslF(0.62, 0.10, 0.185))
            grad.setColorAt(1.0, QColor.fromHslF(0.62, 0.12, 0.095))
            p.fillRect(img.rect(), grad)
            note = QFont()
            note.setPixelSize(int(s * 0.44))
            p.setFont(note)
            p.setPen(QColor.fromHslF(0.62, 0.10, 0.34))
            p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
            p.end()
            _NOART = img
    return _NOART


def warm_thumb(rel: str):
    """Build one thumbnail away from Qt without racing provider requests."""
    with _art_lock_for(rel):
        _warm_thumb_locked(rel)


def _warm_thumb_locked(rel: str):
    """Pre-build the disk-cached thumbnail for a library path (no-op when
    already cached). Called from the prefetch worker so upcoming songs'
    art is ready before their transition — QImage raster ops are safe off
    the GUI thread."""
    cache_file = CACHE_DIR / (_cache_key(rel) + ".jpg")
    if cache_file.exists():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    img = QImage()
    abs_path = (MUSIC_ROOT / rel).resolve()
    if MUSIC_ROOT.resolve() in abs_path.parents or abs_path == MUSIC_ROOT.resolve():
        data = _art_bytes_for(abs_path)
        if data:
            img.loadFromData(data)
    if not img.isNull():
        img = img.scaled(THUMB_SIZE, THUMB_SIZE,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        img.save(str(cache_file), "JPG", 88)
    else:
        img = QImage(1, 1, QImage.Format.Format_ARGB32)
        img.fill(0)
        img.save(str(cache_file), "PNG")


class ArtProvider(QQuickImageProvider):
    def __init__(self):
        # `Image.asynchronous` is only a request for provider URLs unless the
        # provider advertises this flag. Without it, Mutagen extraction and
        # 1536px decodes occupied Qt's render/input thread on every song or
        # page change.
        super().__init__(
            QQuickImageProvider.ImageType.Image,
            QQuickImageProvider.Flag.ForceAsynchronousImageLoading,
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _square(self, rel: str, *, fallback_on_miss: bool = True) -> QImage:
        """Square thumbnail for a library path — disk-cached; misses get the
        shared no-art image unless the caller owns a semantic fallback."""
        cache_file = CACHE_DIR / (_cache_key(rel) + ".jpg")
        img = QImage()
        if cache_file.exists():
            img.load(str(cache_file))
        else:
            # Settings may remove the live cache directory. Recreate it on the
            # first subsequent miss so caching resumes without an app restart.
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            abs_path = (MUSIC_ROOT / rel).resolve()
            # never escape the library root
            if MUSIC_ROOT.resolve() in abs_path.parents or abs_path == MUSIC_ROOT.resolve():
                data = _art_bytes_for(abs_path)
                if data:
                    img.loadFromData(data)
            if not img.isNull():
                img = img.scaled(
                    THUMB_SIZE, THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                img.save(str(cache_file), "JPG", 88)
            else:
                img = QImage(1, 1, QImage.Format.Format_ARGB32)
                img.fill(0)
                img.save(str(cache_file), "PNG")
        if img.isNull() or img.width() <= 1:
            img = _noart_image() if fallback_on_miss else QImage()
        return img

    @staticmethod
    def _circled(img: QImage) -> QImage:
        """Center-crop to a circle with a real alpha mask — QML Rectangle
        clipping is bounding-box only, so round avatars are cut here."""
        s = min(img.width(), img.height())
        out = QImage(s, s, QImage.Format.Format_ARGB32)
        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addEllipse(0.5, 0.5, s - 1.0, s - 1.0)
        p.setClipPath(clip)
        p.drawImage(0, 0, img, (img.width() - s) // 2, (img.height() - s) // 2, s, s)
        p.end()
        return out

    def _full(
            self, rel: str, requested_size: QSize, *,
            fallback_on_miss: bool = True) -> tuple[QImage, QSize]:
        """Highest-resolution album source, decoded to a bounded display size.

        This intentionally bypasses the lossy 512px thumbnail cache. The
        QImageReader cap allows JPEG readers to downscale during decode rather
        than allocating an arbitrarily large intermediate image.
        """
        img = QImage()
        original_size = QSize()
        abs_path = (MUSIC_ROOT / rel).resolve()
        root = MUSIC_ROOT.resolve()
        if root in abs_path.parents or abs_path == root:
            max_side = FULL_ART_MAX
            if requested_size.isValid():
                max_side = min(
                    max_side,
                    max(requested_size.width(), requested_size.height()),
                )
            data = _art_bytes_for(abs_path, max_side)
            if data:
                encoded = QByteArray(data)
                device = QBuffer(encoded)
                if device.open(QIODevice.OpenModeFlag.ReadOnly):
                    reader = QImageReader(device)
                    original_size = reader.size()
                    if original_size.isValid() and max(
                        original_size.width(), original_size.height()
                    ) > max_side:
                        reader.setScaledSize(
                            original_size.scaled(
                                QSize(max_side, max_side),
                                Qt.AspectRatioMode.KeepAspectRatio,
                            )
                        )
                    img = reader.read()
                    if not img.isNull() and not original_size.isValid():
                        original_size = img.size()
        if img.isNull() and fallback_on_miss:
            img = _noart_image()
            original_size = img.size()
        return img, original_size

    def requestImage(self, image_id: str, size, requested_size: QSize) -> QImage:
        # Serialize only requests for the same underlying source. A library
        # grid can decode distinct covers concurrently while duplicate requests
        # still share one safe cache-write boundary.
        with _art_lock_for(image_id):
            return self._request_image_locked(image_id, size, requested_size)

    def _request_image_locked(
            self, image_id: str, size, requested_size: QSize) -> QImage:
        rel = unquote(image_id)
        full = rel.startswith("full:")
        ambient = rel.startswith("ambient:")
        round_crop = rel.startswith("round:")
        portrait_full = rel.startswith("portrait-full:")
        portrait = rel.startswith("portrait:")
        folder = rel.startswith("folder:")
        if full:
            rel = rel[len("full:"):]
            img, original_size = self._full(rel, requested_size)
        elif ambient:
            rel = rel[len("ambient:"):]
            img, original_size = self._full(rel, requested_size)
        elif portrait_full:
            key = rel[len("portrait-full:"):]
            img = QImage()
            if re.fullmatch(r"[0-9a-f]{40}", key):
                img.load(str(BIO_CACHE_DIR / f"{key}.img"))
            original_size = img.size()
        elif portrait:
            key = rel[len("portrait:"):]
            img = QImage()
            if re.fullmatch(r"[0-9a-f]{40}", key):
                img.load(str(BIO_CACHE_DIR / f"{key}.img"))
            if img.isNull():
                img = _noart_image()
            img = self._circled(img)
            original_size = img.size()
        elif folder:
            rel = rel[len("folder:"):]
            img, original_size = self._full(
                rel, requested_size, fallback_on_miss=False)
        elif round_crop:
            rel = rel[len("round:"):]
            img, source_size = self._full(rel, requested_size)
            img = self._circled(img)
            original_size = source_size
        else:
            # Unprefixed image://art URLs are the app-wide album-art default.
            # They select the best verified native source and never route
            # through the lossy 512px JPEG thumbnail cache.
            img, original_size = self._full(rel, requested_size)

        # Native album variants are already bounded during decode. Portraits
        # are cached remote rasters, so only that separate media type needs a
        # final provider-side downscale here.
        if ((portrait or portrait_full) and not img.isNull()
                and requested_size.isValid()):
            target = original_size.scaled(
                requested_size,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            if target.width() < img.width() or target.height() < img.height():
                img = img.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        if size is not None:
            # Qt's provider contract requires the unrequested/original size.
            size.setWidth(original_size.width())
            size.setHeight(original_size.height())
        return img
