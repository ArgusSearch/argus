// The investigation rules Argus runs with that the API does not serve. Each value is copied from the named source
// file and constant; constants.test.ts reads those files and fails when a value here drifts from the code.

export interface CodeRule {
  key: string;
  label: string;
  help: string;
  value: number;
  /** how the page prints it */
  show: string;
  /** repo-relative source file and constant name */
  file: string;
  constant: string;
}

export const CODE_RULES: CodeRule[] = [
  {
    key: "supported",
    label: "Smallest share for a supported cause",
    help: "A cause must explain at least this much of the change before the verdict may call it supported.",
    value: 0.2,
    show: "20%",
    file: "src/argus/investigate/procedure.py",
    constant: "SUPPORTED_MIN_EXPLAINED",
  },
  {
    key: "stop",
    label: "Stop searching once explained",
    help: "The investigation stops looking for more causes once this share of the change is explained.",
    value: 0.8,
    show: "80%",
    file: "src/argus/investigate/procedure.py",
    constant: "STOP_EXPLAINED",
  },
  {
    key: "plan-band",
    label: "A plan counts as kept within",
    help: "Delivered within this share of the planned uplift (or 5 points, whichever is wider) is logged as planned instead of paged.",
    value: 0.25,
    show: "±25%",
    file: "src/argus/investigate/procedure.py",
    constant: "PLAN_BAND_REL",
  },
  {
    key: "plan-min",
    label: "Smallest plan band",
    help: "The band around a small plan never gets narrower than this many points.",
    value: 0.05,
    show: "5 points",
    file: "src/argus/investigate/procedure.py",
    constant: "PLAN_BAND_MIN",
  },
  {
    key: "late-data",
    label: "Late data below",
    help: "A source table delivered below this share for the hour is a data issue: Argus waits instead of scoring.",
    value: 0.8,
    show: "80% delivered",
    file: "src/argus/watcher/freshness.py",
    constant: "DATA_ISSUE_BELOW",
  },
  {
    key: "calm",
    label: "Resolve after calm hours",
    help: "An incident under watch closes itself after this many normal hours in a row.",
    value: 3,
    show: "3 hours",
    file: "src/argus/incidents/lifecycle.py",
    constant: "CALM_HOURS",
  },
  {
    key: "checks",
    label: "Most checks per investigation",
    help: "An investigation runs at most this many checks before it must write its verdict.",
    value: 12,
    show: "12 checks",
    file: "src/argus/investigate/ledger.py",
    constant: "MAX_CHECKS",
  },
];
