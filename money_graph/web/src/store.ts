import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Simulation } from "./types";
type Selection = {
  block: string[];
  caseIds: string[];
  scenarios: Simulation[];
};
type State = {
  shortcuts: boolean;
  setShortcuts: (enabled: boolean) => void;
  theme: "light" | "dark";
  language: string;
  selections: Record<string, Selection>;
  setTheme: () => void;
  setLanguage: (v: string) => void;
  add: (pid: string, kind: "block" | "caseIds", ids: string[]) => void;
  remove: (pid: string, kind: "block" | "caseIds", id: string) => void;
  scenario: (pid: string, s: Simulation) => void;
  forget: (pid: string) => void;
};
export const emptySelection: Selection = {
  block: [],
  caseIds: [],
  scenarios: [],
};
export const useWorkspace = create<State>()(
  persist(
    (set) => ({
      shortcuts: true,
      setShortcuts: (shortcuts) => set({ shortcuts }),
      theme: matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light",
      language: "ru",
      selections: {},
      forget: (pid) =>
        set((s) => {
          const selections = { ...s.selections };
          delete selections[pid];
          return { selections };
        }),
      setTheme: () =>
        set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setLanguage: (language) => set({ language }),
      add: (pid, kind, ids) =>
        set((s) => ({
          selections: {
            ...s.selections,
            [pid]: {
              ...(s.selections[pid] || emptySelection),
              [kind]: [
                ...new Set([
                  ...(s.selections[pid] || emptySelection)[kind],
                  ...ids,
                ]),
              ],
            },
          },
        })),
      remove: (pid, kind, id) =>
        set((s) => ({
          selections: {
            ...s.selections,
            [pid]: {
              ...(s.selections[pid] || emptySelection),
              [kind]: (s.selections[pid] || emptySelection)[kind].filter(
                (x) => x !== id,
              ),
            },
          },
        })),
      scenario: (pid, result) =>
        set((s) => ({
          selections: {
            ...s.selections,
            [pid]: {
              ...(s.selections[pid] || emptySelection),
              scenarios: [
                ...(s.selections[pid] || emptySelection).scenarios,
                result,
              ],
            },
          },
        })),
    }),
    { name: "money-graph-workspace-v2" },
  ),
);
