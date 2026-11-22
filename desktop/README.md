# Argus Desktop

Argus Desktop bundles the Mission Control web build, the FastAPI server and the MockMart data. Double-click Argus to open it. The app waits for the local API and starts the sealed S4 agent replay by default. Without a key, replay runs offline.

## Install

- **macOS** — Open the DMG, drag `Argus.app` to Applications, then open Argus. The local disk image is unsigned and the app is unnotarized. If macOS blocks the first launch, try **right-click Open** or **System Settings → Privacy & Security → Open Anyway**. For a build you produced or trust, you can also clear the downloaded quarantine attribute with `xattr -cr /Applications/Argus.app`. The local build targets the Mac's own architecture.
- **Windows x64** — Run the NSIS `.exe` installer, then open **Argus** from the Start menu. The installer is unsigned.

## Settings and agent mode

Open **Argus → Settings** on macOS or **File → Settings** on Windows. The shortcut is **⌘+,** or **Ctrl+,**. Save your Anthropic API key to start the live agent over a local S1 MockMart simulation. The first live start generates the DuckDB world. **Remove key** returns to sealed replay. Switching modes restarts the API and the current run. Live agent calls can incur provider charges. Argus stores the key in macOS Keychain or Windows Credential Manager and passes it to the bundled provider in memory.

## Build and smoke-test

Use Python 3.13 with `uv` and Node.js 24 or newer. Build on the host OS and architecture you want to ship. Run these from the repository root, one at a time.

```sh
npm --prefix web ci
npm --prefix desktop ci
npm --prefix desktop run build
```

Installers land in `desktop/dist/`. The macOS build produces a DMG, and on Windows it produces an x64 NSIS installer. The build uses the project's `uv.lock` for Python runtime dependencies and a separate npm lockfile for the desktop shell. To smoke-test a packaged app, pass the executable to `npm --prefix desktop run smoke -- <executable>`. On an Apple Silicon Mac, use the executable inside the packaged app.

```sh
npm --prefix desktop run smoke -- desktop/dist/mac-arm64/Argus.app/Contents/MacOS/Argus --visible
```

The smoke test uses a temporary profile and a hidden window by default. It checks `/health`, verifies that the API rejects an unauthenticated request, opens Settings, drives the bundled Mission Control page into the sealed S4 replay and checks that the sidecar exits and closes its listener. On Windows, the workflow runs the smoke test against the app installed by the NSIS artifact.

## Windows workflow

The Desktop workflow builds the **Argus-Windows-x64** artifact for relevant pull requests. Push a `desktop-v*` tag or dispatch the workflow with a new desktop release tag to attach the tested installer to a draft GitHub Release. Dispatch builds the selected ref, so use the commit you intend to release. Publishing the draft is a separate GitHub action for the release owner.

## Architecture

Both `node` and `cargo` were available on the Apple Silicon build host. Electron provides the same Chromium runtime on macOS and Windows and manages the bundled Python child process through standard pipes. PyInstaller builds that child alongside the locked FastAPI and DuckDB dependencies. The OS allocates an ephemeral `127.0.0.1` port, and each launch uses a private session token. The app waits for `/health` before opening Mission Control, retries a crashed sidecar once and closes the sidecar's control pipe on quit.

The build reuses FastAPI's existing static mount and health route. The frozen Python layout preserves the existing resource lookup, and the Vite build uses same-origin requests. This integration requires zero source changes under `web/` or `src/argus/`.
