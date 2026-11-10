import { ButtonItem, PanelSection, PanelSectionRow } from "@decky/ui";
import type { DiagnosticSnapshot } from "../api/types";
import { DependencyStatus } from "./DependencyStatus";

function mediaLabel(media: boolean | "unknown" | undefined): string {
  if (media === true) {
    return "media present";
  }
  if (media === false) {
    return "no media";
  }
  return "media unknown";
}

export function DiagnosticsPanel({
  snapshot,
  busy,
  error,
  onRefresh,
  onProbeEvent,
  onVersionPolicy,
}: {
  snapshot: DiagnosticSnapshot | null;
  busy: boolean;
  error: string | null;
  onRefresh: () => void;
  onProbeEvent: () => void;
  onVersionPolicy: () => void;
}) {
  const identity = snapshot?.identity;
  const redumper = snapshot?.probes?.redumper;
  const cdemu = snapshot?.probes?.cdemu;
  const steam = snapshot?.probes?.steam;
  return (
    <>
      <PanelSection title="Phase 0 diagnostics">
        <PanelSectionRow>
          <div>
            Read-only checks only. A successful refresh does not prove mount, eject, dump, virtual-disc, or game-launch behavior.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onRefresh} disabled={busy}>
            Refresh diagnostics
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onProbeEvent} disabled={busy}>
            Send probe event
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onVersionPolicy} disabled={busy}>
            Check Redumper version policy
          </ButtonItem>
        </PanelSectionRow>
        {error ? (
          <PanelSectionRow>
            <div>{error}</div>
          </PanelSectionRow>
        ) : null}
      </PanelSection>
      <PanelSection title="Runtime">
        <PanelSectionRow>
          <div>
            {identity
              ? `User ${identity.effective_user ?? "unknown"} uid ${identity.effective_uid ?? "unknown"} gid ${identity.effective_gid ?? "unknown"}; owner ${identity.owner_user ?? "unset"}; root flag ${identity.root_requested ? "yes" : "no"}; loader ${identity.loader_version ?? "not in environment"}`
              : "No snapshot yet."}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div>Build {snapshot?.build?.commit ?? "unpackaged"} · hardware validated: no</div>
        </PanelSectionRow>
      </PanelSection>
      {snapshot ? <DependencyStatus modules={snapshot.modules} /> : null}
      <PanelSection title="Drives">
        {(snapshot?.drives.length ?? 0) === 0 ? (
          <PanelSectionRow>
            <div>No optical sr nodes were visible to this process.</div>
          </PanelSectionRow>
        ) : (
          snapshot?.drives.map((drive) => (
            <PanelSectionRow key={drive.drive_id}>
              <div>
                {drive.block_node} → {drive.generic_scsi_node ?? "no sg node"} · {drive.vendor} {drive.model} · {drive.scsi_address ?? "no scsi address"}
                {drive.shared_bridge ? " · shared USB bridge" : ""} · {mediaLabel(drive.media_present)} · operations not run
              </div>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>
      <PanelSection title="Dependencies">
        <PanelSectionRow>
          <div>
            UDisks2: {snapshot?.probes?.udisks2?.status ?? "not collected"} {snapshot?.probes?.udisks2?.reason_code ?? ""}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div>
            Redumper: {redumper?.launch_kind ?? redumper?.status ?? "not collected"}; version {redumper?.version_status ?? "not collected"}; executed {redumper?.executed ? "yes" : "no"}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div>
            CDEmu: {cdemu?.reason_code ?? "not collected"}; active {cdemu?.active ? "yes" : "no"}; VHBA loaded {cdemu?.vhba_loaded ? "yes" : "no"}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <div>
            Steam: {steam?.status ?? "not collected"}; tools {(steam?.compatibility_tools ?? []).length}; shortcuts read {steam?.shortcuts_read ? "yes" : "no"}
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
