export interface DumpDrive {
  block_node: string;
  media_present?: boolean | "unknown";
}

export interface DumpOffer {
  label: string;
  enabled: boolean;
  reason: string | null;
}

export function dumpOffer(drive: DumpDrive | null, outputRoot: string | null): DumpOffer {
  if (drive === null) {
    return { label: "Dump", enabled: false, reason: "No optical drive is visible." };
  }
  const label = `Dump ${drive.block_node}`;
  if (!outputRoot) {
    return { label, enabled: false, reason: "Choose a dump folder first." };
  }
  if (drive.media_present !== true) {
    const reason = drive.media_present === false ? "This drive has no media." : "Media presence is unknown. Refresh diagnostics.";
    return { label, enabled: false, reason };
  }
  return { label, enabled: true, reason: null };
}
