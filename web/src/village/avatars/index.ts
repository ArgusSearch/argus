// Public entry of the agent avatars: lanes import from here only.
//
//   import { AgentAvatar, agentName, PERSONAS } from "../village/avatars";
//   <AgentAvatar role="skeptic" status="working" size={32} />
//   <AgentAvatar role="operator" status="waiting" size={72} nameplate />
//
// Roles: watcher | detective | skeptic | market | narrator | operator | cartographer (RoleId).
// Status: idle | working | waiting | done | sleeping (AvatarStatus).
// `roleOfTool(tool)` maps a C5 trail step's or an agent activity record's tool to the role that runs it.
export { AgentAvatar, type AgentAvatarProps } from "./AgentAvatar";
export { AvatarPainter, OVERSCAN, type AvatarStatus } from "./painter";
export { agentName, PERSONAS, type AcronymOption, type HudDetail, type Persona } from "./personas";
export { roleOfTool } from "../beats";
export { ROLE, ROLE_IDS, ROLES, type Role, type RoleId } from "../roles";
