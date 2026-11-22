export const SETTINGS_TABS = ["autonomy", "playbooks", "thresholds", "budgets", "quiet-hours", "channels", "sources", "shop", "account", "ai", "notifications", "appearance", "data", "developer"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
