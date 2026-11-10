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
