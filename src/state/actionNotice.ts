import type { Envelope } from "../api/types";

export function actionNotice(response: Envelope<Record<string, unknown>>): string {
  if (!response.ok) {
    return `${response.code}: ${response.message}`;
  }
  const action = response.result.action;
  if (action === "mount") {
    const mountPath = response.result.mount_path;
    return typeof mountPath === "string" && mountPath.length > 0
      ? `Mounted read-only at ${mountPath}`
      : "UDisks2 mounted the filesystem read-only.";
  }
  if (action === "unmount") {
    return "Unmounted the DiscDeck filesystem.";
  }
  if (action === "mount_iso") {
    const mountPath = response.result.mount_path;
    return typeof mountPath === "string" && mountPath.length > 0
      ? `Mounted the ISO read-only at ${mountPath}`
      : "UDisks2 mounted the ISO read-only.";
  }
  if (action === "unmount_iso") {
    return response.result.via === "already-gone"
      ? "The DiscDeck loop was already gone. The record was cleared."
      : "Unmounted the DiscDeck ISO and removed its loop.";
  }
  if (action === "start_dump") {
    return "Redumper started. Progress is indeterminate, and a finished process is not a verified dump.";
  }
  if (action === "cancel_dump") {
    return "Cancel was requested. The output folder was kept.";
  }
  if (action === "force_stop_dump") {
    return "Force stop was sent. The output folder was kept and was not verified.";
  }
  if (action === "acknowledge_dump") {
    return "This drive is no longer held by that dump. The output was kept and was not verified.";
  }
  if (action === "eject") {
    if (response.result.via === "user-eject") {
      return "UDisks2 did not authorize this process. The tray command ran as the current user.";
    }
    return response.result.via === "user-session"
      ? "UDisks2 accepted eject in the user session."
      : "UDisks2 accepted eject.";
  }
  return "DiscDeck finished the request.";
}
