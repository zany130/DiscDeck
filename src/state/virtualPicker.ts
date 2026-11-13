/** FileSelectionType.FILE from @decky/api. The published package does not export the enum value. */
export const PICK_FILE = 0;

export interface VirtualPickerRequest {
  select: number;
  startPath: string;
  includeFiles: true;
  includeFolders: true;
  extensions: ["cue", "iso"];
  showHiddenFiles: false;
  allowAllFiles: true;
}

export function virtualPickerRequest(home: string | null | undefined): VirtualPickerRequest {
  const startPath = typeof home === "string" && home.startsWith("/") ? home : "/";
  return {
    select: PICK_FILE,
    startPath,
    includeFiles: true,
    includeFolders: true,
    extensions: ["cue", "iso"],
    showHiddenFiles: false,
    allowAllFiles: true,
  };
}

export function chosenDiscPath(picked: { path?: string; realpath?: string } | null | undefined): string | null {
  const realpath = picked?.realpath;
  if (typeof realpath === "string" && realpath.startsWith("/")) {
    return realpath;
  }
  const path = picked?.path;
  if (typeof path === "string" && path.startsWith("/")) {
    return path;
  }
  return null;
}
