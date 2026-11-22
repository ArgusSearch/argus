# Argus Desktop

Argus Desktop bundles the Mission Control web build, the FastAPI server and the MockMart data. Double-click Argus to open it. The app waits for the local API and starts the sealed S4 agent replay by default. Without a key, replay runs offline.

## Install

- **macOS** — Open the DMG, drag `Argus.app` to Applications, then open Argus. The local disk image is unsigned and the app is unnotarized. If macOS blocks the first launch, try **right-click Open** or **System Settings → Privacy & Security → Open Anyway**. For a build you produced or trust, you can also clear the downloaded quarantine attribute with `xattr -cr /Applications/Argus.app`. The local build targets the Mac's own architecture.
- **Windows x64** — Run the NSIS `.exe` installer, then open **Argus** from the Start menu. The installer is unsigned.

## Settings and agent mode

Open **Argus → Settings** on macOS or **File → Settings** on Windows. The shortcut is **⌘+,** or **Ctrl+,**. Save your Anthropic API key to start the live agent over a local S1 MockMart simulation. The first live start generates the DuckDB world. **Remove key** returns to sealed replay. Switching modes restarts the API and the current run. Live agent calls can incur provider charges. Argus stores the key in macOS Keychain or Windows Credential Manager and passes it to the bundled provider in memory.

## Build and smoke-test

Use Python 3.13 with `uv` and Node.js 24 or newer. Build on the host OS and architecture you want to ship. On Windows, pass `--config core.autocrlf=false` to `git clone` to preserve the bytes verified by the sealed replay manifest. The Windows workflow applies the same setting at checkout. Run these from the repository root, one at a time.

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

Electron provides the same Chromium runtime on macOS and Windows and manages the bundled Python child process through standard pipes. PyInstaller builds that child alongside the locked FastAPI and DuckDB dependencies. The OS allocates an ephemeral `127.0.0.1` port, and each launch uses a private session token. The app waits for `/health` before opening Mission Control, retries a crashed sidecar once and closes the sidecar's control pipe on quit.

The build reuses FastAPI's existing static mount and health route. The frozen Python layout preserves the existing resource lookup, and the Vite build uses same-origin requests. The replay loader compares artifact names in the manifest's forward-slash format so that nested artifacts verify on Windows. The desktop app builds directly from `web/`.

## Third-party notices

The [desktop npm lockfile](package-lock.json) pins Electron and electron-builder. The [sidecar build script](scripts/build.mjs) pins PyInstaller and Keyring. The notice paths below are relative to the installed app directory in the [tested Windows build](https://github.com/ArgusSearch/argus/actions/runs/45001389510/artifacts/14745519890).

| Component | Version | Role and notice |
| --- | --- | --- |
| Electron | 45.4.1 | MIT. Runs the desktop shell. The app ships `LICENSE.electron.txt` and Chromium's `LICENSES.chromium.html`. |
| electron-builder | 26.18.0 | MIT. Build dependency that assembles the app and generates the installers. [Upstream source and license](https://github.com/electron-userland/electron-builder) |
| Keyring | 25.7.0 | MIT. Stores the provider key in the system credential store. The frozen API ships its notice at `resources/sidecar/src/keyring-25.7.0.dist-info/licenses/LICENSE`. |
| PyInstaller | 6.22.3 | Freezes the API and embeds its bootloader and runtime hooks in `argus-sidecar.exe`. The bootloader has a GPL-2.0-or-later exception for generated executables. The bundled runtime hooks use Apache-2.0. [PyInstaller license and exception](https://pyinstaller.org/en/stable/license.html) |

The [Mission Control credits](../README.md#prior-work-and-inspiration) also apply to the bundled web build.
