import { ButtonItem, PanelSection, PanelSectionRow, TextField } from "@decky/ui";
import type { DiagnosticSnapshot, DriveObservation } from "../api/types";
import { dumpOffer } from "../state/dumpOffer";
import { versionLabel } from "../state/updateNotice";
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
  updateMessage,
  updateOfferLabel,
  redumperMessage,
  onUpdateRedumper,
  onCheckUpdate,
  onInstallUpdate,
  onRefresh,
  onProbeEvent,
  onVersionPolicy,
  pendingEjectId,
  onMount,
  onUnmount,
  onEject,
  onPickIso,
  onUnmountIso,
  imageName,
  onImageName,
  outputRoot,
  pendingForceJobId,
  onChooseDumpFolder,
  onDump,
  onCancelDump,
  onForceDump,
  onAcknowledgeDump,
}: {
  snapshot: DiagnosticSnapshot | null;
  busy: boolean;
  error: string | null;
  updateMessage: string | null;
  updateOfferLabel: string | null;
  redumperMessage: string | null;
  onUpdateRedumper: () => void;
  onCheckUpdate: () => void;
  onInstallUpdate: () => void;
  onRefresh: () => void;
  onProbeEvent: () => void;
  onVersionPolicy: () => void;
  pendingEjectId: string | null;
  onMount: (driveId: string, generation: number, mediaGeneration: number) => void;
  onUnmount: (driveId: string, generation: number) => void;
  onEject: (driveId: string, generation: number) => void;
  onPickIso: () => void;
  onUnmountIso: (imageId: string) => void;
  imageName: string;
  onImageName: (value: string) => void;
  outputRoot: string | null;
  pendingForceJobId: string | null;
  onChooseDumpFolder: () => void;
  onDump: (driveId: string, generation: number) => void;
  onCancelDump: (jobId: string) => void;
  onForceDump: (jobId: string) => void;
  onAcknowledgeDump: (jobId: string) => void;
}) {
  const identity = snapshot?.identity;
  const redumper = snapshot?.probes?.redumper;
  const cdemu = snapshot?.probes?.cdemu;
  const steam = snapshot?.probes?.steam;
  const drives = snapshot?.drives ?? [];
  const dumpTargets: Array<DriveObservation | null> = drives.length > 0 ? drives : [null];
  return (
    <>
      <PanelSection title="Dump">
        <PanelSectionRow>
          <div>
            {redumper?.build
              ? `Redumper build ${redumper.build}${redumper.origin === "updated" ? ", from Update Redumper" : ", shipped with DiscDeck"}.`
              : "The Redumper build shipped with DiscDeck is not available."}{" "}
            Dumps use only that copy. A system or container install is not used. The disc must be unmounted, and a finished command is not a verified dump.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onUpdateRedumper} disabled={busy}>
            Update Redumper
          </ButtonItem>
        </PanelSectionRow>
        {redumperMessage ? (
          <PanelSectionRow>
            <div>{redumperMessage}</div>
          </PanelSectionRow>
        ) : null}
        <PanelSectionRow>
          <TextField label="Image name" value={imageName} disabled={busy} onChange={(event) => onImageName(event.target.value)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <div>
            {outputRoot
              ? `Output folder ${outputRoot}`
              : "Open the folder, then press Select. A highlighted row only opens the next folder."}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onChooseDumpFolder} disabled={busy}>
            Choose dump folder
          </ButtonItem>
        </PanelSectionRow>
        {dumpTargets.map((drive) => {
          const offer = dumpOffer(drive, outputRoot);
          const key = drive ? `dump-${drive.drive_id}` : "dump-none";
          return (
            <PanelSectionRow key={key}>
              <ButtonItem
                layout="below"
                onClick={() => {
                  if (drive) {
                    onDump(drive.drive_id, drive.generation ?? 1);
                  }
                }}
                disabled={busy || !offer.enabled}
              >
                {offer.label}
              </ButtonItem>
              {offer.reason ? <div>{offer.reason}</div> : null}
            </PanelSectionRow>
          );
        })}
        {(snapshot?.jobs.length ?? 0) === 0 ? (
          <PanelSectionRow>
            <div>No dump is recorded.</div>
          </PanelSectionRow>
        ) : (
          snapshot?.jobs.map((job) => (
            <PanelSectionRow key={job.job_id}>
              <div>
                {job.state} · {job.image_name} · {job.generic_scsi_node ?? "no sg node"} · {job.output_dir} · {job.verification ?? "unverified"} · {job.message}
              </div>
              {job.state === "running" || job.state === "orphaned_running" ? (
                <ButtonItem layout="below" onClick={() => onCancelDump(job.job_id)} disabled={busy}>
                  Cancel dump
                </ButtonItem>
              ) : null}
              {job.state === "cancel_requested" ? (
                <ButtonItem layout="below" onClick={() => onForceDump(job.job_id)} disabled={busy}>
                  {pendingForceJobId === job.job_id ? "Confirm force stop" : "Force stop"}
                </ButtonItem>
              ) : null}
              {job.needs_ack ? (
                <ButtonItem layout="below" onClick={() => onAcknowledgeDump(job.job_id)} disabled={busy}>
                  Dump process is gone. Release this drive
                </ButtonItem>
              ) : null}
            </PanelSectionRow>
          ))
        )}
      </PanelSection>
      <PanelSection title="Diagnostics">
        <PanelSectionRow>
          <div>
            Refresh only reads inventory. Mount, unmount, eject, an ISO mount, and a Redumper dump run when you press those buttons. The result stays in the message below.
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
          <div>{versionLabel(snapshot?.build?.version, snapshot?.build?.commit)} · hardware validated: no</div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onCheckUpdate} disabled={busy}>
            Check for updates
          </ButtonItem>
        </PanelSectionRow>
        {updateMessage ? (
          <PanelSectionRow>
            <div>{updateMessage}</div>
          </PanelSectionRow>
        ) : null}
        {updateOfferLabel ? (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={onInstallUpdate} disabled={busy}>
              {`Install ${updateOfferLabel}`}
            </ButtonItem>
          </PanelSectionRow>
        ) : null}
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
            Redumper: {redumper?.build ? `build ${redumper.build}` : "missing"}
            {redumper?.origin === "updated" ? " (updated)" : redumper?.origin === "bundled" ? " (shipped with DiscDeck)" : ""}; executed {redumper?.executed ? "yes" : "no"}
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
