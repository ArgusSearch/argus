// Who did it: the avatar of one of the seven agent roles. Lane G builds the avatars (web/src/village/avatars,
// `<AgentAvatar role status size nameplate />`, size in px, status idle | working | waiting | done | sleeping,
// one shared frame loop for every avatar on the page); until that module is in the build this slot draws a
// placeholder, the role's initial in a circle of its color with the role's short name.

import { lazy, Suspense, type ComponentType } from "react";
import type { AgentRole } from "../../lib/agent";

export interface AvatarProps {
  role: AgentRole;
  size?: "sm" | "md" | "lg";
  /** what the role is doing: drives a ring on lane G's avatar */
  status?: "idle" | "working" | "waiting" | "done" | "alarm";
  /** show the role's nameplate next to the face */
  nameplate?: boolean;
}

/** Names and short plates; lane G's module owns the final art, these are the words the placeholder shows. */
export const ROLE_TEXT: Record<AgentRole, { name: string; plate: string }> = {
  watcher: { name: "Watcher", plate: "WAT" },
  cartographer: { name: "Cartographer", plate: "CRT" },
  detective: { name: "Detective", plate: "DET" },
  market: { name: "Market Analyst", plate: "MKT" },
  skeptic: { name: "Skeptic", plate: "SKP" },
  narrator: { name: "Narrator", plate: "NAR" },
  operator: { name: "Operator", plate: "OPR" },
};

/** Lane G's props (web/src/village/avatars/AgentAvatar.tsx). */
interface LaneGAvatarProps {
  role: AgentRole;
  status?: "idle" | "working" | "waiting" | "done" | "sleeping";
  size?: number;
  nameplate?: boolean;
  badge?: boolean;
}
type AvatarModule = { AgentAvatar?: ComponentType<LaneGAvatarProps>; default?: ComponentType<LaneGAvatarProps> };

const PX: Record<NonNullable<AvatarProps["size"]>, number> = { sm: 24, md: 30, lg: 48 };
/** our statuses in lane G's set: a sent-back or fallen-back step works on (lane G has no alarm pose) */
const STATUS: Record<NonNullable<AvatarProps["status"]>, LaneGAvatarProps["status"]> = { idle: "idle", working: "working", waiting: "waiting", done: "done", alarm: "working" };
// import.meta.glob: an absent module builds to an empty map instead of failing
const files = import.meta.glob<AvatarModule>(["../../village/avatars.tsx", "../../village/avatars/index.tsx", "../../village/avatars/index.ts"]);
const load = Object.values(files)[0];
const Avatar = load
  ? lazy(() =>
      load().then((m) => {
        const component = m.AgentAvatar ?? m.default;
        if (!component) throw new Error("web/src/village/avatars exports no AgentAvatar");
        return { default: component };
      }),
    )
  : null;

function Placeholder({ role, size = "sm", status, nameplate }: AvatarProps) {
  const t = ROLE_TEXT[role];
  return (
    <span className={`ws-avatar s-${size}${status ? ` st-${status}` : ""}`} style={{ ["--role" as string]: `var(--role-${role})` }} title={t.name}>
      <i aria-hidden="true">{t.name[0]}</i>
      {nameplate && <b>{t.plate}</b>}
      <span className="sr-only">{t.name}</span>
    </span>
  );
}

export function AvatarSlot(props: AvatarProps) {
  if (!Avatar) return <Placeholder {...props} />;
  return (
    <Suspense fallback={<Placeholder {...props} />}>
      <span className={`ws-avatar-g s-${props.size ?? "sm"}`}>
        <Avatar role={props.role} size={PX[props.size ?? "sm"]} status={props.status ? STATUS[props.status] : "idle"} badge={false} />
        {props.nameplate && <b>{ROLE_TEXT[props.role].plate}</b>}
      </span>
    </Suspense>
  );
}
