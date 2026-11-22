// Public entry of the Argus Ice style layer (report section 3.2), the default interface; with ?classic=1 (or
// fx=0) everything renders the classic interface. Do not import from ./scene.
export { fxFlags, fxOn, parseFx, type FxFlags, type FxQuality, type FxTheme } from "./flag";
export { GraphStage, type GraphSceneProps } from "./GraphStage";
export { StyleProvider, useFx, type FxPhase } from "./StyleProvider";
export * from "./ui";
export { openIncidentPage } from "./nav";
export { useStoryFocus } from "./workspace/story";
export { FxWorkspace, type WorkspaceProps } from "./workspace/Workspace";
