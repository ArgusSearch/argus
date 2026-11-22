import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CODE_RULES } from "../../src/settings/constants";


describe("the settings page's code rules", () => {
  for (const rule of CODE_RULES) {
    it(`${rule.constant} matches ${rule.file}`, () => {
      const source = readFileSync(fileURLToPath(new URL(`../../../${rule.file}`, import.meta.url)), "utf8");
      const m = new RegExp(`^${rule.constant}\\s*=\\s*([0-9.]+)`, "m").exec(source);
      expect(m, `${rule.constant} not found in ${rule.file}`).not.toBeNull();
      expect(Number(m![1])).toBe(rule.value);
    });
  }
});
