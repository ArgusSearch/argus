#!/bin/bash
set -euo pipefail
umask 077

bin=$(dirname -- "$(realpath "$0")")
state=${ARGUS_DEPLOY_DIR:-"$HOME/.firstmate-secondmate-hacklab/data/argus-deploy/production"}
repo=https://github.com/ArgusSearch/argus.git
github=ArgusSearch/argus
project=argus-eye
web=https://argus.caniberk.dev
api=https://argus-api.caniberk.dev
port=18080
tunnel=argus-api
label=dev.caniberk.argus
domain=gui/$(id -u)
cluster="$state/tunnel"
cert=${TUNNEL_ORIGIN_CERT:-"$HOME/.cloudflared/cert.pem"}
mode=${1:---watch}
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export CI=1 WRANGLER_LOG_PATH="$state/wrangler.log" CLOUDFLARE_ACCOUNT_ID=c452dd4753dd99c4d03eec47380d0470

fail() { printf '%s\n' "$*" >&2; exit 1; }
usage() { fail "Use --go, --go --attach-web, --watch, --web-only or --rollback."; }

if [ "$#" -gt 1 ]; then
  [ "$#" -eq 2 ] && [ "$1" = --go ] && [ "$2" = --attach-web ] || usage
  exec python3 "$bin/cloudflare_pages.py" web-domain --go
fi

case "$mode" in --go|--watch|--web-only|--rollback|--serve) ;; *) usage ;; esac
mkdir -p "$state" "$state/releases"

if [ "$mode" = --serve ]; then
  release=$(realpath "$state/current")
  world="$state/worlds/${release##*/}/world.duckdb"
  args=(--port "$port")
  if [ -f "$world" ] && [ ! -f "$state/replay-only" ]; then args+=(--world "$world"); fi
  origin="$release/scripts/cloudflare_api.py"
  if [ ! -f "$origin" ]; then origin="$bin/cloudflare_api.py"; fi
  mkdir -p "$state/api-home"
  builtin cd "$release"
  exec env -i HOME="$state/api-home" PATH=/usr/bin:/bin:/opt/homebrew/bin \
    ARGUS_DISABLE_PROVIDER=1 "$release/.venv/bin/python" "$origin" "${args[@]}"
fi

if [ "${ARGUS_DEPLOY_LOCKED:-}" != "$state" ]; then
  exec python3 - "$state" "$bin/deploy_cloudflare.sh" "$mode" <<'PY'
import fcntl
import os
import sys
from pathlib import Path

state, script, mode = sys.argv[1:]
with (Path(state) / "deploy.lock").open("a") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another Argus deployment is running.") from None
    os.set_inheritable(lock.fileno(), True)
    os.environ["ARGUS_DEPLOY_LOCKED"] = state
    os.execv("/bin/bash", ["/bin/bash", script, mode])
PY
fi

green() {
  git -C "$state/upstream" fetch --quiet origin +refs/heads/main:refs/remotes/origin/main || fail "Git fetch failed."
  sha=$(git -C "$state/upstream" rev-parse refs/remotes/origin/main) || fail "Missing origin/main."
  result=$(gh-axi api "repos/$github/actions/workflows/ci.yml/runs?branch=main&event=push&head_sha=$sha&per_page=20" \
    --jq '.workflow_runs[0] | [.status, .conclusion, .html_url] | @tsv') || fail "GitHub CI lookup failed."
  case "$result" in
    $'completed\tsuccess\t'*) return 0 ;;
    *) printf 'Waiting for successful CI for %s (%s)\n' "$sha" "${result:-no run yet}"; return 1 ;;
  esac
}

prepare() {
  release="$state/releases/$sha"
  if [ ! -d "$release/.git" ]; then
    local checkout
    checkout=$(mktemp -d "$state/releases/.$sha.XXXXXXXX")
    git clone --quiet --shared --no-checkout "$state/upstream" "$checkout"
    git -C "$checkout" checkout --quiet --detach "$sha"
    mv "$checkout" "$release"
  fi
  [ "$(git -C "$release" rev-parse HEAD)" = "$sha" ] || fail "Unexpected release checkout $release."
  [ -z "$(git -C "$release" status --porcelain)" ] || fail "Release checkout has local changes."
  [ ! -e "$release/.env" ] || fail "Remove the private .env from the deployment checkout before continuing."
}

scan() {
  local status=0
  rg --files-with-matches --hidden --no-ignore -e \
    'sk-ant-[A-Za-z0-9_-]{16,}|sk-(proj-|svcacct-)?[A-Za-z0-9_-]{32,}|(ANTHROPIC|OPENAI)_API_KEY[[:blank:]]*[:=][[:blank:]"\x27]*[A-Za-z0-9_-]{20,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' \
    "$1" || status=$?
  [ "$status" -eq 1 ] || fail "Static asset secret scan failed for $1."
}

build_web() {
  local offline=$1 source=$release base
  if [ ! -f "$release/web/src/lib/deployment.ts" ]; then
    if [ "$bin" != "$state/runner" ]; then
      base=$(git -C "$bin/.." merge-base HEAD origin/main)
      git -C "$bin/.." diff --binary "$base" HEAD -- web > "$state/web-hook.patch.new"
      mv "$state/web-hook.patch.new" "$state/web-hook.patch"
    fi
    [ -s "$state/web-hook.patch" ] || fail "The web deployment hook is missing."
    # The first main release may predate the hook. Patch a build copy and leave the API clone clean.
    source=$(mktemp -d "$state/web-source.XXXXXXXX")
    git -C "$release" archive HEAD | tar -x -C "$source"
    GIT_CEILING_DIRECTORIES="$state" git -C "$source" apply --no-index "$state/web-hook.patch"
  fi
  env -i HOME="$HOME" PATH="$PATH" npm --prefix "$source/web" ci --no-audit --no-fund
  env -i HOME="$HOME" PATH="$PATH" VITE_ARGUS_API_URL="$api" VITE_ARGUS_STATIC_REPLAY="$offline" \
    npm --prefix "$source/web" run build -- --outDir "$dist" --emptyOutDir
  scan "$dist"
}

publish() {
  local patched=false
  if [ ! -f "$state/releases/$2/web/src/lib/deployment.ts" ]; then patched=true; fi
  GIT_DIR="$state/upstream/.git" wrangler pages deploy "$1" --cwd "$state" --project-name "$project" --branch main \
    --commit-hash "$2" --commit-message "Deploy Argus $2" --commit-dirty="$patched"
}

request() { curl -fsS --retry 5 --retry-delay 4 --retry-all-errors --retry-max-time 90 --max-time 25 "$@"; }

smoke_web() {
  request "$1/?demo=1" > "$state/demo-smoke.html" && rg -q '<div id="root">' "$state/demo-smoke.html"
}

smoke() {
  request -H "Origin: $web" -D "$state/health.headers" "$api/health" > "$state/health.json" &&
    jq -e '.status == "ok" and (.mode == "live" or .mode == "replay")' "$state/health.json" >/dev/null &&
    tr -d '\r' < "$state/health.headers" | rg -qi '^access-control-allow-origin: https://argus\.caniberk\.dev$' &&
    request "$api/graph" > "$state/graph.json" && jq -e '.nodes | length > 0' "$state/graph.json" >/dev/null &&
    smoke_web "$web"
}

link_release() {
  python3 - "$state" "$1" <<'PY'
import os
import sys
from pathlib import Path

state, release = map(Path, sys.argv[1:])
temp = state / "current.new"
temp.unlink(missing_ok=True)
temp.symlink_to(release, target_is_directory=True)
os.replace(temp, state / "current")
PY
}

load_job() {
  local job=$1
  if ! launchctl print "$domain/$label.$job" >/dev/null 2>&1; then
    launchctl bootstrap "$domain" "$state/$label.$job.plist"
  fi
}

install_jobs() {
  mkdir -p "$state/runner" "$state/logs"
  if [ "$bin" != "$state/runner" ]; then
    for file in deploy_cloudflare.sh cloudflare_api.py cloudflare_pages.py; do
      cp "$bin/$file" "$state/runner/$file.new"
      mv "$state/runner/$file.new" "$state/runner/$file"
    done
  fi
  python3 - "$state" "$label" "$(command -v cloudflared)" "$PATH" <<'PY'
import plistlib
import sys
from pathlib import Path

state, label, cloudflared, path = sys.argv[1:]
root = Path(state)
script = str(root / "runner" / "deploy_cloudflare.sh")
jobs = {
    "api": (["/bin/bash", script, "--serve"], {"KeepAlive": True}),
    "tunnel": ([cloudflared, "tunnel", "--config", str(root / "tunnel" / "config.yml"),
                "--no-autoupdate", "run", "argus-api"], {"KeepAlive": True}),
    "deploy": (["/bin/bash", script, "--watch"], {"StartInterval": 300}),
}
for job, (command, settings) in jobs.items():
    name = f"{label}.{job}"
    config = dict(
        Label=name, ProgramArguments=command, WorkingDirectory=state,
        EnvironmentVariables={"PATH": path, "ARGUS_DEPLOY_DIR": state},
        StandardOutPath=str(root / "logs" / f"{job}.out.log"),
        StandardErrorPath=str(root / "logs" / f"{job}.err.log"), **settings,
    )
    with (root / f"{name}.plist").open("wb") as output:
        plistlib.dump(config, output)
PY
}

persist_jobs() {
  local job path plist
  mkdir -p "$HOME/Library/LaunchAgents"
  for job in api tunnel deploy; do
    plist="$label.$job.plist"
    path="$HOME/Library/LaunchAgents/$plist"
    if [ "$(readlink "$path" 2>/dev/null || true)" != "$state/$plist" ]; then
      ln -s "$state/$plist" "$path" || fail "Existing LaunchAgent needs review: $path"
    fi
  done
}

configure_tunnel() {
  [ -r "$cert" ] || fail "Authorize the Cloudflare zone with cloudflared tunnel login first."
  mkdir -p "$cluster"
  local tunnels id dns
  tunnels=$(cloudflared tunnel --origincert "$cert" list --name "$tunnel" --output json)
  id=$(jq -r --arg name "$tunnel" '[.[] | select(.name == $name)][0].id // empty' <<< "$tunnels")
  if [ -n "$id" ] && [ ! -s "$cluster/credentials.json" ]; then
    fail "The named tunnel exists but its connector credentials are missing from $cluster."
  fi
  dns=$(python3 "$bin/cloudflare_pages.py" preflight ${id:+"$id"})
  printf '%s\n' "$dns"
  if [ -z "$id" ]; then
    cloudflared tunnel --origincert "$cert" create --credentials-file "$cluster/credentials.json" "$tunnel"
    id=$(jq -er '.TunnelID' "$cluster/credentials.json")
  fi
  [ "$(jq -er '.TunnelID' "$cluster/credentials.json")" = "$id" ] || fail "Wrong tunnel credentials."
  cat > "$cluster/config.yml" <<EOF
tunnel: $id
credentials-file: "$cluster/credentials.json"
ingress:
  - hostname: argus-api.caniberk.dev
    service: http://127.0.0.1:$port
  - service: http_status:404
EOF
  cloudflared tunnel --config "$cluster/config.yml" ingress validate
  if [[ "$dns" == *API_CNAME_MISSING ]]; then
    cloudflared tunnel --origincert "$cert" route dns "$tunnel" argus-api.caniberk.dev
  fi
  python3 "$bin/cloudflare_pages.py" web-domain --go
}

restart_api() { launchctl kickstart -k "$domain/$label.api"; }

check_local_api() {
  local service_pid
  request "http://127.0.0.1:$port/health" > "$state/local-health.json" &&
    jq -e '.status == "ok" and (.mode == "live" or .mode == "replay")' "$state/local-health.json" >/dev/null || return 1
  service_pid=$(launchctl print "$domain/$label.api" | awk '$1 == "pid" && $2 == "=" { print $3 }')
  [ -n "$service_pid" ] && [ "$(lsof -nP -t -iTCP:"$port" -sTCP:LISTEN)" = "$service_pid" ]
}

deployed="$state/deployed"
old=$(cat "$deployed" 2>/dev/null || true)
if [ "$mode" = --rollback ]; then
  sha=$(cat "$state/previous")
  prepare
  dist="$state/assets/$sha"
  scan "$dist"
  link_release "$release"
  restart_api
  check_local_api || fail "The prior release did not bind the Argus API port."
  publish "$dist" "$sha"
  smoke || fail "Rollback smoke test failed. Inspect the Argus service logs."
  printf '%s\n' "$sha" > "$deployed"
  exit
fi

if [ ! -d "$state/upstream/.git" ]; then git clone --quiet --no-checkout "$repo" "$state/upstream"; fi
if ! green; then
  [ "$mode" = --watch ] && exit 0
  fail "The current origin/main is not green yet."
fi
[ "$mode" != --watch ] || [ "$old" != "$sha" ] || exit 0
prepare

if [ "$mode" = --web-only ]; then
  dist="$state/assets/$sha-static"
  pages=$(python3 "$bin/cloudflare_pages.py" project)
  build_web 1
  publish "$dist" "$sha"
  smoke_web "https://$pages"
  exit
fi

dist="$state/assets/$sha"
build_web 0
( cd "$release" && uv sync --frozen )
world="$state/worlds/$sha"
if [ ! -f "$world/world.duckdb" ]; then
  mkdir -p "$state/worlds"
  staging=$(mktemp -d "$state/worlds/.$sha.XXXXXXXX")
  ( cd "$release" && .venv/bin/mockmart generate --scenario s1 --seed 1 --out "$staging" )
  mv "$staging" "$world"
fi
if [ "$mode" = --go ]; then
  python3 "$bin/cloudflare_pages.py" project
  configure_tunnel
  install_jobs
fi
link_release "$release"
load_job api
deploy_candidate() {
  restart_api && check_local_api || return 1
  if [ "$mode" = --go ]; then load_job tunnel || return 1; fi
  publish "$dist" "$sha" || return 1
  if [ "$mode" = --go ]; then
    persist_jobs && load_job deploy || return 1
  fi
  smoke
}
if deploy_candidate; then
  if [ -n "$old" ] && [ "$old" != "$sha" ]; then printf '%s\n' "$old" > "$state/previous"; fi
  printf '%s\n' "$sha" > "$deployed.new"
  mv "$deployed.new" "$deployed"
else
  if [ -n "$old" ] && [ "$old" != "$sha" ]; then
    link_release "$state/releases/$old"
    restart_api
    publish "$state/assets/$old" "$old"
  fi
  fail "Argus deployment did not pass smoke tests. Inspect $state/logs and $state/wrangler.log."
fi
