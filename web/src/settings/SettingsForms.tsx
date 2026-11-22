import { useState } from "react";
import { EditorSection, type Editor } from "./editor";
import { useText } from "./language";
import { downloadData, resetSettings, testConnection, useOperatorSettings, type DataSource, type Settings } from "./operator";
import { Badge, Btn, Card, Empty, Row } from "./ui";

export function AccountTab() {
  const tr = useText();
  return <EditorSection area="account">{(editor) => <Card title="Your profile">
    <Row label="Name"><input className="cs-input" aria-label={tr("Name")} value={editor.value.name} autoComplete="name"
      maxLength={120} onChange={(event) => editor.set("name", event.target.value)} /></Row>
    <Row label="Email"><input className="cs-input" aria-label={tr("Email")} type="email" value={editor.value.email}
      maxLength={254} autoComplete="email" onChange={(event) => editor.set("email", event.target.value)} /></Row>
  </Card>}</EditorSection>;
}

export function AppearanceTab() {
  const tr = useText();
  return <EditorSection area="appearance">{(editor) => <Card title="Appearance">
    <Row label="Theme"><select className="cs-input" aria-label={tr("Theme")} value={editor.value.theme ?? ""}
      onChange={(event) => editor.set("theme", (event.target.value || null) as Settings["appearance"]["theme"])}>
      <option value="">{tr("Default")}</option>
      <option value="light">{tr("Light")}</option>
      <option value="dark">{tr("Dark")}</option>
    </select></Row>
    <Row label="Language"><select className="cs-input" aria-label={tr("Language")} value={editor.value.language}
      onChange={(event) => editor.set("language", event.target.value === "de" ? "de" : "en")}>
      <option value="en">English</option>
      <option value="de">Deutsch</option>
    </select></Row>
  </Card>}</EditorSection>;
}

export function AiTab() {
  const tr = useText();
  return <EditorSection area="ai">{(editor) => {
    const { provider, model, api_key_configured } = editor.value;
    return <Card title="AI model" desc="Changes apply to the next live model run. Provider keys are stored on the local API server.">
      <Row label="Provider">
        <select className="cs-input" aria-label={tr("Provider")} value={provider ?? ""} onChange={(event) => {
          editor.set("provider", (event.target.value || null) as Settings["ai"]["provider"]);
          editor.set("model", "");
          if (editor.changes.api_key !== undefined) editor.change("api_key", null);
        }}>
          <option value="">{tr("Provider default")}</option>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
        </select>
      </Row>
      <Row label="Model" help="Leave blank to use the provider’s default.">
        <input className="cs-input" aria-label={tr("Model")} maxLength={100} disabled={!provider} value={model}
          placeholder={tr("Provider default")} onChange={(event) => editor.set("model", event.target.value)} />
      </Row>
      <SecretField label="API key" configured={api_key_configured && !("provider" in editor.changes)}
        disabled={editor.simulator || !provider} value={editor.changes.api_key} onChange={(value) => editor.change("api_key", value)} />
      {editor.simulator && <Empty>{tr("Provider credentials are available on the local API.")}</Empty>}
    </Card>;
  }}</EditorSection>;
}

function SecretField({ label, configured, disabled, value, onChange }: {
  label: string; configured: boolean; disabled?: boolean; value: unknown; onChange: (value: string | null) => void;
}) {
  const tr = useText();
  return <Row label={label}>
    <span className="cs-chips end">
      <input className="cs-input" type="password" aria-label={tr(label)} autoComplete="new-password"
        spellCheck={false} maxLength={label === "API key" ? 512 : 2048} disabled={disabled}
        placeholder={configured && value !== null ? "••••••••" : ""}
        value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value || null)} />
      {configured && value !== null && <Btn disabled={disabled} onClick={() => onChange(null)}>{tr("Remove")}</Btn>}
    </span>
  </Row>;
}

const DESTINATIONS = [
  ["slack", "Slack webhook URL", "slack_url", "slack_url_configured"],
  ["pagerduty", "PagerDuty webhook URL", "pagerduty_url", "pagerduty_url_configured"],
  ["webhook", "Webhook URL", "webhook_url", "webhook_url_configured"],
] as const;

function TestButton({ area, body, disabled, label }: {
  area: "notifications" | "sources"; body: Record<string, unknown>; disabled: boolean; label: string;
}) {
  const tr = useText();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ message: string; ok: boolean }>();
  const run = async () => {
    setRunning(true);
    setResult(undefined);
    try {
      await testConnection(area, body);
      setResult({ message: area === "sources" ? "Connection reached" : "Test sent", ok: true });
    } catch (error) {
      setResult({ message: error instanceof Error ? error.message : "Test failed.", ok: false });
    } finally {
      setRunning(false);
    }
  };
  return <span className="cs-chips end">
    <Btn disabled={disabled || running} onClick={() => void run()}>{tr(running ? "Testing" : label)}</Btn>
    {result && <span role={result.ok ? "status" : "alert"}>{tr(result.message)}</span>}
  </span>;
}

export function NotificationsTab() {
  const tr = useText();
  return <EditorSection area="notifications">{(editor) => <>
    <Card title="Email" desc="The local API uses its configured SMTP server.">
      <Row label="Email">
        <input className="cs-input" aria-label={tr("Email")} type="email" autoComplete="email" maxLength={254}
          value={editor.value.email} onChange={(event) => editor.set("email", event.target.value)} />
      </Row>
      <Row label="Email test">
        <TestButton key={editor.value.email} area="notifications" body={{ channel: "email" }} label="Send test"
          disabled={editor.simulator || !editor.value.email || "email" in editor.changes} />
      </Row>
    </Card>
    <Card title="Outside channels" desc="Save each destination before testing it. A webhook test contacts the exact URL you provide.">
      {DESTINATIONS.map(([id, label, field, configured]) => <Destination key={id}
        channel={id} label={label} field={field} configured={editor.value[configured]} editor={editor} />)}
      {editor.simulator && <Empty>{tr("External delivery is available on the local API.")}</Empty>}
    </Card>
  </>}</EditorSection>;
}

function Destination({ channel, label, field, configured, editor }: {
  channel: string; label: string; field: string; configured: boolean; editor: Editor<Settings["notifications"]>;
}) {
  return <>
    <SecretField label={label} configured={configured} disabled={editor.simulator} value={editor.changes[field]}
      onChange={(value) => editor.change(field, value)} />
    <Row label={`${label} test`}>
      <TestButton key={`${configured}:${field in editor.changes}`} area="notifications" body={{ channel }} label="Send test"
        disabled={editor.simulator || !configured || field in editor.changes} />
    </Row>
  </>;
}

const CONNECTORS = {
  shopify: "Shopify",
  ga4: "Google Analytics 4",
  "google-ads": "Google Ads",
  "meta-ads": "Meta Ads",
  stripe: "Stripe",
  http: "HTTPS",
} satisfies Record<DataSource["connector"], string>;

export function ShopTab() {
  return <EditorSection area="sources">{(editor) => <ShopConnections editor={editor} />}</EditorSection>;
}

function ShopConnections({ editor }: { editor: Editor<Settings["sources"]> }) {
  const tr = useText();
  const update = (id: string, change: Partial<DataSource>) =>
    editor.set("sources", editor.value.sources.map((source) => source.id === id ? { ...source, ...change } : source));
  return <>
    <Card title="Shop connection" desc="Register the public HTTPS endpoint for a data source and test its response."
      action={<Btn disabled={editor.simulator || editor.value.sources.length >= 20} onClick={() => editor.set("sources", [
        ...editor.value.sources, { id: crypto.randomUUID(), name: "", connector: "shopify", url: "" },
      ])}>{tr("Add source")}</Btn>}>
      {editor.value.sources.length === 0 && <Empty>{tr(editor.simulator ? "External connections are available on the local API." : "No external sources configured.")}</Empty>}
    </Card>
    {editor.value.sources.map(({ id, connector, name, url }) => <Card key={id} title={name || CONNECTORS[connector]}
      action={<Badge>{CONNECTORS[connector]}</Badge>}>
      <Row label="Name"><input className="cs-input" aria-label={tr("Name")} value={name} maxLength={120}
        onChange={(event) => update(id, { name: event.target.value })} /></Row>
      <Row label="Connector"><select className="cs-input" aria-label={tr("Connector")} value={connector}
        onChange={(event) => update(id, { connector: event.target.value as DataSource["connector"] })}>
        {Object.entries(CONNECTORS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></Row>
      <Row label="Endpoint URL"><input className="cs-input" type="url" aria-label={tr("Endpoint URL")} value={url} maxLength={2048}
        onChange={(event) => update(id, { url: event.target.value })} /></Row>
      <Row label="Connection">
        <span className="cs-chips end">
          <TestButton key={url} area="sources" body={{ id }} label="Test connection" disabled={editor.simulator || "sources" in editor.changes} />
          <Btn onClick={() => editor.set("sources", editor.value.sources.filter((source) => source.id !== id))}>{tr("Remove")}</Btn>
        </span>
      </Row>
    </Card>)}
  </>;
}

export function DataTab() {
  const { snapshot } = useOperatorSettings();
  const tr = useText();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; message: string }>();
  if (!snapshot) return null;
  const perform = async (action: "reset" | "settings" | "run") => {
    setBusy(true);
    setStatus(undefined);
    try {
      if (action === "reset") await resetSettings(snapshot.revision);
      else await downloadData(action);
      setConfirm(false);
      setStatus({ ok: true, message: action === "reset" ? "Settings reset" : "Download ready" });
    } catch (error) {
      setStatus({ ok: false, message: error instanceof Error ? error.message : "Request failed." });
    } finally {
      setBusy(false);
    }
  };
  return <Card title="Export and reset">
    <Row label="Download settings" help="Download a JSON copy. Saved credentials are represented by their configured status.">
      <Btn disabled={busy} onClick={() => void perform("settings")}>{tr("Download settings")}</Btn>
    </Row>
    <Row label="Download run data" help="Download a JSON snapshot of the current graph, incidents and notes.">
      <Btn disabled={busy} onClick={() => void perform("run")}>{tr("Download run data")}</Btn>
    </Row>
    <Row label="Reset settings" help="Restore every setting to its default and clear saved credentials.">
      {confirm ? <span className="cs-chips end">
        <Btn disabled={busy} onClick={() => setConfirm(false)}>{tr("Cancel")}</Btn>
        <Btn disabled={busy} onClick={() => void perform("reset")}>{tr("Confirm reset")}</Btn>
      </span> : <Btn disabled={busy} onClick={() => setConfirm(true)}>{tr("Reset settings")}</Btn>}
    </Row>
    {status && <p role={status.ok ? "status" : "alert"}>{tr(status.message)}</p>}
  </Card>;
}
