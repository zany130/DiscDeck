import { describe, expect, it } from "vitest";
import type { DiagnosticSnapshot } from "../api/types";
import { acceptSnapshot } from "./snapshotReducer";

function snapshot(epoch: string, revision: number): DiagnosticSnapshot {
  return {
    epoch,
    revision,
    phase: "0",
    hardware_validated: false,
    settings_revision: 0,
    modules: [],
    drives: [],
    virtual_slots: [],
    jobs: [],
    identity: {},
  };
}

describe("acceptSnapshot", () => {
  it("accepts the first snapshot", () => {
    const decision = acceptSnapshot(null, snapshot("epoch-a", 1));
    expect(decision.accepted).toBe(true);
    expect(decision.reason).toBe("initial");
  });

  it("replaces state when the backend epoch changes", () => {
    const decision = acceptSnapshot(snapshot("epoch-a", 4), snapshot("epoch-b", 1));
    expect(decision.accepted).toBe(true);
    expect(decision.snapshot.epoch).toBe("epoch-b");
  });

  it("ignores an older revision from the same epoch", () => {
    const current = snapshot("epoch-a", 3);
    const decision = acceptSnapshot(current, snapshot("epoch-a", 2));
    expect(decision.accepted).toBe(false);
    expect(decision.snapshot).toBe(current);
  });
});
