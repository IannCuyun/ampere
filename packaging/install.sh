#!/usr/bin/env bash
# Ampere v1.0.1 installer. Run as your desktop user, never with sudo bash.
set -euo pipefail

fail() { printf 'Ampere: %s\n' "$*" >&2; exit 1; }

select_packages() {
    case "$1" in
        arch|cachyos|endeavouros|manjaro)
            manager=pacman
            packages=(python mpd mpc ffmpeg pipewire libpulse curl)
            ;;
        ubuntu|linuxmint|pop|debian)
            case "$1:$2" in
                ubuntu:24.04|ubuntu:26.04|linuxmint:22*|pop:24.04|debian:13|debian:13.*) ;;
                *) fail "This release supports Ubuntu 24.04/26.04, Mint 22, Pop!_OS 24.04, Debian 13, and Arch-based desktops. Detected $1 $2." ;;
            esac
            manager=apt-get
            packages=(python3 python3-venv mpd mpc ffmpeg pipewire-bin pulseaudio-utils libegl1 libopengl0 libxcb-cursor0 curl)
            ;;
        *) fail "Unsupported distribution: $1. No changes made. See docs/INSTALL.md for manual setup." ;;
    esac
}

missing_packages() {
    missing=()
    local package status
    for package in "${packages[@]}"; do
        if [[ "$manager" == pacman ]]; then
            pacman -Q "$package" >/dev/null 2>&1 || missing+=("$package")
        else
            status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) || status=''
            [[ "$status" == 'install ok installed' ]] || missing+=("$package")
        fi
    done
}

install_packages() {
    ((${#missing[@]})) || return 0
    command -v sudo >/dev/null || fail 'sudo is required to install missing system dependencies.'
    if [[ "$manager" == pacman ]]; then
        # Use the existing repository database. Do not refresh it alone or
        # inspect/upgrade unrelated installed applications.
        sudo pacman -S --needed "${missing[@]}" || fail 'Could not install the required packages. See the package-manager error above; Ampere will not change system-update settings or force installation.'
    else
        sudo apt-get update
        sudo apt-get install --no-install-recommends --no-upgrade "${missing[@]}"
    fi
}

install_main() {
    local music='' skip_system=0 plan=0
    while (($#)); do
        case "$1" in
            --music-dir) (($# >= 2)) || fail '--music-dir needs a path'; music=$2; shift 2 ;;
            --skip-system) skip_system=1; shift ;;
            --dry-run) plan=1; shift ;;
            --help)
                printf '%s\n' 'Usage: install.sh [--music-dir PATH] [--skip-system] [--dry-run]' \
                    'Installs Ampere v1.0.1 for your desktop account. Prompts for a music folder.' \
                    '--skip-system: dependencies already installed; no sudo/package operations.' \
                    '--dry-run: show package plan without changing anything.'
                return ;;
            *) fail "Unknown option: $1" ;;
        esac
    done
    [[ $(uname -s) == Linux ]] || fail 'Linux is required.'
    [[ $(uname -m) == x86_64 ]] || fail 'This installer currently supports x86_64 only.'
    # /etc/os-release is OS-owned configuration, not downloaded input.
    local ID='' VERSION_ID=''
    . /etc/os-release
    local manager
    local -a packages missing
    select_packages "$ID" "$VERSION_ID"
    printf 'Ampere v1.0.1 — %s %s\n' "$ID" "$VERSION_ID"
    missing_packages
    printf 'System packages missing (%s): %s\n' "$manager" "${missing[*]:-none}"
    printf 'Application: %s/.local/share/ampere/venv\n' "$HOME"
    if ((plan)); then return; fi
    ((EUID != 0)) || fail 'Run as your normal desktop account. Only package installation uses sudo.'
    [[ -n ${DISPLAY:-}${WAYLAND_DISPLAY:-} ]] || fail 'Run from a terminal inside your graphical desktop session.'
    command -v systemctl >/dev/null || fail 'A systemd desktop is required.'
    systemctl --user show-environment >/dev/null || fail 'No systemd user session is available.'
    local destination="$HOME/.local/share/ampere/venv"
    # Never mutate an existing install or custom MPD state during first setup.
    if [[ -e "$destination" || -L "$destination" ]]; then
        if [[ -x "$destination/bin/ampere" ]]; then
            "$destination/bin/ampere-setup" --doctor || fail 'Existing installation needs attention; share the diagnostic output.'
            printf 'Ampere is already installed. Open Ampere from your application menu.\n' 
            return
        fi
        fail "An incomplete environment exists at $destination. Preserve it and inspect before retrying."
    fi
    [[ ! -e "$HOME/.config/mpd/mpd.conf" && ! -L "$HOME/.config/mpd/mpd.conf" ]] || fail 'An MPD configuration already exists. Use manual setup to preserve your existing player.'
    [[ ! -e "$HOME/.local/share/applications/ampere.desktop" ]] || fail 'An Ampere launcher already exists. Use manual setup for this installation.'
    if [[ -z "$music" ]]; then
        [[ -r /dev/tty ]] || fail 'No terminal for music selection. Supply --music-dir /path/to/music.'
        printf 'Music folder (Enter for %s/Music): ' "$HOME" > /dev/tty
        IFS= read -r music < /dev/tty || fail 'Music folder selection cancelled.'
        music=${music:-"$HOME/Music"}
    fi
    if [[ "$music" == '~/'* ]]; then music="$HOME/${music:2}"; fi
    [[ -d "$music" && -r "$music" ]] || fail "Music folder does not exist or is unreadable: $music"
    if systemctl is-active --quiet mpd.service; then
        fail 'A system-wide MPD service is already running. Keep it intact and use manual setup to resolve the port conflict.'
    fi
    local had_mpd=0
    command -v mpd >/dev/null && had_mpd=1
    if ((!skip_system)); then
        # A working audio session is a desktop prerequisite, not permission
        # to install or replace the user's sound server/session manager.
        local audio_unit
        for audio_unit in pipewire.service pipewire-pulse.service; do
            systemctl --user is-active --quiet "$audio_unit" || fail 'A running PipeWire + pipewire-pulse desktop is required. No audio stack will be installed or replaced.'
        done
        if ((${#missing[@]})); then install_packages < /dev/tty; fi
        if [[ "$manager" == apt-get ]]; then
            # Debian packages can auto-start a system MPD on the port reserved
            # for the desktop player. Never stop a pre-existing installation.
            if ((had_mpd == 0)); then
                printf 'Disabling the newly installed system MPD; Ampere uses your user service.\n'
                local system_unit
                for system_unit in mpd.service mpd.socket; do
                    if systemctl cat "$system_unit" >/dev/null 2>&1; then
                        sudo systemctl disable --now "$system_unit"
                    fi
                done
            fi
        fi
    fi
    python3 -c 'import sys; assert (3,12) <= sys.version_info[:2] <= (3,14), "Python 3.12–3.14 required"' || fail 'Unsupported Python runtime.'
    # Do not replace a working PulseAudio desktop or restart live audio.
    pactl info | grep -qi pipewire || fail 'A running PipeWire audio session is required. Configure your desktop audio separately, then rerun.'
    local temp_dir
    temp_dir=$(mktemp -d)
    local setup_done=0 env_created=0
    trap 'rm -rf -- "$temp_dir"; if ((env_created && !setup_done)); then rm -rf -- "$destination"; fi' EXIT
    local wheel=ampere_player-1.0.1-py3-none-any.whl
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
        "https://github.com/IannCuyun/ampere/releases/download/v1.0.1/$wheel" -o "$temp_dir/$wheel"
    printf '%s  %s\n' 1e16c2c5f21dc719a5830541bc67b2d2504be75c083b66d01e5ca98b1a3de700 "$temp_dir/$wheel" | sha256sum --check -
    mkdir -p "$(dirname "$destination")"
    # Keep the environment at its final path: Python entrypoints embed it.
    env_created=1
    python3 -m venv "$destination"
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
        'https://github.com/IannCuyun/ampere/releases/download/v1.0.1/requirements.lock' -o "$temp_dir/requirements.lock"
    printf '%s  %s\n' 61520338e865a2e4be5b0bce268a65408f558cece25a48ba16e340f4d1111287 "$temp_dir/requirements.lock" | sha256sum --check -
    "$destination/bin/pip" install -c "$temp_dir/requirements.lock" "$temp_dir/$wheel"
    "$destination/bin/ampere-setup" --music-dir "$music" --dry-run
    "$destination/bin/ampere-setup" --music-dir "$music"
    setup_done=1
    local unit
    for unit in mpd.service filter-chain.service; do
        if ! systemctl --user cat "$unit" >/dev/null 2>&1; then
            mkdir -p "$HOME/.config/systemd/user"
            # No-clobber also protects masked units and concurrent installs.
            (set -o noclobber; cat "$destination/share/ampere/systemd/$unit" > "$HOME/.config/systemd/user/$unit")
        fi
    done
    systemctl --user daemon-reload
    if ! "$destination/bin/ampere-setup" --doctor; then
        fail 'Application installed, but a desktop prerequisite needs attention. Share the diagnostic output; do not delete existing configuration.'
    fi
    printf '\nInstalled. Open Ampere from your application menu, then Settings → Rescan.\n'
    rm -rf -- "$temp_dir"
    trap - EXIT
}

# Sourcing allows contract tests without running installation.
if [[ ${BASH_SOURCE[0]:-} == "$0" || -z ${BASH_SOURCE[0]:-} ]]; then
    install_main "$@"
fi
