const base = (import.meta.env.VITE_ARGUS_API_URL ?? "").replace(/\/+$/, "");

export const staticReplay = import.meta.env.VITE_ARGUS_STATIC_REPLAY === "1";

export function apiUrl(path: string): string {
  return `${base}${path}`;
}
