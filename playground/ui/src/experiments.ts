// One-click policy edits that change a decision on the recorded demo (checked against real answers).
import type { TemplateName } from "./api";

export interface Experiment {
  id: string;
  title: string;
  expect: string;
  edit: (yaml: string) => string;
}

/** Comment out a single-line rule so it can be switched back on. */
export const disableRule = (yaml: string, line: string): string =>
  yaml.replace(line, line.replace(/^(\s*)- /, "$1# - "));
export const enableRule = (yaml: string, line: string): string =>
  yaml.replace(line.replace(/^(\s*)- /, "$1# - "), line);

const ruleLine = (yaml: string, name: string): string =>
  yaml.split("\n").find((l) => l.includes(`name: ${name},`)) ?? "";

export const EXPERIMENTS: Record<TemplateName, Experiment[]> = {
  "personal-memory": [
    {
      id: "no-rollback",
      title: "Turn off rollbacks",
      expect: "Message 4 no longer undoes the move, so Riyadh stays in memory.",
      edit: (y) => disableRule(y, ruleLine(y, "retracted")),
    },
    {
      id: "strict-update",
      title: "Only update on near-certain matches",
      expect: "Message 3 is saved as a new fact next to Dubai. Message 4 then needs a live call, because the memory it sees changed.",
      edit: (y) => y.replace("conflict.p > 0.6", "conflict.p > 0.995"),
    },
  ],
  "dev-sessions": [
    {
      id: "drop-unverified",
      title: "Drop unverified work",
      expect: "The fix nobody tested is ignored instead of saved with an “unverified” label.",
      edit: (y) => y.replace("then: store_labeled, label: unverified}", "then: reject}"),
    },
  ],
};
