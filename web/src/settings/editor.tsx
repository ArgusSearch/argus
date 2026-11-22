import { useState, type ReactNode } from "react";
import { useText } from "./language";
import { saveSettings, undoSettings, useOperatorSettings, type Area, type Settings } from "./operator";
import { Btn } from "./ui";

export interface Editor<T> {
  value: T;
  set: <K extends keyof T>(key: K, value: T[K]) => void;
  change: (key: string, value: unknown) => void;
  changes: Record<string, unknown>;
  simulator: boolean;
}

export function EditorSection<K extends Area>({ area, children }: {
  area: K;
  children: (editor: Editor<Settings[K]>) => ReactNode;
}) {
  const { snapshot } = useOperatorSettings();
  const tr = useText();
  const [draft, setDraft] = useState<{ base: number; changes: Record<string, unknown> } | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!snapshot) return null;

  const { settings, revision, simulator } = snapshot;
  const changes = draft?.changes ?? {};
  const changed = Object.keys(changes).length > 0;
  const value = { ...settings[area], ...changes };
  const change = (key: string, next: unknown) => {
    setDraft((previous) => ({ base: previous?.base ?? revision, changes: { ...previous?.changes, [key]: next } }));
    setError("");
    setMessage("");
  };

  const commit = async (undo: boolean) => {
    setBusy(true);
    setError("");
    try {
      if (undo) await undoSettings(area, revision);
      else await saveSettings(area, draft?.base ?? revision, changes);
      setDraft(null);
      setMessage(undo ? "Undone" : "Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save settings.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <fieldset className="cs-fields" disabled={busy} aria-busy={busy}>
        {children({ value, change, set: (key, next) => change(String(key), next), changes, simulator })}
      </fieldset>
      <div className="cs-head-actions">
        <Btn disabled={!changed || busy} onClick={() => void commit(false)}>{tr(busy ? "Saving" : "Save")}</Btn>
        {changed && <Btn disabled={busy} onClick={() => { setDraft(null); setError(""); }}>{tr("Discard")}</Btn>}
        {!changed && snapshot.undoable.includes(area) && <Btn disabled={busy} onClick={() => void commit(true)}>{tr("Undo")}</Btn>}
        <span role="status" aria-live="polite">{message && tr(message)}</span>
      </div>
      {error && <p className="cs-note" role="alert">{error}</p>}
    </>
  );
}
