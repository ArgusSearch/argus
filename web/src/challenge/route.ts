// Which challenge screen the URL asks for. `?challenge` alone or `=pick` is the big-screen start, `=run`
// is Mission Control with the commitment banner, `=reveal` the reveal, `=verify` the phone page.

export type Screen = "pick" | "run" | "reveal" | "verify";

export interface Route {
  screen: Screen;
  /** A commitment carried in the link (the phone page gets it from the QR code before the run). */
  commitment: string | null;
  /** The laptop's address as a phone sees it, e.g. 192.168.1.20:8000. */
  lan: string | null;
}

const SCREENS: Screen[] = ["pick", "run", "reveal", "verify"];

export function parseRoute(search: string): Route | null {
  const q = new URLSearchParams(search);
  if (!q.has("challenge")) return null;
  const value = (q.get("challenge") ?? "").toLowerCase();
  const screen = (SCREENS as string[]).includes(value) ? (value as Screen) : "pick";
  return { screen, commitment: q.get("c"), lan: q.get("lan") };
}

/** The same URL with the challenge screen (and optional extras) set, other parameters kept. */
export function routeHref(search: string, screen: Screen | null, extra: Record<string, string | null> = {}): string {
  const q = new URLSearchParams(search);
  if (screen) q.set("challenge", screen);
  else q.delete("challenge");
  for (const [k, v] of Object.entries(extra)) {
    if (v === null) q.delete(k);
    else q.set(k, v);
  }
  const s = q.toString();
  return s ? `?${s.replace(/=(&|$)/g, "$1")}` : "?";
}

/** Phones cannot open the laptop's loopback address. */
export function isLoopback(host: string): boolean {
  const name = host.replace(/:\d+$/, "").replace(/^\[|\]$/g, "");
  return name === "localhost" || name === "::1" || /^127\./.test(name);
}

/** The link a phone opens to check the commitment, built from the address it can reach. */
export function phoneLink(origin: string, lan: string | null, commitment: string): string {
  const base = lan ? `${/^https?:\/\//.test(lan) ? "" : "http://"}${lan.replace(/\/+$/, "")}` : origin;
  return `${base}/?challenge=verify&c=${commitment.replace(/^sha256:/, "")}`;
}
