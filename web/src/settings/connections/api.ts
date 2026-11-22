import { apiUrl } from "../../lib/deployment";

export type Provider = "plausible" | "stripe";

export interface Connection {
  id: Provider;
  status: "connected" | "missing" | "error";
  has_key: boolean;
  last_synced: string | null;
  error: string | null;
  target: string | null;
}

let session: Promise<string> | undefined;

class ConnectionError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, method: string, token?: string, body?: { key: string; target: string }): Promise<T> {
  const response = await fetch(apiUrl(`/connections${path}`), {
    method,
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(path.endsWith("/connect") || path.endsWith("/test") ? 120_000 : 12_000),
    headers: {
      ...(token ? { "X-Argus-CSRF": token } : {}),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const message = response.status === 404
      ? "Connections are available in the local Argus app."
      : typeof data?.detail === "string" ? data.detail : "Could not complete the connection request.";
    throw new ConnectionError(message, response.status);
  }
  return response.json() as Promise<T>;
}

function operatorToken() {
  session ??= request<{ csrf_token: string }>("/operator/session", "POST").then(
    (reply) => reply.csrf_token,
    (error: unknown) => { session = undefined; throw error; },
  );
  return session;
}

async function authorized<T>(path: string, method = "GET", body?: { key: string; target: string }): Promise<T> {
  const current = operatorToken();
  try {
    return await request<T>(path, method, await current, body);
  } catch (error) {
    if (!(error instanceof ConnectionError && error.status === 403 && error.message.includes("CSRF token"))) throw error;
    if (session === current) session = undefined;
    return request<T>(path, method, await operatorToken(), body);
  }
}

export const listConnections = () => authorized<Connection[]>("");
export const syncConnection = (id: Provider, credentials?: { key: string; target: string }) =>
  authorized<Connection>(`/${id}/${credentials ? "connect" : "test"}`, "POST", credentials);
export const disconnect = (id: Provider) => authorized<Connection>(`/${id}/disconnect`, "POST");
