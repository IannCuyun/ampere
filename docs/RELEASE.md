# Release procedure

Current state: local release candidate preparation. No public release or tag
has been created. Application license selection is still pending; see
THIRD_PARTY_NOTICES.md before distributing the application.

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
releases. GitHub-hosted execution remains unverified until it runs there.

The October 31 local checks use fresh Python environments and isolated service
namespaces on the existing host. A real clean-distribution systemd session and
physical-device listening are separate acceptance checks; do not imply that
null-output or mocked service lifecycle tests certify them.
