import { lazy, Suspense, type ReactNode } from "react";
import type { AgentRole } from "../lib/agent";
import type { Level } from "./model";

const AgentAvatar = lazy(() => import("../village/avatars").then(({ AgentAvatar }) => ({ default: AgentAvatar })));

export function Portrait({ role, size }: { role: AgentRole; size: number }) {
  return (
    <span className="cs-portrait" style={{ width: size, height: size }} aria-hidden="true">
      <Suspense fallback={null}>
        <AgentAvatar role={role} size={size} badge={false} paused />
      </Suspense>
    </span>
  );
}

export type Tone = "ok" | "watch" | "alarm" | "probe" | "calm" | "muted";

export function PageHead({ title, lead, actions, children }: { title: string; lead: string; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="cs-head">
      <div className="cs-head-row">
        <div className="cs-head-text">
          <h1>{title}</h1>
          {lead && <p>{lead}</p>}
        </div>
        {actions && <div className="cs-head-actions">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

export function Card({ title, desc, action, children, className, flush }: { title?: ReactNode; desc?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`cs-card${flush ? " flush" : ""}${className ? ` ${className}` : ""}`}>
      {(title || action) && (
        <header className="cs-card-head">
          <div>
            {title && <h2>{title}</h2>}
            {desc && <p>{desc}</p>}
          </div>
          {action && <div className="cs-card-action">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Row({ label, help, children, lead }: { label: ReactNode; help?: ReactNode; children?: ReactNode; lead?: ReactNode }) {
  return (
    <div className="cs-row">
      {lead && <div className="cs-row-lead">{lead}</div>}
      <div className="cs-row-text">
        <span className="cs-row-label">{label}</span>
        {help && <span className="cs-row-help">{help}</span>}
      </div>
      {children !== undefined && <div className="cs-row-control">{children}</div>}
    </div>
  );
}

export function Badge({ tone = "muted", children, title, dot }: { tone?: Tone; children: ReactNode; title?: string; dot?: boolean }) {
  return (
    <span className={`cs-badge t-${tone}`} title={title}>
      {dot && <i aria-hidden="true" />}
      {children}
    </span>
  );
}

/** Label for settings that have no runtime effect. */
export function Preview() {
  return (
    <span className="cs-preview" title="Shown so you can see where it goes. Changing it would not change what Argus does.">
      Not configured
    </span>
  );
}

/** Where a value comes from: an API route or a source file. */
export function Source({ children }: { children: ReactNode }) {
  return <code className="cs-source">{children}</code>;
}

/** A switch that shows a state but cannot be flipped here. */
export function Switch({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`cs-switch${on ? " on" : ""}`} role="switch" aria-checked={on} aria-disabled="true" aria-label={label} title="Read-only">
      <i aria-hidden="true" />
    </span>
  );
}

const LEVELS: { id: Level; label: string }[] = [
  { id: "alone", label: "Alone" },
  { id: "asks", label: "Asks first" },
  { id: "off", label: "Off" },
];

/** The level picker of one rule: alone, asks first or off; read-only, the level comes from GET /autonomy. */
export function LevelPicker({ level, label }: { level: Level; label: string }) {
  return (
    <span className="cs-seg" role="radiogroup" aria-label={label} aria-readonly="true">
      {LEVELS.map((l) => (
        <span key={l.id} role="radio" aria-checked={l.id === level} aria-disabled="true" className={l.id === level ? `on l-${l.id}` : undefined}>
          {l.label}
        </span>
      ))}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="cs-empty">{children}</p>;
}

/** A plain button in the page's style. */
export function Btn({ children, onClick, title }: { children: ReactNode; onClick: () => void; title?: string }) {
  return (
    <button type="button" className="cs-btn" aria-label={title} onClick={onClick} title={title}>
      {children}
    </button>
  );
}

export interface SubNavGroup<T extends string> {
  label: string;
  items: { id: T; label: string }[];
}

/** The page's own section list (the Core settings sidebar). */
export function SubNav<T extends string>({ groups, current, onPick, label }: { groups: SubNavGroup<T>[]; current: T; onPick: (id: T) => void; label: string }) {
  return (
    <nav className="cs-subnav" aria-label={label}>
      {groups.map((g) => (
        <div key={g.label} className="cs-subnav-group">
          <span>{g.label}</span>
          <ul>
            {g.items.map((it) => (
              <li key={it.id}>
                <button type="button" className={it.id === current ? "on" : undefined} aria-current={it.id === current ? "page" : undefined} onClick={() => onPick(it.id)}>
                  <span className="cs-subnav-label">{it.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
