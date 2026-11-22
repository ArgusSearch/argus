import { useEffect, useSyncExternalStore } from "react";
import { apiUrl, staticReplay } from "../lib/deployment";
import type { Level } from "./model";

export interface Lines { wiggle_z: number; pair_z: number; alarm_z: number }
export interface Thresholds extends Lines {
  per_metric: Record<string, Lines>;
  supported: number;
  stop: number;
  plan_band: number;
  plan_min: number;
  freshness: number;
  calm_hours: number;
  checks: number;
}
export interface Budgets {
  requests: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  wall_seconds: number;
  monthly_usd: number | null;
}
export interface QuietHours {
  enabled: boolean;
  start: string;
  end: string;
  timezone: string;
  weekends: boolean;
  bypass_eur: number | null;
}
export interface DataSource {
  id: string;
  name: string;
  connector: "shopify" | "ga4" | "google-ads" | "meta-ads" | "stripe" | "http";
  url: string;
}
export interface Settings {
  autonomy: Record<string, Level>;
  playbooks: { disabled: string[] };
  thresholds: Thresholds;
  budgets: Budgets;
  quiet_hours: QuietHours;
  channels: { in_app: boolean; slack: boolean; email: boolean; pagerduty: boolean; webhook: boolean };
  sources: { sources: DataSource[] };
  ai: { provider: "openai" | "anthropic" | null; model: string; api_key_configured: boolean };
  notifications: { email: string; slack_url_configured: boolean; pagerduty_url_configured: boolean; webhook_url_configured: boolean };
  account: { name: string; email: string };
  appearance: { theme: "light" | "dark" | null; language: "en" | "de" };
}

interface Snapshot {
  revision: number;
  settings: Settings;
  undoable: Area[];
  simulator: boolean;
}

class SettingsError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

let csrf: Promise<string> | undefined;
let loading: Promise<void> | undefined;
let state: { snapshot: Snapshot | null; error: string | null } = {
  snapshot: null,
  error: staticReplay ? "Settings require the live API." : null,
};
const listeners = new Set<() => void>();

function publish(snapshot: Snapshot | null, error: string | null = null) {
  state = { snapshot, error };
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};

async function request<T>(path: string, method: string, token?: string, body?: Record<string, unknown>): Promise<T> {
  const response = await fetch(apiUrl(`/settings${path}`), {
    method,
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(12000),
    headers: {
      ...(token ? { "X-Argus-CSRF": token } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const message = typeof data?.detail === "string" ? data.detail : "Settings request failed.";
    throw new SettingsError(message, response.status);
  }
  return response.json() as Promise<T>;
}

function session() {
  csrf ??= request<{ csrf_token: string }>("/operator/session", "POST").then(
    (reply) => reply.csrf_token,
    (error: unknown) => { csrf = undefined; throw error; },
  );
  return csrf;
}

async function authorized<T>(path: string, method = "GET", body?: Record<string, unknown>): Promise<T> {
  const token = await session();
  try {
    return await request<T>(path, method, token, body);
  } catch (error) {
    if (!(error instanceof SettingsError && error.status === 403 && error.message.includes("CSRF token are required"))) throw error;
    if (await csrf === token) csrf = undefined;
    return request<T>(path, method, await session(), body);
  }
}

export function loadSettings(): Promise<void> {
  if (staticReplay) return Promise.resolve();
  loading ??= authorized<Snapshot>("").then(
    (snapshot) => publish(snapshot),
    (error: unknown) => publish(state.snapshot, error instanceof Error ? error.message : "Could not load settings."),
  ).finally(() => { loading = undefined; });
  return loading;
}

export function useOperatorSettings() {
  const current = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    if (!state.snapshot && !state.error) void loadSettings();
  }, []);
  return current;
}

async function write(path: string, method: string, body: Record<string, unknown>) {
  try {
    const saved = await authorized<Snapshot>(path, method, body);
    publish(saved);
    return saved;
  } catch (error) {
    if (error instanceof SettingsError && error.status === 409) await loadSettings();
    throw error;
  }
}

export type Area = keyof Settings;

export function saveSettings(area: Area, revision: number, changes: Record<string, unknown>) {
  return write(`/${area.replaceAll("_", "-")}`, "PATCH", { revision, changes });
}

export function undoSettings(area: Area, revision: number) {
  return write(`/${area.replaceAll("_", "-")}/undo`, "POST", { revision });
}

export function resetSettings(revision: number) {
  return write("/reset", "POST", { revision, confirm: "reset" });
}

export function testConnection(area: "sources" | "notifications", body: Record<string, unknown>) {
  return authorized<{ ok: boolean }>(`/${area}/test`, "POST", body);
}

export async function downloadData(scope: "settings" | "run") {
  const data = scope === "settings" ? (await authorized<Snapshot>("/export")).settings : await authorized("/export/run");
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `argus-${scope}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

