# Install Ampere on Linux

## One-command installation

Run this from a terminal in your normal graphical desktop account (not as root):

```sh
curl -fsSL https://github.com/IannCuyun/ampere/releases/download/v1.0.1/install.sh | bash
```

The installer asks for your existing music folder and your sudo password for
system packages. Review package-manager prompts. It verifies the v1.0.1 wheel
and pinned dependency list with embedded SHA256 checksums, installs an isolated
Python environment, creates the menu launcher, adds missing user units without
overwriting them, and runs diagnostics. Open **Ampere → Settings → Rescan**
after installation. It does not launch the player or restart your audio session.

For a custom folder or to inspect the script first:

```sh
curl -fLO https://github.com/IannCuyun/ampere/releases/download/v1.0.1/install.sh
bash install.sh --dry-run
bash install.sh --music-dir "/path/to/music"
```

Installer targets (x86_64, systemd desktop, running PipeWire audio):

- CachyOS, Arch, EndeavourOS and Manjaro with Python 3.12–3.14.
- Ubuntu 24.04/26.04, Mint 22.x, Pop!_OS 24.04 and Debian 13.

Distro selection and failure behavior are automated-test covered. The app's
Ubuntu 24.04 desktop integration and local CachyOS runtime have been checked;
end-to-end installer runs on every listed distribution are not yet certified.
Fedora, openSUSE, older Debian/Ubuntu, ARM, non-systemd desktops and PulseAudio-only
sessions are not supported by this installer. It stops on unsupported systems.

Only missing packages are requested. No full system update is performed. On Arch,
pending updates or stale repository data require your normal system update
separately; Ampere never refreshes Arch databases alone. Apt recommendations are
disabled. An existing PipeWire desktop is required; the installer does not replace
your audio server or session manager. Existing custom MPD
configuration or a running system MPD blocks automatic setup to preserve it.
On a fresh apt installation only, the newly added system MPD service is disabled
because Ampere manages a user service instead. 

Repeated runs check an existing installation without overwriting it. This is a
Version 1 first-install command, not an automatic upgrade command. If diagnostics
fail after setup, preserve the output and use the troubleshooting section below.

## Manual installation

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
