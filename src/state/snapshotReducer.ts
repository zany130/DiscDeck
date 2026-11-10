import type { DiagnosticSnapshot } from "../api/types";

export interface SnapshotDecision {
  snapshot: DiagnosticSnapshot;
  accepted: boolean;
  reason?: "initial" | "new_epoch" | "stale_revision" | "current";
}

export function acceptSnapshot(current: DiagnosticSnapshot | null, incoming: DiagnosticSnapshot): SnapshotDecision {
  if (!current) {
    return { snapshot: incoming, accepted: true, reason: "initial" };
  }
  if (incoming.epoch !== current.epoch) {
    return { snapshot: incoming, accepted: true, reason: "new_epoch" };
  }
  if (incoming.revision < current.revision) {
    return { snapshot: current, accepted: false, reason: "stale_revision" };
  }
  return { snapshot: incoming, accepted: true, reason: "current" };
}
