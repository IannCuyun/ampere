# Contributing

Ampere is a Python and Qt Quick application for Linux. The playback engine is
MPD; the audio correction path uses PipeWire. Start with README.md and
`docs/INSTALL.md` for an isolated development environment. Editable installation
is supported with `pip install -e .`.

Run Python checks through `python tests/run_isolated.py`. This runner prevents
tests from connecting to your active MPD session. Do not use unrestricted test
discovery while listening to music. Run the QML suite with Qt 6 qmltestrunner,
`-input tests/qml -import qml`, using offscreen/software rendering when headless.

Keep changes focused and describe the behavior they fix. Preserve existing
queues, listening history, playlists and configuration. Add a behavioral
regression test for meaningful state or lifecycle changes. Never include
personal music, artwork caches, credentials or local runtime state in patches.

Discuss visual changes with the maintainer before implementing a new layout.
A screenshot of an old design is not approval to restore it.

The project license is pending. External contribution terms will be clarified
before contributions are solicited.
