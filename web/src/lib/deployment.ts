const base = (import.meta.env.VITE_ARGUS_API_URL ?? "").replace(/\/+$/, "");

export const staticReplay = import.meta.env.VITE_ARGUS_STATIC_REPLAY === "1";
export const pollEvents = import.meta.env.VITE_ARGUS_POLL_EVENTS === "1";
export const publicApi = import.meta.env.VITE_ARGUS_PUBLIC_API === "1";
export const exampleShopName = "Boreal Outfitters";
const guided = typeof location === "undefined" ? "" : new URLSearchParams(location.search).get("demo") ?? "";
export const remoteGuidedRun = publicApi && /^(1|true|yes|on)$/i.test(guided);

export function apiUrl(path: string): string {
  return `${base}${remoteGuidedRun ? "/sealed-run" : ""}${path}`;
}
