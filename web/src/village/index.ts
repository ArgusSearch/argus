// Public entry of the Argus Village (lane G). The shell mounts <ArgusVillage onMetricMap={...} /> as a page;
// other lanes use the avatars from ./avatars.
export { ArgusVillage, type ArgusVillageProps } from "./ArgusVillage";
export { AgentAvatar, agentName, PERSONAS, type AgentAvatarProps, type AvatarStatus } from "./avatars";
export { ROLES, type RoleId } from "./roles";
export { SOURCES, type SourceId } from "./source";

/** The nav entry the shell adds for the village (lane E's sidebar). */
export const VILLAGE_NAV = {
  id: "village",
  group: "Monitor",
  label: "Agent village",
  hint: "The seven Argus agents at work, one igloo each: who is checking what, and what waits for you",
} as const;
