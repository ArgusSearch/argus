# Operator settings

In Mission Control, open **Settings**, choose a section, and save the edits. **Undo** restores the previous values for that section during the API process's lifetime. Detection and autonomy settings are read at the next live tick. Model and budget settings are read when the next investigation starts. Quiet hours hold external notices until the next eligible tick in the configured timezone. The emergency threshold uses estimated EUR impact per hour.

On the local API, a live world's settings are stored in `.argus-settings.json` beside its DuckDB file. A local replay uses `~/.local/state/argus/settings.json`. The settings file has mode `0600`. Provider keys and webhook URLs stay on the server. The API returns only whether each secret is configured. The monthly model spend counter uses a private file beside the settings and rolls over at midnight UTC on the first of each month.

Start the API with `--agent live` to use a configured Anthropic or OpenAI provider. The provider default follows the deployment configuration. Select an explicit provider before supplying its model or key in Settings. All proposals still require operator approval before applying a fix.

Configure external notices in **Notifications**, use **Send test** on a saved destination, and enable the corresponding switch in **Channels**. Email requires an SMTP-over-TLS relay configured with `ARGUS_SMTP_HOST` and `ARGUS_SMTP_FROM`. The optional variables are `ARGUS_SMTP_PORT` (default `465`), `ARGUS_SMTP_USER`, and `ARGUS_SMTP_PASSWORD`. A webhook check uses the saved public HTTPS URL and refuses redirects. **Shop connection** saves and tests an HTTPS endpoint. The runtime continues to monitor the DuckDB world it was started with.

The public Cloudflare simulator gives each browser operator session its own temporary settings. Network tests, secrets, and external connections are available on the local API.

## HTTP interface

Open or resume a session with `POST /settings/operator/session`. Send its HttpOnly cookie and the returned `X-Argus-CSRF` token on all subsequent settings requests.

- `GET /settings` returns the settings snapshot and revision.
- `PATCH /settings/{area}` takes `revision` and a `changes` object containing the fields to save.
- `POST /settings/{area}/undo` takes the revision of the latest edit.
- `POST /settings/notifications/test` takes the saved destination's `channel`. `POST /settings/sources/test` takes the saved source's `id`.
- `GET /settings/export` downloads settings with secrets redacted. `GET /settings/export/run` downloads the current graph, incidents and notes.
- `POST /settings/reset` takes `revision` and `confirm: "reset"` to restore the default settings.
