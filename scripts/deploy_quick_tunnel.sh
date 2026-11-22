#!/bin/bash
set -euo pipefail
umask 077

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
root=$(dirname -- "$(dirname -- "$(realpath "$0")")")
state=${ARGUS_QUICK_DIR:-"$HOME/.firstmate-secondmate-hacklab/data/argus-live-fix/quick-tunnel"}
port=${ARGUS_QUICK_PORT:-18180}
label=dev.caniberk.argus.quick
domain=gui/$(id -u)
web=https://argus-eye.pages.dev

fail() { printf '%s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = --install ]; then
  [ "$#" -eq 2 ] || fail "Use --install /absolute/path/to/bench."
  [ -s "$2/scorecard.json" ] || fail "Run the bench gate first and pass its output directory."
  if launchctl print "$domain/$label" >/dev/null 2>&1; then
    fail "Stop $label before installing an updated release."
  fi
  [ -z "$(git -C "$root" status --porcelain)" ] || fail "Commit the tested release first."
  mkdir -p "$state/releases" "$HOME/Library/LaunchAgents"
  state=$(realpath "$state")
  sha=$(git -C "$root" rev-parse HEAD)
  release="$state/releases/$sha"
  if [ ! -d "$release" ]; then
    staging=$(mktemp -d "$state/releases/.$sha.XXXXXXXX")
    git -C "$root" archive "$sha" | tar -x -C "$staging"
    mv "$staging" "$release"
  fi
  bench="$release/runs/bench"
  mkdir -p "$bench"
  cp "$2/scorecard.json" "$bench/scorecard.json"
  ( cd "$release" && uv sync --frozen )
  env -i HOME="$HOME" PATH="$PATH" npm --prefix "$release/web" ci --no-audit --no-fund
  if [ ! -f "$release/world/world.duckdb" ]; then
    world=$(mktemp -d "$release/world.XXXXXXXX")
    env -i HOME="$HOME" PATH="$PATH" "$release/.venv/bin/mockmart" generate --scenario s1 --seed 1 --out "$world"
    mv "$world" "$release/world"
  fi
  plist="$HOME/Library/LaunchAgents/$label.plist"
  if [ -e "$plist" ] || [ -L "$plist" ]; then
    [ "$(readlink "$plist" || true)" = "$state/$label.plist" ] || fail "Existing LaunchAgent needs review: $plist"
  else
    ln -s "$state/$label.plist" "$plist"
  fi
  python3 - "$state" "$release" "$label" "$port" "$sha" <<'PY'
import plistlib
import sys
from pathlib import Path

state, release, label, port, sha = sys.argv[1:]
path = Path(state) / f"{label}.plist"
config = dict(
    Label=label,
    ProgramArguments=["/bin/bash", f"{release}/scripts/deploy_quick_tunnel.sh", "--run", sha],
    WorkingDirectory=release,
    EnvironmentVariables={"ARGUS_QUICK_DIR": state, "ARGUS_QUICK_PORT": port},
    StandardOutPath=f"{state}/deploy.log",
    StandardErrorPath=f"{state}/deploy.log",
    KeepAlive=True,
    ThrottleInterval=30,
)
with path.open("wb") as output:
    plistlib.dump(config, output)
PY
  exec launchctl bootstrap "$domain" "$plist"
fi

[ "${1:-}" = --run ] && [ "$#" -eq 2 ] || fail "Use --install /absolute/path/to/bench."
sha=$2
mkdir -p "$state/api-home" "$state/tunnel-home"
api_pid=
tunnel_pid=
cleanup() {
  for pid in "$api_pid" "$tunnel_pid"; do
    if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; fi
  done
  wait || true
}
trap cleanup EXIT
trap 'exit 0' TERM INT

loopback="http://127.0.0.1:$port"
env -i HOME="$state/api-home" PATH="$PATH" ARGUS_DISABLE_PROVIDER=1 \
  "$root/.venv/bin/python" "$root/scripts/cloudflare_api.py" --port "$port" \
  --world "$root/world/world.duckdb" > "$state/api.log" 2>&1 &
api_pid=$!

health() {
  curl -fsS --max-time 5 -H "Origin: $web" "$1/health" | jq -e '.status == "ok" and .mode == "live"' >/dev/null
}

for ((attempt=0; attempt<30; attempt++)); do
  kill -0 "$api_pid" || fail "Argus API exited. See $state/api.log."
  if health "$loopback"; then break; fi
  sleep 1
done
health "$loopback" || fail "Argus API did not come up."
pace_shop() {
  curl -fsS --max-time 5 -H 'Content-Type: application/json' -d "{\"speed\":$1}" "$loopback/replay" >/dev/null
}
pace_shop 8

env -i HOME="$state/tunnel-home" PATH="$PATH" cloudflared tunnel --no-autoupdate --url "$loopback" > "$state/tunnel.log" 2>&1 &
tunnel_pid=$!
api=
for ((attempt=0; attempt<45; attempt++)); do
  kill -0 "$tunnel_pid" || fail "Quick Tunnel exited. See $state/tunnel.log."
  api=$(rg -m 1 -o 'https://[a-z0-9-]+\.trycloudflare\.com' "$state/tunnel.log" || true)
  if [ -n "$api" ] && health "$api"; then break; fi
  sleep 2
done
[ -n "$api" ] && health "$api" || fail "Quick Tunnel did not expose the live API."
curl -fsS --max-time 10 -H "Origin: $web" -D "$state/health.headers" "$api/events/snapshot" |
  jq -e '.mode == "live" and (.stream | length > 0)' >/dev/null
tr -d '\r' < "$state/health.headers" | rg -qi '^access-control-allow-origin: https://argus-eye\.pages\.dev$'

dist="$state/dist"
env -i HOME="$HOME" PATH="$PATH" VITE_ARGUS_API_URL="$api" VITE_ARGUS_PUBLIC_API=1 VITE_ARGUS_POLL_EVENTS=1 \
  npm --prefix "$root/web" run build -- --outDir "$dist" --emptyOutDir
scan=0
rg --files-with-matches --hidden --no-ignore -e \
  'sk-ant-[A-Za-z0-9_-]{16,}|sk-(proj-|svcacct-)?[A-Za-z0-9_-]{32,}|(ANTHROPIC|OPENAI)_API_KEY[[:blank:]]*[:=][[:blank:]"\x27]*[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
  "$dist" || scan=$?
[ "$scan" -eq 1 ] || fail "Static asset secret scan failed."
incident_ready() {
  curl -fsS --max-time 5 "$loopback/incidents" | jq -e 'length > 0' >/dev/null
}
for ((attempt=0; attempt<45; attempt++)); do
  if incident_ready; then break; fi
  sleep 2
done
incident_ready || fail "The live Shop did not file its S1 incident."
pace_shop 1
health "$api" || fail "Quick Tunnel stopped answering before publish."

commit_dirty=false
if [ -f "$root/web/.argus-pages-overlay" ]; then commit_dirty=true; fi
CI=1 WRANGLER_LOG_PATH="$state/wrangler.log" CLOUDFLARE_ACCOUNT_ID=c452dd4753dd99c4d03eec47380d0470 \
  wrangler pages deploy "$dist" --cwd "$state" --project-name argus-eye --branch main \
  --commit-hash "$sha" --commit-message "Deploy Argus $sha" --commit-dirty="$commit_dirty"
printf '%s\n' "$api" > "$state/api-url.new"
mv "$state/api-url.new" "$state/api-url"
printf 'Published %s with %s\n' "$web" "$api"

misses=0
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$tunnel_pid" 2>/dev/null && [ "$misses" -lt 3 ]; do
  sleep 15
  if health "$api"; then misses=0; else misses=$((misses + 1)); fi
done
fail "The live API became unavailable. launchd will restart the API and Quick Tunnel."
