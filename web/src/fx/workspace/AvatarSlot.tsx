// Who did it: the avatar of one of the seven agent roles. Lane G builds the avatars (web/src/village/avatars,
// `<AgentAvatar role status size nameplate />`, size in px, status idle | working | waiting | done | sleeping,
// one shared frame loop for every avatar on the page); until that module is in the build this slot draws a
// placeholder, the role's initial in a circle of its color with the role's short name.

import { lazy, Suspense, type ComponentType } from "react";
import { useAppState } from "../../lib/AppState";
import { AGENT_ROLES, type AgentRole } from "../../lib/agent";
import type { AgentAvatarProps } from "../../village/avatars/AgentAvatar";
import type { AvatarCue } from "../../village/avatars/state";
import { useAgent } from "./agent";
import { openAgentChat } from "./chatStore";

export interface AvatarProps {
  role: AgentRole;
  size?: "sm" | "md" | "lg";
  /** what the role is doing: drives a ring on lane G's avatar */
  status?: "idle" | "working" | "waiting" | "done" | "alarm";
  cue?: AvatarCue;
  showThought?: boolean;
  paused?: boolean;
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

type AvatarModule = { AgentAvatar?: ComponentType<AgentAvatarProps>; default?: ComponentType<AgentAvatarProps> };

const PX: Record<NonNullable<AvatarProps["size"]>, number> = { sm: 24, md: 30, lg: 48 };
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

function Placeholder({ role, size = "sm", status, cue, nameplate }: AvatarProps) {
  const t = ROLE_TEXT[role];
  const state = cue?.status ?? status;
  return (
    <span className={`ws-avatar s-${size}${state ? ` st-${state}` : ""}`} style={{ ["--role" as string]: `var(--role-${role})` }} title={t.name}>
      <i aria-hidden="true">{t.name[0]}</i>
      {nameplate && <b>{t.plate}</b>}
      <span className="sr-only">{t.name}</span>
    </span>
  );
}

export function AvatarSlot(props: AvatarProps) {
  if (!Avatar) return <Placeholder {...props} />;
  const status = props.cue?.status ?? (props.status === "alarm" ? "done" : props.status);
  return (
    <Suspense fallback={<Placeholder {...props} />}>
      <span className={`ws-avatar-g s-${props.size ?? "sm"}`}>
        <Avatar
          role={props.role}
          size={PX[props.size ?? "sm"]}
          status={status}
          motionKey={props.cue?.key}
          thought={props.showThought ? props.cue?.text : undefined}
          badge={status === "waiting"}
          paused={props.paused}
        />
        {props.nameplate && <b>{ROLE_TEXT[props.role].plate}</b>}
      </span>
    </Suspense>
  );
}

export function AgentTeam({ compact = false }: { compact?: boolean }) {
  const { enabled } = useAgent();
  const { monitor } = useAppState();
  if (!enabled) return null;
  return (
    <div className={compact ? "fx-demo ws-side-team" : "ws-agent-team"} role="group" aria-label="Agent team">
      <div className="ws-agent-team-faces">
        {AGENT_ROLES.map((role) => (
          <button key={role} type="button" className="ws-agent-chat" onClick={() => openAgentChat(role)} aria-label={`Chat with the ${ROLE_TEXT[role].name}`} title={`Chat with the ${ROLE_TEXT[role].name}`}>
            <AvatarSlot role={role} size={compact ? "sm" : "lg"} cue={monitor.avatars[role]} showThought />
          </button>
        ))}
      </div>
    </div>
  );
}
