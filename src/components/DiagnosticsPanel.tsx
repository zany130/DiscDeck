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
  pendingEjectId,
  onMount,
  onUnmount,
  onEject,
  onPickIso,
  onUnmountIso,
}: {
  snapshot: DiagnosticSnapshot | null;
  busy: boolean;
  error: string | null;
  onRefresh: () => void;
  onProbeEvent: () => void;
  onVersionPolicy: () => void;
  pendingEjectId: string | null;
  onMount: (driveId: string, generation: number, mediaGeneration: number) => void;
  onUnmount: (driveId: string, generation: number) => void;
  onEject: (driveId: string, generation: number) => void;
  onPickIso: () => void;
  onUnmountIso: (imageId: string) => void;
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
            Refresh only reads inventory. Mount, unmount, eject, and an ISO mount run when you press those buttons, and the result stays in the message below.
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
                {drive.shared_bridge ? " · shared USB bridge" : ""} · {mediaLabel(drive.media_present)} · not hardware-validated
              </div>
              <ButtonItem layout="below" onClick={() => onMount(drive.drive_id, drive.generation ?? 1, drive.media_generation ?? 1)} disabled={busy}>
                Mount read-only
              </ButtonItem>
              <ButtonItem layout="below" onClick={() => onUnmount(drive.drive_id, drive.generation ?? 1)} disabled={busy}>
                Unmount DiscDeck mount
              </ButtonItem>
              <ButtonItem layout="below" onClick={() => onEject(drive.drive_id, drive.generation ?? 1)} disabled={busy}>
                {pendingEjectId === drive.drive_id ? "Confirm eject" : "Eject"}
              </ButtonItem>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>
      <PanelSection title="Filesystem images">
        <PanelSectionRow>
          <div>
            A filesystem image is a read-only file mount. It is not a virtual disc and it does not use CDEmu. The picker lists folders. Open one and choose the .iso file.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onPickIso} disabled={busy}>
            Choose ISO and mount read-only
          </ButtonItem>
        </PanelSectionRow>
        {(snapshot?.images ?? []).length === 0 ? (
          <PanelSectionRow>
            <div>No DiscDeck filesystem image is recorded.</div>
          </PanelSectionRow>
        ) : (
          snapshot?.images?.map((image) => (
            <PanelSectionRow key={image.image_id}>
              <div>
                {image.backing_path}
                {image.mount_path ? ` · mounted at ${image.mount_path}` : ""} · read-only · not hardware-validated
              </div>
              <ButtonItem layout="below" onClick={() => onUnmountIso(image.image_id)} disabled={busy}>
                Unmount DiscDeck image
              </ButtonItem>
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
