# Release procedure

**Public release authorized October 31, 2026:** Iann requested publishing
Version 1 so a friend can download it. This supersedes the earlier privacy hold.
Version 1.0.0
omits the unfinished Features tab; its code remains for incremental development.

Application license: GPL-3.0-only, selected October 31, 2026. See LICENSE,
COPYRIGHT and THIRD_PARTY_NOTICES.md before distributing the application.

1. Run `python tests/run_isolated.py` with the intended Python environment.
2. Run the QML suite using Qt 6 qmltestrunner with offscreen/software rendering.
3. Build wheel and source archive with `python -m build` (or `uv build`).
4. Install the wheel outside the checkout in a fresh environment. Verify
   packaged resources, setup idempotence, conflict preservation, launch,
   local-library scan, playback, audio routing, and MPRIS controls.
5. Inspect both artifact member lists and scan their contents. A source archive
   is not the same publication surface as the entire Git repository/history.
6. Complete license, third-party notice and asset-provenance review. Verify
   metadata and the version agree with the intended release.
7. Run the GitHub checks against the exact release commit. Record supported
   Linux distribution, Python and Qt versions and any remaining limitations.
8. Select the public repository and release visibility; audit anything that
   will be public, including Git history if it is retained. Record SHA256 sums
   and source commit for each uploaded artifact.

The GitHub workflow builds and tests only; it cannot publish packages or create
releases. Hosted checks cover Python 3.12/3.14, QML on the application Qt runtime, and
fresh Ubuntu 24.04 user services with MPD, PipeWire, EQ routing, MPRIS pause,
and application/engine shutdown. Physical audio devices remain a separate check.

The October 31 local checks use fresh Python environments and isolated service
namespaces on the existing host. The hosted Ubuntu check additionally uses real systemd user services.
Physical-device listening remains separate; a null output does not certify
audible quality, device switching or suspend/resume across hardware.
