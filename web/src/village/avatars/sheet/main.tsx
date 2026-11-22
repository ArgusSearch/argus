// Dev-only avatar sheet (npm run dev, then /src/village/avatars/sheet/index.html): the seven agents live, every
// status, and an exporter for the brand kit. `window.argusAvatarSheet.png({ transparent, size })` paints the
// sheet into one canvas and returns a PNG data URL; `.single(role, { size, transparent })` paints one agent.

import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import { AgentAvatar } from "../AgentAvatar";
import { AvatarPainter, OVERSCAN, type AvatarStatus } from "../painter";
import { agentName, PERSONAS } from "../personas";
import { ROLE_IDS, type RoleId } from "../../roles";
import "./sheet.css";

const STATUSES: AvatarStatus[] = ["idle", "working", "waiting", "done"];

function Sheet() {
  const still = new URLSearchParams(location.search).has("still");
  return (
    <main className="sheet">
      <header>
        <span className="kicker">// Argus agents</span>
        <h1>Seven agents, one igloo each</h1>
      </header>
      <section className="row">
        {ROLE_IDS.map((role) => (
          <figure key={role} className="hero">
            <AgentAvatar role={role} size={150} nameplate paused={still} status={role === "operator" ? "waiting" : role === "detective" ? "working" : "idle"} />
            <figcaption>{PERSONAS[role].names[0].meaning}</figcaption>
          </figure>
        ))}
      </section>
      <section className="statuses">
        {ROLE_IDS.map((role) => (
          <div key={role} className="status-row">
            <b>{agentName(role)}</b>
            {STATUSES.map((s) => (
              <span key={s} className="cell">
                <AgentAvatar role={role} size={44} status={s} paused={still} />
                <small>{s}</small>
              </span>
            ))}
            <span className="cell">
              <AgentAvatar role={role} size={24} status="working" paused={still} />
              <small>24 px</small>
            </span>
          </div>
        ))}
      </section>
    </main>
  );
}

/** Paints one agent at `size` into a new canvas, after `warm` seconds of idle motion so the fur is baked. */
async function paintOne(role: RoleId, size: number, status: AvatarStatus = "idle"): Promise<HTMLCanvasElement> {
  const painter = new AvatarPainter(PERSONAS[role], 0.37, false);
  painter.setStatus(status);
  const canvas = document.createElement("canvas");
  const px = Math.round(size * OVERSCAN);
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  // the fabric's pile bakes on idle time: paint, wait, paint again until it lands
  for (let i = 0; i < 6; i++) {
    painter.paint(ctx, size, 1, 0);
    await new Promise((r) => setTimeout(r, 120));
  }
  painter.paint(ctx, size, 1, 0);
  return canvas;
}

function plate(ctx: CanvasRenderingContext2D, role: RoleId, cx: number, top: number, scale: number) {
  const p = PERSONAS[role];
  const name = agentName(role);
  ctx.save();
  ctx.font = `600 ${Math.round(26 * scale)}px "IBM Plex Mono", monospace`;
  const w1 = ctx.measureText(name).width;
  ctx.font = `500 ${Math.round(17 * scale)}px "IBM Plex Mono", monospace`;
  const w2 = ctx.measureText(p.title.toUpperCase()).width;
  const w = Math.max(w1, w2) + 34 * scale;
  const h = 66 * scale;
  ctx.fillStyle = "rgba(11,19,32,0.82)";
  ctx.beginPath();
  ctx.roundRect(cx - w / 2, top, w, h, 12 * scale);
  ctx.fill();
  ctx.fillStyle = p.glow;
  ctx.fillRect(cx - w / 2 + 12 * scale, top + h - 4 * scale, w - 24 * scale, 3 * scale);
  ctx.textAlign = "center";
  ctx.fillStyle = "#ffffff";
  ctx.font = `600 ${Math.round(26 * scale)}px "IBM Plex Mono", monospace`;
  ctx.fillText(name, cx, top + 30 * scale);
  ctx.fillStyle = p.glow;
  ctx.font = `500 ${Math.round(17 * scale)}px "IBM Plex Mono", monospace`;
  ctx.fillText(p.title.toUpperCase(), cx, top + 52 * scale);
  ctx.restore();
}

async function sheetPng(opts: { transparent?: boolean; size?: number } = {}): Promise<string> {
  await document.fonts.ready;
  const size = opts.size ?? 300;
  const cell = size * 1.3;
  const scale = size / 300;
  const pad = 60 * scale;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(pad * 2 + cell * ROLE_IDS.length);
  canvas.height = Math.round(pad * 2 + size * OVERSCAN + 90 * scale);
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  if (!opts.transparent) {
    const g = ctx.createLinearGradient(0, 0, 0, canvas.height);
    g.addColorStop(0, "#c3c9d6");
    g.addColorStop(1, "#a2a8b5");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  for (const [i, role] of ROLE_IDS.entries()) {
    const one = await paintOne(role, size);
    const cx = pad + cell * i + cell / 2;
    ctx.drawImage(one, cx - (size * OVERSCAN) / 2, pad - size * 0.12);
    plate(ctx, role, cx, pad + size * 1.32, scale);
  }
  return canvas.toDataURL("image/png");
}

async function singlePng(role: RoleId, opts: { transparent?: boolean; size?: number; nameplate?: boolean } = {}): Promise<string> {
  await document.fonts.ready;
  const size = opts.size ?? 512;
  const one = await paintOne(role, size);
  const scale = size / 300;
  const canvas = document.createElement("canvas");
  canvas.width = one.width;
  canvas.height = one.height + (opts.nameplate ? Math.round(40 * scale) : 0);
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  if (!opts.transparent) {
    ctx.fillStyle = "#a2a8b5";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  ctx.drawImage(one, 0, 0);
  if (opts.nameplate) plate(ctx, role, canvas.width / 2, size * 1.3, scale);
  return canvas.toDataURL("image/png");
}

(window as unknown as Record<string, unknown>).argusAvatarSheet = { png: sheetPng, single: singlePng, roles: ROLE_IDS };

createRoot(document.getElementById("sheet") as HTMLElement).render(<Sheet />);
