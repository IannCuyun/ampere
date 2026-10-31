"""Safety-bounded local or remote deletion of library-relative tracks."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class DeletionReconciliation:
    deleted: int
    failed: int
    disliked_verified: bool
    queue_verified: bool

    def message(self) -> str:
        noun = "file" if self.deleted == 1 else "files"
        parts = [f"{self.deleted} {noun} deleted from the library"]
        if self.failed:
            failed_noun = "file" if self.failed == 1 else "files"
            parts.append(
                f"{self.failed} {failed_noun} could not be deleted and remain Disliked")
        if not self.disliked_verified:
            parts.append("Disliked cleanup could not be verified")
        if not self.queue_verified:
            parts.append("queue cleanup could not be verified")
        return " · ".join(parts)


class LibraryDeletionService:
    def __init__(self, library_root: str | Path, *, runner=subprocess.run):
        self._library_root = Path(library_root).resolve()
        self._runner = runner

    def delete(self, files, *, remote_host="", remote_root=""):
        safe, failed = self.partition(files)
        if remote_host and remote_root:
            deleted, remote_failed = self._delete_remote(
                safe, remote_host, remote_root)
            return deleted, failed + remote_failed
        deleted, local_failed = self._delete_local(safe)
        return deleted, failed + local_failed

    @staticmethod
    def partition(files):
        safe, rejected = [], []
        for file in files:
            value = str(file or "")
            relative = PurePosixPath(value)
            if (not value or relative.is_absolute() or not relative.parts
                    or ".." in relative.parts):
                rejected.append(file)
            else:
                safe.append(value)
        return safe, rejected

    def _delete_local(self, files):
        deleted, failed = [], []
        for file in files:
            candidate = self._library_root.joinpath(*PurePosixPath(file).parts)
            try:
                relative_parts = candidate.relative_to(self._library_root).parts
                cursor = self._library_root
                if any((cursor := cursor / part).is_symlink()
                       for part in relative_parts):
                    failed.append(file)
                    continue
                target = candidate.resolve()
                if not target.is_relative_to(self._library_root):
                    failed.append(file)
                    continue
                target.unlink()
                deleted.append(file)
            except FileNotFoundError:
                deleted.append(file)
            except (OSError, ValueError):
                failed.append(file)
        return deleted, failed

    def _delete_remote(self, files, host, root):
        deleted, failed = [], []
        root = str(root).rstrip("/")
        for start in range(0, len(files), 50):
            chunk = files[start:start + 50]
            command = "rm -f -- " + " ".join(
                shlex.quote(f"{root}/{file}") for file in chunk)
            try:
                result = self._runner(
                    ["ssh", "-o", "BatchMode=yes", str(host), command],
                    capture_output=True, text=True, timeout=60)
                (deleted if result.returncode == 0 else failed).extend(chunk)
            except Exception:
                failed.extend(chunk)
        return deleted, failed
