# Install Ampere on Linux

Current target: a Linux desktop with systemd user services, PipeWire,
pipewire-pulse and a session manager such as WirePlumber. Python 3.12 or newer
is required. Windows and macOS packages are not provided.

Install your distribution's packages for MPD, mpc, ffmpeg (including ffprobe),
PipeWire, its PulseAudio compatibility server, pactl, and the PipeWire tools
pw-cli, pw-dump and pw-metadata. Qt needs a working desktop graphics stack.

From the source directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps .
.venv/bin/ampere-setup --music-dir "$HOME/Music"
.venv/bin/ampere-setup --doctor
.venv/bin/ampere
```

Replace the music path with your existing music folder. Setup does not move or
modify your music. It creates MPD configuration, a matching Ampere library
setting, and a desktop menu entry pointing at this virtual environment. Keep
the environment in place. Use `--dry-run` to list planned files, or
`--no-desktop` to omit the menu entry. No services start during setup.

In Settings, use Rescan to index the folder. Choose an album or song to play.
MPD keeps its database, playlists, stickers and paused playback state under
`~/.local/state/ampere/mpd`. Ampere starts the MPD user service on launch and
stops it on exit. The EQ chain is started through `filter-chain.service`.

## User services

Most target distributions ship `mpd.service` and `filter-chain.service` user
units. Check both with `ampere-setup --doctor`. If a unit is missing, example
units are included in `packaging/systemd` (source) and
`.venv/share/ampere/systemd` (installed package). Confirm the executable paths
match your distribution before using them. Copy only the missing unit to
`~/.config/systemd/user/`, without replacing an existing unit, then run:

```sh
systemctl --user daemon-reload
```

Do not enable MPD at login: Ampere manages its session lifetime. PipeWire,
pipewire-pulse and the desktop session manager must already be available.
The generated MPD config uses the `ampere_eq` PulseAudio sink and binds MPD to
loopback and a local Unix socket, not the public network.

## Existing installations

Setup refuses to overwrite differing files, including an existing MPD config
or desktop entry. It is not a migration or reset command. Preserve your existing
configuration. Existing Esper-named state and audio routes remain supported.
For a custom library location, set `AMPERE_MUSIC_ROOT` to the same local folder
as MPD's `music_directory`; advanced users may use
`~/.config/ampere/library.json` containing `{"music_directory":"/absolute/path"}`
(or the existing `esper` config directory when present). Environment overrides
continue to take precedence.

## Troubleshooting

- Start with `ampere-setup --doctor`; it is read-only.
- Engine offline: inspect `systemctl --user status mpd.service` and
  `journalctl --user -u mpd.service -n 50`. A system-wide MPD instance using
  port 6600 can conflict with the user service.
- No sound: check `pactl info`, `pactl list short sinks`, and
  `systemctl --user status filter-chain.service`. The `ampere_eq` sink must
  exist for a fresh setup. Check the selected desktop output and its volume.
- Empty library: verify the chosen directory, file permissions and Settings
  Rescan. Large initial scans take time.
- Missing artwork or local metadata: ensure Ampere and MPD use the same folder.
- Media keys: Ampere publishes `org.mpris.MediaPlayer2.ampere` on the desktop
  session bus; launch inside the desktop session, not a root shell.

## Upgrade and remove

Close Ampere before upgrading its environment. Reinstall the new wheel or
source with pip; do not rerun setup to replace your existing state.
Removing the virtual environment uninstalls application code. Remove only its
Ampere desktop entry/icon if desired. Keep MPD configuration, playlists,
listening history and EQ profiles unless you explicitly want to erase them.
