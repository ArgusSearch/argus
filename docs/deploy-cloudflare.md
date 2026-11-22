# Argus on Cloudflare

Cloudflare Pages project `argus-eye` serves Mission Control at [argus-eye.pages.dev](https://argus-eye.pages.dev). The permanent setup runs the API on the Studio at `127.0.0.1:18080` behind the named tunnel `argus-api`. [Argus custom domain](https://argus.caniberk.dev), [API health](https://argus-api.caniberk.dev/health).

## Interim quick tunnel

On the Studio, run the release gates from a clean, committed checkout. Use its bench output when you install the interim LaunchAgent.

```sh
make web
ARGUS_DISABLE_PROVIDER=1 make s1
ARGUS_DISABLE_PROVIDER=1 make bench
./scripts/deploy_quick_tunnel.sh --install "$PWD/runs/bench"
```

The machine needs a macOS GUI login, authenticated Wrangler with Pages access, Cloudflared, Node/npm, `uv`, Python, `curl`, `jq` and `rg`. The script exports the committed release into the task state directory, generates the S1 Shop world, and starts a supervised loopback API on port 18180. The API starts with an allowlisted environment and provider access disabled. The simulator moves quickly through its opening quiet hours. Once it has filed the first incident, the job restores normal speed and uploads the scanned build directly to the `main` production deployment of Pages.

The temporary hostname changes whenever the job restarts. The LaunchAgent restarts the API and tunnel together and publishes a fresh build with the new hostname. Reload an open tab after the new deployment to pick up the URL. Cloudflare Quick Tunnels buffer event streams, so the interim build polls bounded event pages using the same sequence and stream IDs as the named tunnel's SSE connection. [Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

Default job state, logs, and the active `api-url` file are in `~/.firstmate-secondmate-hacklab/data/argus-live-fix/quick-tunnel/`. Stop the interim job with `launchctl bootout "gui/$(id -u)/dev.caniberk.argus.quick"` before installing an updated interim release or switching to the named tunnel. For the permanent cutover, also remove the `dev.caniberk.argus.quick.plist` symlink from `~/Library/LaunchAgents` so the interim deployment does not resume at login.

Opening the live site shows the Batu operator entry and then the workspace overview. The Shop data comes from a running simulation. The proof link opens the sealed result. The S1 recording URL `/?demo=1&captions=1&fx=1` uses its own event stream. The S4 recording starts at `/?fx=1&agentdemo=s4&agentspeed=2`.

## Activate on the Studio

1. A Cloudflare super administrator runs `cloudflared tunnel login` on the Studio and selects `caniberk.dev`. The command saves `~/.cloudflared/cert.pem`.
2. Set `CLOUDFLARE_API_TOKEN` in the invoking shell, using a token scoped to the owning account with **Account → Cloudflare Pages → Edit**, and to `caniberk.dev` with **Zone → Zone → Read** and **Zone → DNS → Edit**. The script needs DNS listing as well as creation, and the Wrangler OAuth login alone returns HTTP 403 for listing. Use a shell secret prompt or password manager and keep the token out of the command history.
3. From the checkout containing this package, run `./scripts/deploy_cloudflare.sh --go`. The script requires a successful push CI run for `origin/main`. If that revision predates the API URL hook, it applies the hook to a web build copy. The Studio needs `git`, `gh-axi`, `wrangler`, `cloudflared`, Node/npm, `uv`, `python3`, `curl`, `jq`, `rg`, and an active macOS GUI login. Confirm `gh-axi` and Wrangler are logged in as the deployment user.

The script lists DNS at both exact names first and refuses conflicting records. It runs `cloudflared tunnel route dns argus-api argus-api.caniberk.dev` when the API record is absent. Pages registers `argus.caniberk.dev` on the project and creates its proxied CNAME to `argus-eye.pages.dev` if Pages did not add it automatically. To attach only that web name with the same scoped token, run `./scripts/deploy_cloudflare.sh --go --attach-web`.

## Runtime and checks

- `dev.caniberk.argus.api` runs Uvicorn from a clean, detached clone of the checked-out green SHA. It generates a separate MockMart world per release. The overview uses that live simulation. The guided demo and case-scoped Ask and approvals use the sealed presentation. Recorded approval sets the presentation's decision, and the checked-in live simulator executor targets the generated DuckDB world. No provider credentials or customer connections are configured.
- `dev.caniberk.argus.tunnel` runs `cloudflared` with its own configuration and connector credentials. Its ingress is limited to `argus-api.caniberk.dev`. `dev.caniberk.argus.deploy` checks `origin/main` CI every five minutes and deploys a new SHA after successful CI. The deployment builds with `VITE_ARGUS_API_URL=https://argus-api.caniberk.dev`, scans assets for credential patterns, checks CORS and `/health`, reads `/graph`, and loads `/?demo=1`.
- The public API allows browser origins `https://argus.caniberk.dev` and `https://argus-eye.pages.dev`, limits requests per client and across the process, and caps request bodies at 128 KiB. The operator cookie and CSRF token protect simulator decisions in the sealed playback and metric placement in Visualization. The public placement endpoint accepts the five recorded ad pack definitions and applies their classifier results to a private in-memory graph held for the 30-minute session. Metric placement requests are limited to 16 KiB and 16 attempts per minute per session in each mode. `VITE_ARGUS_STATIC_REPLAY=1` selects the Pages-only fallback with offline verification. Timed playback, Ask, and approvals require the API.

## Stop or roll back

The default deployment directory is `~/.firstmate-secondmate-hacklab/data/argus-deploy/production`, with per-service logs under `logs/`. The three LaunchAgent links in `~/Library/LaunchAgents` restore the services at login. Stop the redeployer with `launchctl bootout gui/$(id -u)/dev.caniberk.argus.deploy`. Run `./scripts/deploy_cloudflare.sh --rollback` to republish and restart the prior successful release, if present. Leave the watcher stopped until a green replacement is ready. Use `./scripts/deploy_cloudflare.sh --web-only` to publish the sealed static fallback from green main. To stop the public API, boot out `dev.caniberk.argus.tunnel` and `dev.caniberk.argus.api` in the same launchd domain. Create `production/replay-only` and restart the API to serve recorded data when troubleshooting the live world.
