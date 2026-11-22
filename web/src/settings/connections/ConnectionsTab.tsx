import { useEffect, useRef, useState, type FormEvent } from "react";

import { publicApi, staticReplay } from "../../lib/deployment";
import { Badge, Btn, Card, Empty, Row } from "../ui";
import { disconnect, listConnections, syncConnection, type Connection, type Provider } from "./api";
import "./connections.css";

const PROVIDERS = {
  plausible: {
    name: "Plausible",
    description: "Website visitors, traffic sources, pageviews and goal completions.",
    target: "Site domain",
    placeholder: "example.com",
    key: "Stats API key",
    detail: "Use a Stats API key from the team that owns the site.",
    defaultTarget: "",
  },
  stripe: {
    name: "Stripe",
    description: "Gross payments, payment success and new subscriptions from Stripe test mode.",
    target: "Revenue currency",
    placeholder: "EUR",
    key: "Test API key",
    detail: "Use a restricted test key with read access to payments and subscriptions.",
    defaultTarget: "EUR",
  },
} satisfies Record<Provider, Record<string, string>>;

const STATE = {
  connected: { label: "Connected", tone: "ok" },
  missing: { label: "Missing key", tone: "muted" },
  error: { label: "Connection error", tone: "alarm" },
} as const;
const DATE = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function errorText(error: unknown) {
  return error instanceof Error && error.name !== "TimeoutError" && error.name !== "TypeError"
    ? error.message
    : "Could not reach the local Argus API. Try again.";
}

export function ConnectionsTab({ live }: { live: boolean }) {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const enabled = !publicApi && !staticReplay;

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    listConnections().then(
      (reply) => { if (active) setConnections(reply); },
      (failure: unknown) => { if (active) setError(errorText(failure)); },
    );
    return () => { active = false; };
  }, [enabled, retry]);

  if (!enabled) return (
    <>
      <p className="cs-note">Connect providers from the local Argus app.</p>
      <Card title={PROVIDERS.plausible.name} desc={PROVIDERS.plausible.description} action={<Badge>Local app</Badge>}>
        {null}
      </Card>
      <Card title="Google Analytics 4 (GA4)" desc="Website traffic and conversion events." action={<Badge>Planned</Badge>}>
        {null}
      </Card>
      <Card title={PROVIDERS.stripe.name} desc={PROVIDERS.stripe.description} action={<Badge>Test mode</Badge>}>
        {null}
      </Card>
    </>
  );
  if (!connections) return (
    <Card>
      <Empty>{error || "Reading connections…"}</Empty>
      {error && (
        <div className="cn-actions">
          <Btn onClick={() => { setError(null); setRetry((value) => value + 1); }}>Try again</Btn>
        </div>
      )}
    </Card>
  );

  return (
    <>
      {!live && <p className="cs-note">Start a live run to investigate imported metrics in the graph.</p>}
      {connections.map((connection) => <ConnectionCard key={connection.id} initial={connection} />)}
    </>
  );
}

function ConnectionCard({ initial }: { initial: Connection }) {
  const [connection, setConnection] = useState(initial);
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState<"test" | "disconnect" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const pasteKey = useRef<HTMLButtonElement>(null);
  const provider = PROVIDERS[connection.id];
  const state = STATE[connection.status];
  const target = connection.id === "stripe" ? connection.target?.toUpperCase() : connection.target;

  function finishEdit() {
    setEditing(false);
    pasteKey.current?.focus();
  }

  async function change(operation: "test" | "disconnect", credentials?: { key: string; target: string }) {
    setBusy(operation);
    setMessage(null);
    try {
      const reply = operation === "disconnect"
        ? await disconnect(connection.id)
        : await syncConnection(connection.id, credentials);
      setConnection(reply);
      if (reply.status !== "error" && credentials) finishEdit();
      if (reply.status !== "error" && operation === "disconnect") setRemoving(false);
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(null);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const key = String(fields.get("key") ?? "").trim();
    const target = String(fields.get("target") ?? "").trim();
    const field = event.currentTarget.elements.namedItem("key");
    if (field instanceof HTMLInputElement) field.value = "";
    void change("test", { key, target });
  }

  return (
    <Card
      title={provider.name}
      desc={provider.description}
      action={<span role="status"><Badge tone={state.tone} dot>{state.label}</Badge></span>}
    >
      <Row label="Last synced">
        {connection.last_synced ? (
          <time className="cn-time" dateTime={connection.last_synced}>{DATE.format(new Date(connection.last_synced))}</time>
        ) : <span className="cn-time">Never</span>}
      </Row>
      {connection.has_key && (
        <>
          <Row label={provider.target}><span className="cn-target">{target}</span></Row>
          <Row label={provider.key}><span className="cn-secret" aria-label="API key stored">••••••••</span></Row>
        </>
      )}
      {(message || connection.error) && <p className="cn-error" role="alert">{message || connection.error}</p>}
      <div className="cn-actions" aria-label={`${provider.name} connection actions`}>
        <button type="button" className="cs-btn" ref={pasteKey} disabled={busy !== null} aria-expanded={editing} onClick={() => {
          setRemoving(false);
          if (editing) finishEdit();
          else setEditing(true);
        }}>Paste key</button>
        {connection.has_key && !editing && (
          <>
            <button type="button" className="cs-btn" disabled={busy !== null || removing} onClick={() => void change("test")}>
              {busy === "test" ? "Testing connection…" : "Test connection"}
            </button>
            <button type="button" className="cs-btn" disabled={busy !== null} aria-expanded={removing} onClick={() => setRemoving((value) => !value)}>
              Disconnect
            </button>
          </>
        )}
      </div>
      {editing && (
        <form className="cn-form" onSubmit={save} aria-label={`Connect ${provider.name}`} aria-busy={busy !== null}>
          <label>
            <span>{provider.target}</span>
            <input required autoFocus autoComplete="off" spellCheck={false} autoCapitalize="off"
              name="target" placeholder={provider.placeholder} defaultValue={connection.target ?? provider.defaultTarget}
              maxLength={connection.id === "stripe" ? 3 : 253} disabled={busy !== null} />
          </label>
          <label>
            <span>{provider.key}</span>
            <input type="password" name="key" required autoComplete="new-password" maxLength={512}
              aria-describedby={`cn-${connection.id}-key`} disabled={busy !== null} />
          </label>
          <p className="cn-help" id={`cn-${connection.id}-key`}>{provider.detail}</p>
          <div className="cn-form-actions">
            <button className="cs-btn" type="submit" disabled={busy !== null}>{busy === "test" ? "Testing connection…" : "Test and save"}</button>
            <button className="cs-btn" type="button" disabled={busy !== null} onClick={finishEdit}>Cancel</button>
          </div>
        </form>
      )}
      {removing && (
        <div className="cn-form">
          <p className="cn-help">Remove this key and keep previously imported metrics.</p>
          <div className="cn-form-actions">
            <button type="button" className="cs-btn" disabled={busy !== null} onClick={() => void change("disconnect")}>
              {busy === "disconnect" ? "Disconnecting…" : "Confirm disconnect"}
            </button>
            <button type="button" className="cs-btn" disabled={busy !== null} onClick={() => setRemoving(false)}>Cancel</button>
          </div>
        </div>
      )}
    </Card>
  );
}
