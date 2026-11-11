/** FileSelectionType.FILE from @decky/api. The published package does not export the enum value. */
export const PICK_FILE = 0;

export interface IsoPickerRequest {
  select: number;
  startPath: string;
  includeFiles: true;
  includeFolders: true;
  extensions: ["iso"];
  showHiddenFiles: false;
  allowAllFiles: true;
}

export function isoPickerRequest(home: string | null | undefined): IsoPickerRequest {
  const startPath = typeof home === "string" && home.startsWith("/") ? home : "/";
  return {
    select: PICK_FILE,
    startPath,
    includeFiles: true,
    includeFolders: true,
    extensions: ["iso"],
    showHiddenFiles: false,
    allowAllFiles: true,
  };
}

export function chosenIsoPath(picked: { path?: string; realpath?: string } | null | undefined): string | null {
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
