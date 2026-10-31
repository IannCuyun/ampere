# Third-party dependencies

Ampere's application license is pending a release decision. The current
`Proprietary` metadata is not a completed distribution clearance.

Direct runtime dependencies, from the installed metadata checked October 31, 2026:

| Dependency | License |
|---|---|
| PySide6 / Qt | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; individual Qt modules and bundled components require their own review |
| python-mpd2 | LGPLv3 |
| Mutagen | GPL-2.0-or-later |
| RapidFuzz | MIT |
| NumPy | BSD-3-Clause and bundled component licenses |
| Requests | Apache-2.0 |
| pykakasi | GPL-3.0-or-later |
| pypinyin | MIT |
| AnyAscii | ISC |

These packages are installed separately by pip, not copied into Ampere's wheel.
This inventory does not replace their license texts or eliminate applicable
obligations. MPD, PipeWire, ffmpeg and other system executables are installed by
the operating system and retain their own licenses.

The current direct use of GPL libraries means a permissive-only or proprietary
release must not be assumed compatible. GPLv3 is the recommended candidate for
the existing dependency set, subject to completing source/asset provenance and
redistribution checks. Replacing GPL dependencies would be a separate technical
project, not a metadata edit.

References:
- https://mutagen.readthedocs.io/en/latest/
- https://github.com/miurahr/pykakasi/blob/master/COPYING
- https://www.qt.io/development/open-source-lgpl-obligations
