import { describe, expect, it } from "vitest";
import { CHANGED_EVENT, subscribeChanged } from "./events";

describe("subscribeChanged", () => {
  it("registers the Decky listener and removes that same function", () => {
    const added: { event?: string; listener?: (...args: unknown[]) => void } = {};
    const removed: { event?: string; listener?: (...args: unknown[]) => void } = {};
    const notices: string[] = [];
    const unsubscribe = subscribeChanged(
      (event, listener) => {
        added.event = event;
        added.listener = listener as (...args: unknown[]) => void;
        return listener;
      },
      (event, listener) => {
        removed.event = event;
        removed.listener = listener as (...args: unknown[]) => void;
      },
      (notice) => {
        notices.push(notice.domain);
      },
    );
    added.listener?.({ epoch: "epoch-a", revision: 1, domain: "diagnostics" });
    unsubscribe();
    expect(added.event).toBe(CHANGED_EVENT);
    expect(removed.event).toBe(CHANGED_EVENT);
    expect(removed.listener).toBe(added.listener);
    expect(notices).toEqual(["diagnostics"]);
  });
});
