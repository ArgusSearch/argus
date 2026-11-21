import { spawn, type ChildProcess } from "node:child_process";

// A replay API a spec starts and stops itself, on its own port, next to the shared Playwright server.
// Every wait is bounded; stopApi signals the whole process group (uv and its Python child).
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function isUp(base: string): Promise<boolean> {
  try {
    return (await fetch(`${base}/health`, { signal: AbortSignal.timeout(1000) })).ok;
  } catch {
    return false;
  }
}

export interface OwnApi {
  proc: ChildProcess;
  base: string;
}

/** Start `uv run argus api --port <port> [args]` from the repo root and wait (at most 30 s) for /health. */
export async function startApi(port: number, args: string[] = []): Promise<OwnApi> {
  const base = `http://127.0.0.1:${port}`;
  if (await isUp(base)) throw new Error(`port ${port} is already serving: stop it first (pkill -f "argus api --port ${port}")`);
  const proc = spawn("uv", ["run", "argus", "api", "--port", String(port), ...args], { cwd: "..", stdio: "ignore", detached: true });
  for (let i = 0; i < 120; i++) {
    if (await isUp(base)) return { proc, base };
    if (proc.exitCode !== null) break;
    await sleep(250);
  }
  await stopApi({ proc, base });
  throw new Error(`API on ${port} (${args.join(" ")}) did not start within 30 s`);
}

/** SIGINT the process group, then SIGKILL if the port still answers after 5 s. Safe to call twice or with null. */
export async function stopApi(api: OwnApi | null): Promise<void> {
  const pid = api?.proc.pid;
  if (!api || !pid) return;
  const signal = (sig: NodeJS.Signals) => {
    try {
      process.kill(-pid, sig);
    } catch {
      /* already gone */
    }
  };
  signal("SIGINT");
  for (let i = 0; i < 20; i++) {
    if (!(await isUp(api.base))) return;
    await sleep(250);
  }
  signal("SIGKILL");
  for (let i = 0; i < 8; i++) {
    if (!(await isUp(api.base))) return;
    await sleep(250);
  }
}
