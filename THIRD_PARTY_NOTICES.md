# Third-party dependencies

Ampere is licensed under GPL-3.0-only. Its own license does not replace the
licenses of third-party dependencies or bundled assets.

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

The application uses GPLv3 terms alongside its GPL-compatible dependencies.
The Python wheel contains Ampere source and assets; it does not bundle the
third-party Python distributions or system executables.

References:
- https://mutagen.readthedocs.io/en/latest/
- https://github.com/miurahr/pykakasi/blob/master/COPYING
- https://www.qt.io/development/open-source-lgpl-obligations

## Bundled fonts

Inter (The Inter Project Authors) and Rajdhani (Indian Type Foundry) are
redistributed unmodified under the SIL Open Font License 1.1. Their complete
copyright and license texts are included beside the font files in
`qml/assets/fonts/Inter-OFL.txt` and `Rajdhani-OFL.txt` and in installed assets.
Upstream source: https://github.com/google/fonts/tree/main/ofl/inter and
https://github.com/google/fonts/tree/main/ofl/rajdhani . They keep their own
font licenses independently of Ampere's application license.
