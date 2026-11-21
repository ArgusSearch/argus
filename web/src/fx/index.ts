// Public entry of the Argus Ice style layer (report section 3.2). Everything renders today's interface unless
// the page was opened with ?fx=1 or ?fx=night. Do not import from ./scene.
export { fxFlags, fxOn, parseFx, type FxFlags, type FxQuality, type FxTheme } from "./flag";
export { GraphStage, type GraphSceneProps } from "./GraphStage";
export { StyleProvider, useFx, type FxPhase } from "./StyleProvider";
export * from "./ui";
