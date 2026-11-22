export const SETTINGS_TABS = ["autonomy", "playbooks", "thresholds", "budgets", "quiet-hours", "channels", "sources"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
