// When the entry screen shows. It stands before the overview on a plain page load of the
// style layer, once per browser tab. Deep links go straight to what they name: the recording URL
// (/?demo=1&captions=1&fx=1), the agent presentation (?agentdemo=, ?agentrun=) and every ?view=... link skip it,
// so demo mode, recordings and tests never wait on a click.
//
//   entry=1   show it even after entering, or with a deep link (screenshots, the video's opening shot)
//   entry=0   never show it

/** sessionStorage key: set once the viewer entered Mission Control in this tab. */
export const ENTERED_KEY = "argus.entered";

/** Parameters that name what to show: a page load carrying one goes straight there. */
const DEEP_LINKS = ["demo", "view", "incident", "agentdemo", "agentrun", "village"] as const;

/** Pure: should this page load start on the entry screen? `entered` is this tab's remembered choice. */
export function entryWanted(search: string, entered: boolean): boolean {
  const params = new URLSearchParams(search);
  const asked = (params.get("entry") ?? "").trim().toLowerCase();
  if (asked === "1" || asked === "true") return true;
  if (asked === "0" || asked === "false") return false;
  if (DEEP_LINKS.some((key) => params.has(key))) return false;
  return !entered;
}

/** Pure: the address after entering, without the entry=1 override, so a reload lands on the overview. */
export function searchAfterEntry(search: string): string {
  const params = new URLSearchParams(search);
  params.delete("entry");
  const rest = params.toString();
  return rest ? `?${rest}` : "";
}

/** This tab's remembered choice; storage can be blocked (private windows, previews), which counts as not entered. */
export function readEntered(): boolean {
  try {
    return window.sessionStorage.getItem(ENTERED_KEY) === "1";
  } catch {
    return false;
  }
}

export function rememberEntered(): void {
  try {
    window.sessionStorage.setItem(ENTERED_KEY, "1");
  } catch {
    // blocked storage: the entry shows again on the next load, which is harmless
  }
}
