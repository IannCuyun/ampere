#!/usr/bin/env bash
# Only for a disposable GitHub-hosted runner; never run against a listening session.
set -euo pipefail
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_ENVIRONMENT:-} != github-hosted ]]; then
  echo 'Refusing: this test requires a disposable GitHub-hosted runner.' >&2
  exit 2
fi
export QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
sudo systemctl stop mpd.service mpd.socket || true
sudo loginctl enable-linger "$USER"
sudo systemctl start "user@$(id -u).service"
mkdir -p "$HOME/.config/systemd/user" "$RUNNER_TEMP/ampere-music"
cp -n packaging/systemd/mpd.service packaging/systemd/filter-chain.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user start pipewire.service pipewire-pulse.service wireplumber.service
for attempt in {1..60}; do
  if pactl info >/dev/null 2>&1; then break; fi
  sleep 0.5
done
pactl load-module module-null-sink sink_name=ampere-test-output
for attempt in {1..60}; do
  if pactl set-default-sink ampere-test-output 2>/dev/null; then break; fi
  sleep 0.5
done
pactl set-default-sink ampere-test-output
python - <<'PY'
import math, os, struct, wave
from pathlib import Path
path = Path(os.environ['RUNNER_TEMP']) / 'ampere-music' / 'Test tone.wav'
with wave.open(str(path), 'wb') as f:
    f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
    second = b''.join(struct.pack('<h', int(2000*math.sin(2*math.pi*440*i/8000))) for i in range(8000))
    f.writeframes(second * 60)
PY
ampere-setup --music-dir "$RUNNER_TEMP/ampere-music"
ampere-setup --music-dir "$RUNNER_TEMP/ampere-music"
ampere-setup --doctor
ampere > "$RUNNER_TEMP/ampere-startup.log" 2>&1 &
app_pid=$!
cleanup() {
  kill -TERM "$app_pid" 2>/dev/null || true
  cat "$RUNNER_TEMP/ampere-startup.log" || true
  journalctl --user -u mpd.service -u filter-chain.service -n 50 --no-pager || true
}
trap cleanup EXIT
for attempt in {1..60}; do
  if mpc -h 127.0.0.1 status >/dev/null 2>&1 && pactl list short sinks | grep -q ampere_eq; then break; fi
  kill -0 "$app_pid"
  sleep 0.5
done
systemctl --user is-active mpd.service filter-chain.service
mpc -h 127.0.0.1 update --wait
mpc -h 127.0.0.1 add 'Test tone.wav'
mpc -h 127.0.0.1 play
sleep 2
pactl list short sinks
pactl list short sink-inputs
# Confirm the MPD stream is routed into the actual Ampere EQ sink.
python - <<'PY'
import json, subprocess
sinks = json.loads(subprocess.check_output(['pactl','-f','json','list','sinks']))
inputs = json.loads(subprocess.check_output(['pactl','-f','json','list','sink-inputs']))
eq = next(s['index'] for s in sinks if s['name'] == 'ampere_eq')
assert any(s['sink'] == eq for s in inputs), 'No playback stream reaches Ampere EQ'
print('EQ_ROUTING_OK')
PY
dbus-send --session --print-reply --dest=org.mpris.MediaPlayer2.ampere /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get string:org.mpris.MediaPlayer2.Player string:PlaybackStatus | tee "$RUNNER_TEMP/mpris-before.log"
grep -q Playing "$RUNNER_TEMP/mpris-before.log"
dbus-send --session --print-reply --dest=org.mpris.MediaPlayer2.ampere /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Pause
sleep 1
dbus-send --session --print-reply --dest=org.mpris.MediaPlayer2.ampere /org/mpris/MediaPlayer2 org.freedesktop.DBus.Properties.Get string:org.mpris.MediaPlayer2.Player string:PlaybackStatus | tee "$RUNNER_TEMP/mpris-after.log"
grep -q Paused "$RUNNER_TEMP/mpris-after.log"
kill -TERM "$app_pid"
for attempt in {1..40}; do
  if ! kill -0 "$app_pid" 2>/dev/null; then break; fi
  sleep 0.5
done
if kill -0 "$app_pid" 2>/dev/null; then echo 'Application shutdown timed out'; exit 1; fi
wait "$app_pid"
if systemctl --user is-active --quiet mpd.service; then echo 'MPD still active after app shutdown'; exit 1; fi
if grep -q 'QQmlApplicationEngine failed\|Traceback (most recent call last)' "$RUNNER_TEMP/ampere-startup.log"; then exit 1; fi
echo 'REAL_USER_SERVICE_PLAYBACK_AND_SHUTDOWN_OK'
