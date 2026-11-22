import { lazy, Suspense, type ReactNode } from "react";
import type { AgentRole } from "../lib/agent";
import { useAgent } from "../fx/workspace/agent";
import type { Level } from "./model";
import { useText } from "./language";

const AgentAvatar = lazy(() => import("../village/avatars").then(({ AgentAvatar }) => ({ default: AgentAvatar })));

export function Portrait({ role, size }: { role: AgentRole; size: number }) {
  const { enabled, avatars } = useAgent();
  const cue = avatars[role];
  return (
    <span className="cs-portrait" style={{ width: size, height: size }} aria-hidden="true">
      <Suspense fallback={null}>
        <AgentAvatar role={role} size={size} status={cue?.status} motionKey={cue?.key} badge={cue?.status === "waiting"} paused={!enabled} />
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
  const tr = useText();
  return (
    <section className={`cs-card${flush ? " flush" : ""}${className ? ` ${className}` : ""}`}>
      {(title || action) && (
        <header className="cs-card-head">
          <div>
            {title && <h2>{typeof title === "string" ? tr(title) : title}</h2>}
            {desc && <p>{typeof desc === "string" ? tr(desc) : desc}</p>}
          </div>
          {action && <div className="cs-card-action">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Row({ label, help, children, lead }: { label: ReactNode; help?: ReactNode; children?: ReactNode; lead?: ReactNode }) {
  const tr = useText();
  return (
    <div className="cs-row">
      {lead && <div className="cs-row-lead">{lead}</div>}
      <div className="cs-row-text">
        <span className="cs-row-label">{typeof label === "string" ? tr(label) : label}</span>
        {help && <span className="cs-row-help">{typeof help === "string" ? tr(help) : help}</span>}
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

/** Where a value comes from: an API route or a source file. */
export function Source({ children }: { children: ReactNode }) {
  return <code className="cs-source">{children}</code>;
}

export function Switch({ on, label, onChange }: { on: boolean; label: string; onChange: (on: boolean) => void }) {
  const tr = useText();
  return (
    <button type="button" className={`cs-switch${on ? " on" : ""}`} role="switch" aria-checked={on} aria-label={tr(label)} onClick={() => onChange(!on)}>
      <i aria-hidden="true" />
    </button>
  );
}

const LEVELS: { id: Level; label: string }[] = [
  { id: "alone", label: "Alone" },
  { id: "asks", label: "Asks first" },
  { id: "off", label: "Off" },
];

export function LevelPicker({ level, allowed, label, onChange }: { level: Level; allowed: Level; label: string; onChange: (level: Level) => void }) {
  const tr = useText();
  return (
    <span className="cs-seg" role="group" aria-label={label}>
      {LEVELS.map((choice) => (
        <button key={choice.id} type="button" aria-pressed={choice.id === level} disabled={choice.id !== "off" && choice.id !== allowed}
          className={choice.id === level ? `on l-${choice.id}` : undefined} onClick={() => onChange(choice.id)}>
          {tr(choice.label)}
        </button>
      ))}
    </span>
  );
}

export function NumberInput({ label, value, step = 1, min = 0, max, onChange }: {
  label: string; value: number | null; step?: number; min?: number; max?: number; onChange: (value: number | null) => void;
}) {
  const tr = useText();
  return <input className="cs-input cs-number-input" type="number" aria-label={tr(label)} value={value ?? ""}
    min={min} max={max} step={step} onChange={(event) => onChange(event.target.value === "" ? null : event.target.valueAsNumber)} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="cs-empty">{children}</p>;
}

/** A plain button in the page's style. */
export function Btn({ children, onClick, title, disabled }: { children: ReactNode; onClick: () => void; title?: string; disabled?: boolean }) {
  return (
    <button type="button" className="cs-btn" disabled={disabled} aria-label={title} onClick={onClick} title={title}>
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
